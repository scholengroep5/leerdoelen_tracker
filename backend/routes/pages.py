from flask import Blueprint, render_template, redirect, url_for, current_app
from flask_login import login_required, current_user

pages_bp = Blueprint('pages', __name__)


def _org_name():
    return current_app.config.get('ORG_NAME', 'GO! Scholengroep')


def _beheer_required(fn):
    """Decorator: alleen superadmin en scholengroep_ict."""
    from functools import wraps
    from flask import abort
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not (current_user.is_superadmin or current_user.role == 'scholengroep_ict'):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


@pages_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('pages.dashboard'))
    return redirect(url_for('auth.login'))


@pages_bp.route('/dashboard')
@login_required
def dashboard():
    org = _org_name()
    if current_user.is_superadmin or current_user.role == 'scholengroep_ict':
        return render_template('scholengroep_ict.html',
                               is_superadmin=current_user.is_superadmin,
                               org_name=org)
    if current_user.role == 'school_ict':
        return render_template('school_ict.html', org_name=org)
    if current_user.role == 'director':
        return render_template('directeur.html', org_name=org)
    return render_template('leerkracht.html', org_name=org)


@pages_bp.route('/doelen-beheer')
@login_required
@_beheer_required
def doelen_beheer():
    """Aparte pagina voor het beheer van leerdoelen bestanden."""
    return render_template('doelen_beheer.html',
                           is_superadmin=current_user.is_superadmin,
                           org_name=_org_name())


@pages_bp.route('/admin')
@login_required
def admin_page():
    return redirect(url_for('pages.dashboard'))


@pages_bp.route('/klassen')
@login_required
def klassen_beheer():
    """Klassenbeheer voor directeurs (en school_ict)."""
    if not current_user.is_director:
        from flask import abort
        abort(403)
    return render_template('directeur_klassen.html', org_name=_org_name())
