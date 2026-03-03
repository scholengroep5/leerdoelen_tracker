"""
Auth routes - Microsoft Entra ID (Azure AD) OAuth2 + superadmin fallback

Flow voor Entra login:
1. Gebruiker klikt "Login met Microsoft"
2. Redirect naar Microsoft /authorize (common endpoint, werkt voor alle tenants)
3. Microsoft redirect terug naar /auth/callback met een code
4. We wisselen de code in voor tokens
5. We lezen het id_token uit → email, naam, oid, tid
6. We zoeken of maken de gebruiker aan in onze DB
7. We koppelen aan de juiste school via e-maildomein of bestaand account
"""

import os
import secrets
import logging
from datetime import datetime
from urllib.parse import urlencode, urlparse

import requests
from services.audit import audit_log
from app import db, limiter
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, jsonify, session, current_app)
from flask_login import login_user, logout_user, login_required, current_user
from models import User, School

logger   = logging.getLogger(__name__)
auth_bp  = Blueprint('auth', __name__)


def _safe_next_url(next_url: str | None) -> str:
    """Valideer dat de next-redirect intern blijft — voorkomt open redirect aanvallen."""
    if not next_url:
        return url_for('pages.dashboard')
    parsed = urlparse(next_url)
    # Weiger externe URLs (heeft netloc) of protocol-relative URLs
    if parsed.netloc or parsed.scheme:
        return url_for('pages.dashboard')
    # Zorg dat het pad begint met /
    if not next_url.startswith('/'):
        return url_for('pages.dashboard')
    return next_url

ENTRA_AUTHORITY    = "https://login.microsoftonline.com/common"
ENTRA_AUTH_URL     = f"{ENTRA_AUTHORITY}/oauth2/v2.0/authorize"
ENTRA_TOKEN_URL    = f"{ENTRA_AUTHORITY}/oauth2/v2.0/token"
ENTRA_USERINFO_URL = "https://graph.microsoft.com/v1.0/me"
ENTRA_SCOPES       = "openid profile email User.Read"


def _entra_client_id():
    return current_app.config.get('MICROSOFT_CLIENT_ID')

def _entra_client_secret():
    return current_app.config.get('MICROSOFT_CLIENT_SECRET')

def _callback_url():
    base = current_app.config.get('BASE_URL', 'http://localhost').rstrip('/')
    return f"{base}/auth/callback"

def _find_school_for_email(email: str):
    domain = email.split('@')[-1].lower()
    schools = School.query.all()
    for school in schools:
        if school.email_domains and domain in [d.lower() for d in school.email_domains]:
            return school
    return None

def _get_or_create_user(email, first_name, last_name, oid, tid):
    user = User.query.filter_by(oauth_provider='microsoft', oauth_id=oid).first()
    if user:
        user.first_name      = first_name or user.first_name
        user.last_name       = last_name  or user.last_name
        user.email           = email
        user.entra_tenant_id = tid
        db.session.commit()
        return user, False

    user = User.query.filter_by(email=email).first()
    if user:
        user.oauth_provider  = 'microsoft'
        user.oauth_id        = oid
        user.entra_tenant_id = tid
        user.first_name      = first_name or user.first_name
        user.last_name       = last_name  or user.last_name
        db.session.commit()
        return user, False

    school = _find_school_for_email(email)
    user = User(
        email=email, first_name=first_name, last_name=last_name,
        role='teacher', school_id=school.id if school else None,
        oauth_provider='microsoft', oauth_id=oid,
        entra_tenant_id=tid, is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user, True


@auth_bp.route('/superadmin')
def superadmin_page():
    """Directe loginpagina voor de platformbeheerder."""
    if current_user.is_authenticated:
        return redirect(url_for('pages.dashboard'))
    return render_template('superadmin_login.html')


@auth_bp.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('pages.dashboard'))
    entra_configured  = bool(_entra_client_id() and _entra_client_secret())
    google_configured = bool(_google_client_id() and _google_client_secret())
    org_name = current_app.config.get('ORG_NAME', 'GO! Scholengroep')
    return render_template('login.html', entra_configured=entra_configured,
                           google_configured=google_configured, org_name=org_name)


