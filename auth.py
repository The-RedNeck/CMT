from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User
from app import db
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired
from datetime import datetime, timedelta
from app.utils.history import get_client_ip
from flask_wtf.csrf import generate_csrf
from sqlalchemy.exc import OperationalError

bp = Blueprint('auth', __name__, url_prefix='/auth')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])

@bp.route('/login', methods=['GET', 'POST'])
def login():
    client_ip = get_client_ip()
    print(f"Login attempt from IP: {client_ip}")
    
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        print(f"Login attempt for username '{username}' from IP: {client_ip}")
        
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
            if user.locked_until and user.locked_until > datetime.utcnow():
                flash('Account is locked. Try again later.', 'danger')
                return render_template('auth/login.html', form=form)
            if user.check_password(form.password.data):
                # Reset failed login attempts on successful login
                if user.failed_logins and user.failed_logins > 0:
                    user.failed_logins = 0
                # Reset lockout count on successful login
                if hasattr(user, 'lockout_count') and user.lockout_count:
                    user.lockout_count = 0
                # Clear lock if it exists (in case it expired but wasn't cleared)
                if user.locked_until:
                    user.locked_until = None
                db.session.commit()
                # Mark session as permanent to use PERMANENT_SESSION_LIFETIME
                from flask import session
                session.permanent = True
                login_user(user, remember=True)
                flash('Logged in successfully.', 'success')
                return redirect(url_for('home'))
            else:
                # Handle case where failed_logins might be None
                if user.failed_logins is None:
                    user.failed_logins = 0
                user.failed_logins += 1
                
                # Progressive lockout: 2 min → 5 min → 15 min → 1 hour → 24 hours
                max_attempts = current_app.config.get('MAX_LOGIN_ATTEMPTS_BEFORE_PROGRESSIVE_LOCKOUT', 20)
                if user.failed_logins >= max_attempts:
                    # Calculate lockout duration based on number of lockouts
                    try:
                        lockout_count = getattr(user, 'lockout_count', 0) or 0
                    except (AttributeError, Exception):
                        # Column doesn't exist yet, default to 0
                        lockout_count = 0
                    
                    # Get lockout thresholds and durations from config
                    lockout_thresholds = current_app.config.get('LOGIN_ATTEMPT_LOCKOUT_THRESHOLDS', [1, 2, 3, 4, 5])
                    lockout_durations = current_app.config.get('LOGIN_ATTEMPT_LOCKOUT_DURATIONS', [
                        timedelta(minutes=2), timedelta(minutes=5), timedelta(minutes=15), 
                        timedelta(hours=1), timedelta(hours=24)
                    ])
                    
                    # Get the appropriate duration, default to max if lockout_count exceeds defined durations
                    duration_index = min(lockout_count, len(lockout_durations) - 1)
                    lockout_duration = lockout_durations[duration_index]
                    
                    # Format duration message
                    if lockout_duration.total_seconds() < 3600:
                        lockout_message = f"{int(lockout_duration.total_seconds() / 60)} minutes"
                    elif lockout_duration.total_seconds() < 86400:
                        lockout_message = f"{int(lockout_duration.total_seconds() / 3600)} hour(s)"
                    else:
                        lockout_message = f"{int(lockout_duration.total_seconds() / 86400)} day(s)"
                    
                    user.locked_until = datetime.utcnow() + lockout_duration
                    # Only set lockout_count if the column exists
                    try:
                        user.lockout_count = lockout_count + 1
                    except (AttributeError, Exception):
                        # Column doesn't exist, but that's okay - it will be added on next startup
                        pass
                    flash(f'Account locked due to too many failed attempts. Try again in {lockout_message}.', 'danger')
                else:
                    flash('Invalid username or password.', 'danger')
                db.session.commit()
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('auth/login.html', form=form)

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))

@bp.route('/refresh-csrf')
@login_required
def refresh_csrf():
    """Refresh CSRF token for AJAX requests"""
    return jsonify({'csrf_token': generate_csrf()})

