import os
from datetime import timedelta

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.pool import StaticPool

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config_overrides=None):
    """Application factory used by the development server and the test suite."""
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    database_path = os.path.join(app.instance_path, 'cmt.db')

    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-change-me'),
        PASSWORD_HASH_METHOD='scrypt:131072:8:1',
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///' + database_path),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        WTF_CSRF_ENABLED=True,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_LOGIN_ATTEMPTS_BEFORE_PROGRESSIVE_LOCKOUT=20,
        LOGIN_ATTEMPT_LOCKOUT_THRESHOLDS=[1, 2, 3, 4, 5],
        LOGIN_ATTEMPT_LOCKOUT_DURATIONS=[
            timedelta(minutes=2),
            timedelta(minutes=5),
            timedelta(minutes=15),
            timedelta(hours=1),
            timedelta(hours=24),
        ],
    )
    if config_overrides:
        app.config.update(config_overrides)
    # The test suite signs in often. Keep production on the strong parameters.
    if app.config.get('TESTING') and (not config_overrides or 'PASSWORD_HASH_METHOD' not in config_overrides):
        app.config['PASSWORD_HASH_METHOD'] = 'scrypt:32768:8:1'

    if app.config.get('TESTING') and app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite:///:memory:':
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'connect_args': {'check_same_thread': False},
            'poolclass': StaticPool,
        }

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.administration import bp as administration_bp
    from app.asset_management import bp as asset_management_bp
    from app.auth import bp as auth_bp
    from app.billing import bp as billing_bp
    from app.billing import subscription_required
    from app.labels import bp as labels_bp
    from app.list_forms import bp as list_forms_bp
    from app.new import bp as new_bp
    from app.reports import bp as reports_bp
    from app.search import bp as search_bp
    from app.tag_number import bp as tag_number_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(asset_management_bp)
    app.register_blueprint(administration_bp)
    app.register_blueprint(list_forms_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(tag_number_bp)
    app.register_blueprint(labels_bp)
    app.register_blueprint(new_bp)
    csrf.exempt(app.view_functions['billing.webhook'])

    @app.before_request
    def require_active_subscription():
        """Trial or an active subscription is required everywhere except sign-in and billing."""
        endpoint = request.endpoint or ''
        if endpoint in ('static', 'health') or endpoint.startswith(('auth.', 'billing.')):
            return None
        if not current_user.is_authenticated or current_user.has_access:
            return None
        flash('Your free trial has ended. Please subscribe to continue.', 'warning')
        return redirect(url_for('billing.pricing'))

    @app.route('/')
    @subscription_required
    def home():
        from app.models.asset import Asset
        from app.models.employee import Employee

        counts = {
            'assets': Asset.query.count(),
            'available': Asset.query.filter_by(status='Available').count(),
            'checked_out': Asset.query.filter_by(status='Checked Out').count(),
            'maintenance': Asset.query.filter_by(status='In Maintenance').count(),
            'employees': Employee.query.count(),
        }
        return render_template('home.html', counts=counts)

    @app.route('/health')
    def health():
        return {'status': 'ok'}

    from app import models as app_models  # noqa: F401  (register models on metadata)

    with app.app_context():
        db.create_all()
        from app.billing import ensure_subscription_columns
        from app.mfa import ensure_mfa_columns
        from app.passwords import ensure_password_hash_storage
        ensure_mfa_columns()
        ensure_subscription_columns()
        ensure_password_hash_storage()
        if not app.config.get('TESTING'):
            from app.seed import seed_demo_data
            seed_demo_data()

    return app