@auth_bp.route('/logout')
@login_required
def logout():
    audit_log('logout', 'auth')
    logout_user()
    if _entra_client_id():
        post_logout = current_app.config.get('BASE_URL', 'http://localhost') + '/auth/login'
        return redirect(
            f"https://login.microsoftonline.com/common/oauth2/v2.0/logout"
            f"?post_logout_redirect_uri={post_logout}"
        )
    return redirect(url_for('auth.login'))


@auth_bp.route('/microsoft')
@limiter.limit('20 per minute')
def microsoft_login():
    if not _entra_client_id():
        flash('Microsoft login is niet geconfigureerd.', 'error')
        return redirect(url_for('auth.login'))

    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state

    params = {
        'client_id':     _entra_client_id(),
        'response_type': 'code',
        'redirect_uri':  _callback_url(),
        'scope':         ENTRA_SCOPES,
        'state':         state,
        'response_mode': 'query',
        'prompt':        'select_account',
    }
    return redirect(f"{ENTRA_AUTH_URL}?{urlencode(params)}")


@auth_bp.route('/callback')
@limiter.limit('20 per minute')
def microsoft_callback():
    error = request.args.get('error')
    if error:
        logger.warning(f"Entra fout: {error} — {request.args.get('error_description')}")
        flash('Inloggen via Microsoft mislukt. Probeer opnieuw.', 'error')
        return redirect(url_for('auth.login'))

    state          = request.args.get('state', '')
    expected_state = session.pop('oauth_state', None)
    if not expected_state or state != expected_state:
        logger.warning("OAuth2 state mismatch")
        flash('Ongeldige sessie. Probeer opnieuw in te loggen.', 'error')
        return redirect(url_for('auth.login'))

    code = request.args.get('code')
    if not code:
        flash('Geen autorisatiecode ontvangen van Microsoft.', 'error')
        return redirect(url_for('auth.login'))

    try:
        token_resp = requests.post(ENTRA_TOKEN_URL, data={
            'client_id':     _entra_client_id(),
            'client_secret': _entra_client_secret(),
            'code':          code,
            'redirect_uri':  _callback_url(),
            'grant_type':    'authorization_code',
            'scope':         ENTRA_SCOPES,
        }, timeout=15)
        token_resp.raise_for_status()
        tokens = token_resp.json()
    except requests.RequestException as e:
        logger.error(f"Token uitwisseling mislukt: {e}")
        flash('Kon niet communiceren met Microsoft. Probeer opnieuw.', 'error')
        return redirect(url_for('auth.login'))

    access_token = tokens.get('access_token')
    if not access_token:
        flash('Geen access token ontvangen van Microsoft.', 'error')
        return redirect(url_for('auth.login'))

    try:
        graph_resp = requests.get(
            ENTRA_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            params={'$select': 'id,displayName,givenName,surname,mail,userPrincipalName'},
            timeout=10
        )
        graph_resp.raise_for_status()
        profile = graph_resp.json()
    except requests.RequestException as e:
        logger.error(f"Graph API mislukt: {e}")
        flash('Kon gebruikersgegevens niet ophalen bij Microsoft.', 'error')
        return redirect(url_for('auth.login'))

    email      = (profile.get('mail') or profile.get('userPrincipalName', '')).lower().strip()
    first_name = profile.get('givenName') or ''
    last_name  = profile.get('surname') or ''
    oid        = profile.get('id', '')
    tid        = ''  # tenant wordt opgeslagen via de oid

    if not email or not oid:
        flash('Onvoldoende profielgegevens ontvangen van Microsoft.', 'error')
        return redirect(url_for('auth.login'))

    user, is_new = _get_or_create_user(email, first_name, last_name, oid, tid)

    if not user.is_active:
        flash('Uw account is gedeactiveerd. Contacteer uw ICT-beheerder.', 'error')
        return redirect(url_for('auth.login'))

    if not user.school_id and not user.is_scholengroep_ict and not user.is_superadmin:
        flash(
            'Uw account is aangemaakt maar nog niet gekoppeld aan een school. '
            'Contacteer uw ICT-beheerder.', 'warning'
        )

    login_user(user, remember=True)
    user.last_login = datetime.utcnow()
    audit_log('login.success', 'auth', detail={'provider': 'microsoft', 'new_user': is_new})
    db.session.commit()

    logger.info(f"Entra login: {email} (nieuw: {is_new}, school_id: {user.school_id})")
    return redirect(_safe_next_url(request.args.get('next')))



