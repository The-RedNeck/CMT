from collections import defaultdict
from threading import Lock
import time

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User
from app import db
from app.mfa import (
    consume_recovery_code,
    new_recovery_codes,
    new_secret,
    pending_admin,
    provisioning_uri,
    qr_data_uri,
    store_recovery_codes,
    verify_totp,
)
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired
from datetime import datetime, timedelta, timezone
from app.utils.history import get_client_ip
from flask_wtf.csrf import generate_csrf
from sqlalchemy.exc import OperationalError

_RATE_LOCK = Lock()
_RATE_HITS = defaultdict(list)


def _utcnow():
    """Naive UTC, matching values already stored in the database."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_rate_limited(bucket, limit, window_seconds):
    """In-process limit. Each Gunicorn worker keeps its own counts."""
    now = time.monotonic()
    with _RATE_LOCK:
        recent = [stamp for stamp in _RATE_HITS[bucket] if now - stamp < window_seconds]
        if len(recent) >= limit:
            _RATE_HITS[bucket] = recent
            return True
        recent.append(now)
        _RATE_HITS[bucket] = recent
        return False

bp = Blueprint('auth', __name__, url_prefix='/auth')


def _note_failed_attempt(user, invalid_message='Invalid username or password.'):
    """Count a bad password or authenticator code and lock the account when it adds up."""
    if user.failed_logins is None:
        user.failed_logins = 0
    user.failed_logins += 1
    max_attempts = current_app.config.get('MAX_LOGIN_ATTEMPTS_BEFORE_PROGRESSIVE_LOCKOUT', 20)
    if user.failed_logins < max_attempts:
        db.session.commit()
        return invalid_message

    lockout_count = getattr(user, 'lockout_count', 0) or 0
    lockout_durations = current_app.config.get('LOGIN_ATTEMPT_LOCKOUT_DURATIONS', [
        timedelta(minutes=2), timedelta(minutes=5), timedelta(minutes=15),
        timedelta(hours=1), timedelta(hours=24)
    ])
    duration_index = min(lockout_count, len(lockout_durations) - 1)
    lockout_duration = lockout_durations[duration_index]
    if lockout_duration.total_seconds() < 3600:
        lockout_message = f"{int(lockout_duration.total_seconds() / 60)} minutes"
    elif lockout_duration.total_seconds() < 86400:
        lockout_message = f"{int(lockout_duration.total_seconds() / 3600)} hour(s)"
    else:
        lockout_message = f"{int(lockout_duration.total_seconds() / 86400)} day(s)"
    user.locked_until = _utcnow() + lockout_duration
    try:
        user.lockout_count = lockout_count + 1
    except (AttributeError, Exception):
        pass
    db.session.commit()
    return f'Account locked due to too many failed attempts. Try again in {lockout_message}.'


def _complete_login(user):
    if user.failed_logins:
        user.failed_logins = 0
    if getattr(user, 'lockout_count', 0):
        user.lockout_count = 0
    if user.locked_until:
        user.locked_until = None
    db.session.commit()
    session.permanent = True
    session.pop('mfa_user_id', None)
    session.pop('mfa_setup_secret', None)
    # Calling login_user again for someone who is already signed in
    # makes the current-user proxy recurse on the next template render.
    already_signed_in = (
        current_user.is_authenticated and str(current_user.get_id()) == str(user.id)
    )
    if not already_signed_in:
        login_user(user, remember=True)
    flash('Logged in successfully.', 'success')
    return redirect(url_for('home'))


@bp.before_app_request
def require_admin_mfa():
    """A signed-in super admin cannot use the app until an authenticator is confirmed."""
    if not current_user.is_authenticated:
        return None
    if not current_user.is_super_admin or current_user.mfa_enabled:
        return None
    endpoint = request.endpoint or ''
    if endpoint in ('auth.logout', 'auth.mfa_setup', 'auth.mfa_cancel', 'static'):
        return None
    return redirect(url_for('auth.mfa_setup'))


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])

@bp.route('/login', methods=['GET', 'POST'])
def login():
    client_ip = get_client_ip()
    current_app.logger.info(f"Login attempt from IP: {client_ip}")
    
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = LoginForm()
    if request.method == 'POST' and _client_rate_limited(f'login:{client_ip}', 30, 60):
        current_app.logger.warning(f"Login rate limit hit from IP: {client_ip}")
        flash('Too many login attempts from this address. Try again in a minute.', 'danger')
        return render_template('auth/login.html', form=form)
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        current_app.logger.info(f"Login attempt for username '{username}' from IP: {client_ip}")
        
        # Try to query user, with automatic database migration if needed
        try:
            user = User.query.filter_by(username=username).first()
        except OperationalError as db_error:
            error_str = str(db_error).lower()
            # Check if it's a missing table or column error
            if 'no such table' in error_str:
                # Tables don't exist, create them
                try:
                    db.create_all()
                    current_app.logger.info('Created database tables during login attempt')
                    # Retry the query
                    user = User.query.filter_by(username=username).first()
                except Exception as create_error:
                    current_app.logger.error(f'Failed to create database tables: {create_error}')
                    flash('Database initialization error. Please contact the administrator.', 'danger')
                    return render_template('auth/login.html', form=form)
            elif 'no such column' in error_str or 'lockout_count' in error_str:
                # Missing column - try to add it automatically
                try:
                    from sqlalchemy import text, inspect
                    inspector = inspect(db.engine)
                    
                    # Extract column name from error - handle "users.lockout_count" format
                    column_name = 'lockout_count'
                    if 'users.lockout_count' in error_str or 'lockout_count' in error_str:
                        column_name = 'lockout_count'
                    
                    # Check which column is missing and add it
                    if 'users' in inspector.get_table_names():
                        user_columns = {col['name'] for col in inspector.get_columns('users')}
                        
                        # Add lockout_count if missing
                        if column_name not in user_columns:
                            current_app.logger.info(f'Adding missing {column_name} column to users table during login...')
                            db.session.execute(text('ALTER TABLE users ADD COLUMN lockout_count INTEGER DEFAULT 0'))
                            db.session.commit()
                            current_app.logger.info('Successfully added lockout_count column during login')
                        
                        # Retry the query
                        user = User.query.filter_by(username=username).first()
                    else:
                        # Table doesn't exist, create all tables
                        db.create_all()
                        user = User.query.filter_by(username=username).first()
                except Exception as migration_error:
                    current_app.logger.error(f'Failed to migrate database during login: {migration_error}', exc_info=True)
                    flash('Database schema error. Please contact the administrator.', 'danger')
                    return render_template('auth/login.html', form=form)
            else:
                # Other database error
                current_app.logger.error(f'Database error during login: {db_error}')
                flash('Database error. Please try again or contact the administrator.', 'danger')
                return render_template('auth/login.html', form=form)
        if user:
            if not user.active:
                flash('This account has been deactivated. Please contact an administrator.', 'danger')
                return render_template('auth/login.html', form=form)
            if user.locked_until and user.locked_until > _utcnow():
                flash('Account is locked. Try again later.', 'danger')
                return render_template('auth/login.html', form=form)
            if user.check_password(form.password.data):
                if user.is_super_admin:
                    session['mfa_user_id'] = user.id
                    session.permanent = True
                    if user.mfa_enabled and user.totp_secret:
                        return redirect(url_for('auth.mfa_verify'))
                    return redirect(url_for('auth.mfa_setup'))
                return _complete_login(user)
            else:
                flash(_note_failed_attempt(user), 'danger')
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('auth/login.html', form=form)

def _reject_mfa_code(user):
    message = _note_failed_attempt(user, 'That authentication code is not valid.')
    if user.locked_until and user.locked_until > _utcnow():
        session.pop('mfa_user_id', None)
        session.pop('mfa_setup_secret', None)
        flash(message, 'danger')
        return redirect(url_for('auth.login'))
    flash(message, 'danger')
    return None


@bp.route('/mfa/setup', methods=['GET', 'POST'])
def mfa_setup():
    user = pending_admin()
    if user is None:
        return redirect(url_for('auth.login'))
    if user.mfa_enabled:
        if current_user.is_authenticated:
            return redirect(url_for('home'))
        return redirect(url_for('auth.mfa_verify'))
    if 'mfa_setup_secret' not in session:
        session['mfa_setup_secret'] = new_secret()
    secret = session['mfa_setup_secret']
    if request.method == 'POST':
        if _client_rate_limited(f'mfa:{get_client_ip()}', 30, 60):
            flash('Too many attempts. Try again in a minute.', 'danger')
            return redirect(url_for('auth.mfa_setup'))
        if verify_totp(secret, request.form.get('code', '')):
            codes = new_recovery_codes()
            user.totp_secret = secret
            user.mfa_enabled = True
            store_recovery_codes(user, codes)
            db.session.commit()
            session.pop('mfa_setup_secret', None)
            _complete_login(user)
            return render_template('auth/mfa_recovery.html', codes=codes)
        rejected = _reject_mfa_code(user)
        if rejected is not None:
            return rejected
    uri = provisioning_uri(user, secret)
    return render_template(
        'auth/mfa_setup.html',
        secret=secret,
        qr_uri=qr_data_uri(uri),
    )


@bp.route('/mfa/verify', methods=['GET', 'POST'])
def mfa_verify():
    user = pending_admin()
    if user is None or not user.mfa_enabled:
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        if _client_rate_limited(f'mfa:{get_client_ip()}', 30, 60):
            flash('Too many attempts. Try again in a minute.', 'danger')
            return redirect(url_for('auth.mfa_verify'))
        code = request.form.get('code', '')
        if verify_totp(user.totp_secret, code) or consume_recovery_code(user, code):
            db.session.commit()
            return _complete_login(user)
        rejected = _reject_mfa_code(user)
        if rejected is not None:
            return rejected
    return render_template('auth/mfa_verify.html')


@bp.route('/mfa/cancel')
def mfa_cancel():
    session.pop('mfa_user_id', None)
    session.pop('mfa_setup_secret', None)
    return redirect(url_for('auth.login'))


@bp.route('/mfa/reset', methods=['POST'])
@login_required
def mfa_reset():
    if not current_user.is_super_admin or not current_user.mfa_enabled:
        return redirect(url_for('home'))
    password = request.form.get('password', '')
    code = request.form.get('code', '')
    if not current_user.check_password(password):
        flash('Password or authentication code was not accepted.', 'danger')
        return redirect(url_for('administration.profile'))
    if not (verify_totp(current_user.totp_secret, code) or consume_recovery_code(current_user, code)):
        flash('Password or authentication code was not accepted.', 'danger')
        return redirect(url_for('administration.profile'))
    current_user.totp_secret = None
    current_user.mfa_enabled = False
    current_user.mfa_recovery_hashes = None
    db.session.commit()
    session.pop('mfa_setup_secret', None)
    flash('Set up the authenticator app again before using the rest of CMT.', 'warning')
    return redirect(url_for('auth.mfa_setup'))


@bp.route('/logout')
@login_required
def logout():
    session.pop('mfa_user_id', None)
    session.pop('mfa_setup_secret', None)
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))

@bp.route('/refresh-csrf')
@login_required
def refresh_csrf():
    """Refresh CSRF token for AJAX requests"""
    return jsonify({'csrf_token': generate_csrf()})

