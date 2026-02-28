import os
import logging
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from werkzeug.middleware.proxy_fix import ProxyFix

logger = logging.getLogger(__name__)

db            = SQLAlchemy()
login_manager = LoginManager()
migrate       = Migrate()
limiter       = Limiter(key_func=get_remote_address, default_limits=[])


def _make_limiter(redis_url: str) -> Limiter:
    """
    Maak een nieuwe Limiter instantie met de correcte storage_uri.
    In flask-limiter 3.x hoort storage_uri in __init__, NIET in init_app().
    """
    return Limiter(
        key_func=get_remote_address,
        default_limits=[],
        storage_uri=redis_url,
        strategy='moving-window',
    )


def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')

    # ── Config ────────────────────────────────────────────────────────────────
    app.config['SECRET_KEY']                  = os.environ['SECRET_KEY']
    app.config['SQLALCHEMY_DATABASE_URI']     = os.environ['DATABASE_URL']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['BASE_URL']                    = os.environ.get('BASE_URL', 'http://localhost')
    app.config['ORG_NAME']                    = os.environ.get('ORG_NAME', 'GO! Scholengroep')

    # OAuth2
    app.config['MICROSOFT_CLIENT_ID']         = os.environ.get('MICROSOFT_CLIENT_ID')
    app.config['MICROSOFT_CLIENT_SECRET']     = os.environ.get('MICROSOFT_CLIENT_SECRET')
    app.config['MICROSOFT_TENANT_ID']         = os.environ.get('MICROSOFT_TENANT_ID', 'common')

    # Session cookie beveiliging
    is_https = app.config['BASE_URL'].startswith('https')
    app.config['SESSION_COOKIE_SECURE']    = is_https
    app.config['SESSION_COOKIE_HTTPONLY']  = True
    app.config['SESSION_COOKIE_SAMESITE']  = 'Lax'     # Lax ipv Strict: compatibel met OAuth redirect
    app.config['REMEMBER_COOKIE_SECURE']   = is_https
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
    app.config['REMEMBER_COOKIE_DURATION'] = 86400 * 8  # 8 dagen max (was: onbeperkt)

    # ── Rate limit handler ───────────────────────────────────────────────────
    def _rate_limit_handler(e):
        logger.warning(
            f"Rate limit overschreden: {request.method} {request.path} "
            f"van {request.remote_addr}"
        )
        return jsonify({
            'error': 'Te veel verzoeken. Probeer later opnieuw.',
            'retry_after': e.retry_after,
        }), 429

    # ── ProxyFix (Flask zit achter nginx) ────────────────────────────────────
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ── Rate limiter ──────────────────────────────────────────────────────────
    # In flask-limiter 3.x hoort storage_uri in de constructor, niet in init_app().
    # We vervangen de module-level limiter instantie zodat @limiter.limit decorators
    # ook de juiste storage gebruiken.
    global limiter
    redis_url = os.environ.get('REDIS_URL', '')
    if not redis_url:
        logger.warning(
            "REDIS_URL niet ingesteld — rate limiter gebruikt in-memory storage. "
            "Dit werkt NIET correct met meerdere gunicorn workers! "
            "Stel REDIS_URL in voor productie."
        )
        redis_url = 'memory://'
    limiter = _make_limiter(redis_url)
    limiter.init_app(app)

    # ── Security headers via Talisman ─────────────────────────────────────────
    # CSP: strikte whitelist — geen inline scripts, geen externe resources buiten cdnjs
    # CSP: nonce-based voor scripts (Talisman injecteert {{ csp_nonce() }} in templates)
    # unsafe-inline is uitgeschakeld voor scripts — gebruik {{ csp_nonce() }} in <script> tags
    csp = {
        'default-src':  ["'self'"],
        'script-src':   ["'self'", 'cdnjs.cloudflare.com', "'unsafe-inline'"],  # unsafe-inline wordt genegeerd door browsers die nonce ondersteunen
        'style-src':    ["'self'", "'unsafe-inline'"],         # inline styles in templates (aanvaardbaar)
        'img-src':      ["'self'", 'data:'],
        'font-src':     ["'self'"],
        'connect-src':  ["'self'"],
        'form-action':  ["'self'"],                             # voorkomt form hijacking
        'base-uri':     ["'self'"],                             # voorkomt base tag injection
        'frame-ancestors': ["'none'"],                          # clickjacking preventie
        'object-src':   ["'none'"],                             # geen Flash/plugins
    }
    Talisman(
        app,
        # HTTPS redirect hoort in nginx, NIET hier.
        # Talisman zou anders redirecten naar het interne Docker adres (127.0.0.1:5000).
        force_https=False,
        strict_transport_security=is_https,
        strict_transport_security_max_age=31536000,
        strict_transport_security_include_subdomains=True,
        content_security_policy=csp,
        content_security_policy_nonce_in=['script-src'],
    )

    # Extra security headers die niet via Talisman beschikbaar zijn in deze versie
    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault(
            'Permissions-Policy',
            'geolocation=(), microphone=(), camera=()'
        )
        return response

    # ── Extensions ────────────────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view    = 'auth.login'
    login_manager.login_message = 'Gelieve in te loggen.'

    # Import models zodat Flask-Migrate ze kent
    from models import User, School, SchoolYear, Class, TeacherClass, Assessment, AuditLog

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.is_json or request.path.startswith('/api/') or request.path.startswith('/admin/'):
            return jsonify({'error': 'Niet ingelogd'}), 401
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    # ── Globale error handlers ───────────────────────────────────────────────
    from flask_limiter.errors import RateLimitExceeded
    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit(e):
        return _rate_limit_handler(e)

    @app.errorhandler(404)
    def not_found(e):
        if request.is_json or request.path.startswith(('/api/', '/admin/')):
            return jsonify({'error': 'Niet gevonden'}), 404
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    @app.errorhandler(500)
    def server_error(e):
        logger.error(f"500 fout: {e}", exc_info=True)
        if request.is_json or request.path.startswith(('/api/', '/admin/')):
            return jsonify({'error': 'Serverfout — probeer later opnieuw'}), 500
        return redirect(url_for('auth.login'))

    # ── Blueprints ────────────────────────────────────────────────────────────
    from routes.auth  import auth_bp
    from routes.api   import api_bp
    from routes.admin import admin_bp
    from routes.pages import pages_bp

    app.register_blueprint(auth_bp,  url_prefix='/auth')
    app.register_blueprint(api_bp,   url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(pages_bp)

    # ── CLI commando's ────────────────────────────────────────────────────────
    @app.cli.command('cleanup-audit')
    def cleanup_audit():
        """Verwijder auditlog entries ouder dan 1 jaar."""
        from models import AuditLog
        from datetime import datetime, timedelta
        cutoff  = datetime.utcnow() - timedelta(days=365)
        deleted = AuditLog.query.filter(AuditLog.timestamp < cutoff).delete()
        db.session.commit()
        print(f"Verwijderd: {deleted} audit entries ouder dan {cutoff.date()}")

    return app


app = create_app()

if __name__ == '__main__':
    # Nooit debug=True in productie — gebruik gunicorn via entrypoint.sh
    app.run(debug=False, host='127.0.0.1', port=5000)