# ── Google OAuth2 ─────────────────────────────────────────────────────────────
GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_SCOPES       = "openid email profile"

def _google_client_id():
    return current_app.config.get('GOOGLE_CLIENT_ID')

def _google_client_secret():
    return current_app.config.get('GOOGLE_CLIENT_SECRET')

def _google_callback_url():
    base = current_app.config.get('BASE_URL', 'http://localhost').rstrip('/')
    return f"{base}/auth/google/callback"

def _get_or_create_google_user(email, first_name, last_name, google_sub):
    """Zelfde logica als Microsoft — zoek op google sub, dan email, dan maak aan."""
    # 1. Zoek op Google sub (stabielste identifier)
    user = User.query.filter_by(oauth_provider='google', oauth_id=google_sub).first()
    if user:
        user.first_name = first_name or user.first_name
        user.last_name  = last_name  or user.last_name
        user.email      = email
        db.session.commit()
        return user, False

    # 2. Zoek op email — koppel bestaand account aan Google
    user = User.query.filter_by(email=email).first()
    if user:
        user.oauth_provider = 'google'
        user.oauth_id       = google_sub
        user.first_name     = first_name or user.first_name
        user.last_name      = last_name  or user.last_name
        db.session.commit()
        return user, False

    # 3. Nieuw account — koppel aan school via emaildomein
    school = _find_school_for_email(email)
    user = User(
        email=email, first_name=first_name, last_name=last_name,
        role='teacher', school_id=school.id if school else None,
        oauth_provider='google', oauth_id=google_sub,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user, True


@auth_bp.route('/google')
@limiter.limit('20 per minute')
def google_login():
    if not _google_client_id():
        flash('Google login is niet geconfigureerd.', 'error')
        return redirect(url_for('auth.login'))

    # Aparte state-sleutel voor Google om verwarring met Microsoft te vermijden
    state = secrets.token_urlsafe(32)
    session['google_oauth_state'] = state

    params = {
        'client_id':     _google_client_id(),
        'response_type': 'code',
        'redirect_uri':  _google_callback_url(),
        'scope':         GOOGLE_SCOPES,
        'state':         state,
        'access_type':   'online',   # geen refresh token nodig
        'prompt':        'select_account',
        # hd-parameter beperkt NIET — we valideren zelf via emaildomein
        # zodat scholen met meerdere domeinen correct werken
    }
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@auth_bp.route('/google/callback')
@limiter.limit('20 per minute')
def google_callback():
    error = request.args.get('error')
    if error:
        logger.warning(f"Google OAuth fout: {error}")
        flash('Inloggen via Google mislukt. Probeer opnieuw.', 'error')
        return redirect(url_for('auth.login'))

    state          = request.args.get('state', '')
    expected_state = session.pop('google_oauth_state', None)
    if not expected_state or state != expected_state:
        logger.warning("Google OAuth2 state mismatch")
        flash('Ongeldige sessie. Probeer opnieuw in te loggen.', 'error')
        return redirect(url_for('auth.login'))

    code = request.args.get('code')
    if not code:
        flash('Geen autorisatiecode ontvangen van Google.', 'error')
        return redirect(url_for('auth.login'))

    # Wissel code in voor tokens
    try:
        token_resp = requests.post(GOOGLE_TOKEN_URL, data={
            'client_id':     _google_client_id(),
            'client_secret': _google_client_secret(),
            'code':          code,
            'redirect_uri':  _google_callback_url(),
            'grant_type':    'authorization_code',
        }, timeout=15)
        token_resp.raise_for_status()
        tokens = token_resp.json()
    except requests.RequestException as e:
        logger.error(f"Google token uitwisseling mislukt: {e}")
        flash('Kon niet communiceren met Google. Probeer opnieuw.', 'error')
        return redirect(url_for('auth.login'))

    access_token = tokens.get('access_token')
    if not access_token:
        flash('Geen access token ontvangen van Google.', 'error')
        return redirect(url_for('auth.login'))

    # Haal gebruikersprofiel op
    try:
        userinfo_resp = requests.get(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10
        )
        userinfo_resp.raise_for_status()
        profile = userinfo_resp.json()
    except requests.RequestException as e:
        logger.error(f"Google userinfo mislukt: {e}")
        flash('Kon gebruikersgegevens niet ophalen bij Google.', 'error')
        return redirect(url_for('auth.login'))

    email      = profile.get('email', '').lower().strip()
    first_name = profile.get('given_name', '')
    last_name  = profile.get('family_name', '')
    google_sub = profile.get('sub', '')      # stabiele unieke Google user ID

    # Vereiste velden
    if not email or not google_sub:
        flash('Onvoldoende profielgegevens ontvangen van Google.', 'error')
        return redirect(url_for('auth.login'))

    # Google geeft 'email_verified' mee — weiger onverifieerde adressen
    if not profile.get('email_verified', False):
        flash('Uw Google e-mailadres is nog niet geverifieerd.', 'error')
        return redirect(url_for('auth.login'))

    user, is_new = _get_or_create_google_user(email, first_name, last_name, google_sub)

    if not user.is_active:
        flash('Uw account is gedeactiveerd. Contacteer uw ICT-beheerder.', 'error')
        return redirect(url_for('auth.login'))

    if not user.school_id and not user.is_scholengroep_ict and not user.is_superadmin:
        flash(
            'Uw account is aangemaakt maar nog niet gekoppeld aan een school. '
            'Contacteer uw ICT-beheerder.', 'warning'
        )

    login_user(user, remember=True)
    user.last_login = datetime.utcnow()
    audit_log('login.success', 'auth', detail={'provider': 'google', 'new_user': is_new})
    db.session.commit()

    logger.info(f"Google login: {email} (nieuw: {is_new}, school_id: {user.school_id})")
    return redirect(_safe_next_url(request.args.get('next')))

@auth_bp.route('/setup', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
def setup():
    admin = User.query.filter_by(role='superadmin').first()
    if admin and admin.password_hash:
        flash('Setup is al voltooid.', 'info')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        data     = request.get_json() if request.is_json else request.form
        password = data.get('password', '')
        confirm  = data.get('confirm', '')

        if len(password) < 12:
            if request.is_json:
                return jsonify({'error': 'Wachtwoord moet minstens 12 tekens zijn'}), 400
            flash('Wachtwoord moet minstens 12 tekens zijn', 'error')
            return render_template('setup.html')

        if password != confirm:
            if request.is_json:
                return jsonify({'error': 'Wachtwoorden komen niet overeen'}), 400
            flash('Wachtwoorden komen niet overeen', 'error')
            return render_template('setup.html')

        if not admin:
            admin = User(email='admin@leerdoelen.local', role='superadmin',
                         first_name='Super', last_name='Admin')
            db.session.add(admin)

        admin.set_password(password)  # pbkdf2:sha256 — zie models.py voor hash methode
        db.session.commit()

        if request.is_json:
            return jsonify({'message': 'Setup voltooid', 'redirect': url_for('auth.login')})
        flash('Setup voltooid! Je kan nu inloggen.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('setup.html')


@auth_bp.route('/superadmin-login', methods=['POST'])
@limiter.limit('10 per minute; 30 per hour')
def superadmin_login():
    """Fallback login ENKEL voor de superadmin — niet voor gewone gebruikers."""
    if current_user.is_authenticated:
        return redirect(url_for('pages.dashboard'))

    data     = request.get_json() if request.is_json else request.form
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    user = User.query.filter_by(email=email, role='superadmin', is_active=True).first()

    if not user or not user.check_password(password):
        if request.is_json:
            return jsonify({'error': 'Ongeldig e-mailadres of wachtwoord'}), 401
        flash('Ongeldig e-mailadres of wachtwoord', 'error')
        return redirect(url_for('auth.login'))

    login_user(user, remember=False)
    user.last_login = datetime.utcnow()
    audit_log('login.success', 'auth', detail={'provider': 'superadmin'}, user_id=user.id)
    db.session.commit()

    if request.is_json:
        return jsonify({'redirect': url_for('pages.dashboard')})
    return redirect(url_for('pages.dashboard'))
