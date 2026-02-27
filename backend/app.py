import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from werkzeug.middleware.proxy_fix import ProxyFix

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()


def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')

    # Config
    app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['BASE_URL'] = os.environ.get('BASE_URL', 'http://localhost')
    app.config['ORG_NAME']  = os.environ.get('ORG_NAME', 'GO! Scholengroep')

    # OAuth2 config (voor later)
    app.config['MICROSOFT_CLIENT_ID'] = os.environ.get('MICROSOFT_CLIENT_ID')
    app.config['MICROSOFT_CLIENT_SECRET'] = os.environ.get('MICROSOFT_CLIENT_SECRET')
    app.config['MICROSOFT_TENANT_ID'] = os.environ.get('MICROSOFT_TENANT_ID', 'common')
    app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')

    # ProxyFix: Flask zit achter nginx als reverse proxy.
    # x_for=1, x_proto=1 zorgt dat Flask de echte client IP en https ziet.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Gelieve in te loggen.'

    # Import models (zodat Flask-Migrate ze kent)
    from models import User, School, SchoolYear, Class, TeacherClass, Assessment

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Blueprints registreren
    from routes.auth import auth_bp
    from routes.api import api_bp
    from routes.admin import admin_bp
    from routes.pages import pages_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(pages_bp)

    # ── Auditlog cleanup (1 jaar bewaren) ─────────────────────────────────────
    @app.cli.command('cleanup-audit')
    def cleanup_audit():
        """Verwijder auditlog entries ouder dan 1 jaar. Voer uit via cron of handmatig."""
        from models import AuditLog
        from datetime import datetime, timedelta
        cutoff  = datetime.utcnow() - timedelta(days=365)
        deleted = AuditLog.query.filter(AuditLog.timestamp < cutoff).delete()
        db.session.commit()
        print(f"Verwijderd: {deleted} audit entries ouder dan {cutoff.date()}")

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
