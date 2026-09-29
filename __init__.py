from flask import Flask, render_template, request, flash, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from config import Config
from flask_wtf import CSRFProtect
from datetime import datetime
import threading

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    schema_check_lock = threading.Lock()
    
    # Ensure database directory exists (already handled in config.py, but double-check)
    import os
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_uri.startswith('sqlite:///'):
        try:
            # Use SQLAlchemy's engine to get the actual database path
            from sqlalchemy import create_engine
            from sqlalchemy.engine import Engine
            temp_engine = create_engine(db_uri)
            # Get the actual database URL from the engine
            db_url = temp_engine.url
            if hasattr(db_url, 'database') and db_url.database:
                db_path = db_url.database
                # Get the directory containing the database file
                db_dir = os.path.dirname(db_path)
                if db_dir and not os.path.exists(db_dir):
                    try:
                        os.makedirs(db_dir, exist_ok=True)
                        app.logger.info(f'Created database directory: {db_dir}')
                    except Exception as e:
                        app.logger.error(f'Failed to create database directory {db_dir}: {e}')
        except Exception as e:
            app.logger.warning(f'Could not parse database URI to ensure directory exists: {e}')
    
    # Add security headers
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # Initialize Flask extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'  # type: ignore
    login_manager.login_message = 'Please log in to access this page.'  # type: ignore
    csrf.init_app(app)

    # Import all models to register them with SQLAlchemy
    from app.models.user import User
    from app.models.asset import Asset
    from app.models.asset_type import AssetType
    from app.models.department import Department
    from app.models.employee import Employee
    from app.models.location import Location
    from app.models.maintenance import Maintenance
    from app.models.manufacturer import Manufacturer
    from app.routes import asset_management, list_forms, administration, labels, reports, new
    from app.routes import auth
    from app.routes.tag_number import bp as tag_number_bp
    from app.routes.search import bp as search_bp

    # Initialize database tables if they don't exist
    with app.app_context():
        try:
            # Check if database file exists, if not create tables
            db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
            if db_uri.startswith('sqlite:///'):
                # Use SQLAlchemy to get the actual database path
                from sqlalchemy import create_engine
                temp_engine = create_engine(db_uri)
                db_url = temp_engine.url
                if hasattr(db_url, 'database') and db_url.database:
                    db_path = db_url.database
                    
                    # If database doesn't exist, create all tables
                    if not os.path.exists(db_path):
                        app.logger.info(f'Database file not found at {db_path}, creating tables...')
                        db.create_all()
                        app.logger.info('Database tables created successfully')
                    else:
                        # Database exists, check if tables exist and schema is up to date
                        try:
                            from app.models.user import User
                            # Try to query to check if tables exist
                            User.query.first()  # This will fail if tables don't exist
                            
                            # Check and migrate database schema for all models
                            app.logger.info('Checking database schema for missing columns...')
                            try:
                                from sqlalchemy import text, inspect
                                from sqlalchemy.engine import reflection
                                
                                # Get database inspector
                                inspector = inspect(db.engine)
                                
                                # Check and add missing columns for User model
                                user_columns = {col['name'] for col in inspector.get_columns('users')}
                                if 'lockout_count' not in user_columns:
                                    app.logger.info('Adding missing lockout_count column to users table for progressive lockout security...')
                                    try:
                                        db.session.execute(text('ALTER TABLE users ADD COLUMN lockout_count INTEGER DEFAULT 0'))
                                        db.session.commit()
                                        app.logger.info('Successfully added lockout_count column to users table')
                                    except Exception as alter_error:
                                        app.logger.error(f'Failed to add lockout_count column: {alter_error}')
                                        db.session.rollback()
                                
                                # Check for other potentially missing columns in other tables
                                # This is a general migration system that can be extended
                                all_tables = inspector.get_table_names()
                                
                                # Check AssetHistory table for ip_address column (security feature)
                                if 'asset_history' in all_tables:
                                    asset_history_columns = {col['name'] for col in inspector.get_columns('asset_history')}
                                    if 'ip_address' not in asset_history_columns:
                                        app.logger.info('Adding missing ip_address column to asset_history table for security auditing...')
                                        try:
                                            db.session.execute(text('ALTER TABLE asset_history ADD COLUMN ip_address VARCHAR(45)'))
                                            db.session.commit()
                                            app.logger.info('Successfully added ip_address column to asset_history table')
                                        except Exception as alter_error:
                                            app.logger.error(f'Failed to add ip_address column: {alter_error}')
                                            db.session.rollback()
                                
                                # Check EmployeeHistory table for ip_address column (security feature)
                                if 'employee_history' in all_tables:
                                    employee_history_columns = {col['name'] for col in inspector.get_columns('employee_history')}
                                    if 'ip_address' not in employee_history_columns:
                                        app.logger.info('Adding missing ip_address column to employee_history table for security auditing...')
                                        try:
                                            db.session.execute(text('ALTER TABLE employee_history ADD COLUMN ip_address VARCHAR(45)'))
                                            db.session.commit()
                                            app.logger.info('Successfully added ip_address column to employee_history table')
                                        except Exception as alter_error:
                                            app.logger.error(f'Failed to add ip_address column: {alter_error}')
                                            db.session.rollback()
                                
                                app.logger.info('Database schema check completed')
                            except Exception as migration_error:
                                app.logger.warning(f'Could not perform database schema migration check: {migration_error}')
                                # Don't fail app startup if migration check fails
                        except Exception as table_error:
                            # Tables don't exist, create them
                            if 'no such table' in str(table_error).lower():
                                app.logger.info('Database file exists but tables are missing, creating tables...')
                                db.create_all()
                                app.logger.info('Database tables created successfully')
                            else:
                                # Some other error, try to create tables anyway
                                app.logger.warning(f'Error checking database: {table_error}, attempting to create tables...')
                                try:
                                    db.create_all()
                                    app.logger.info('Database tables created successfully')
                                except Exception as create_error:
                                    app.logger.error(f'Failed to create tables: {create_error}')
        except Exception as e:
            app.logger.error(f'Error initializing database: {e}', exc_info=True)
            # Don't fail app startup, but log the error
    
    # Register blueprints
    app.register_blueprint(asset_management.bp)
    app.register_blueprint(list_forms.bp)
    app.register_blueprint(administration.bp)
    app.register_blueprint(labels.bp)
    app.register_blueprint(reports.bp)
    app.register_blueprint(new.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(tag_number_bp)
    app.register_blueprint(search_bp)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf)

    # get_client_ip function moved to module level

    @app.before_request
    def ensure_database_ready():
        """Ensure database connectivity/tables once per process (skip static files)."""
        # Skip static files and favicon
        if request.path.startswith('/static/') or request.path == '/favicon.ico':
            return
        if app.config.get('_DB_READY_VERIFIED', False):
            return

        with schema_check_lock:
            if app.config.get('_DB_READY_VERIFIED', False):
                return

            try:
                from sqlalchemy import text
                # Lightweight readiness probe; migrations are handled during app startup.
                db.session.execute(text('SELECT 1'))
                db.session.execute(text('SELECT 1 FROM users LIMIT 1'))
            except Exception as db_check_error:
                error_str = str(db_check_error).lower()
                if 'no such table' in error_str:
                    try:
                        app.logger.warning('Database tables missing, creating them now...')
                        db.create_all()
                        app.logger.info('Database tables created successfully')
                    except Exception as create_error:
                        app.logger.error(f'Failed to create database tables: {create_error}')
            finally:
                app.config['_DB_READY_VERIFIED'] = True
    
    @app.before_request
    def validate_internal_ip():
        """Validate that requests come from allowed internal IP addresses"""
        # Skip validation for static files (CSS, JS, images, etc.)
        if request.path.startswith('/static/') or request.path == '/favicon.ico':
            return
        
        # Only enforce if IP whitelisting is enabled
        if not app.config.get('ENABLE_IP_WHITELIST', True):
            return
        
        try:
            import ipaddress
            from flask import abort
            
            # Get client IP (handles proxy headers securely)
            client_ip_str = get_client_ip()
            
            # Log suspicious proxy header attempts (potential spoofing)
            direct_ip = request.remote_addr
            forwarded_for = request.headers.get('X-Forwarded-For')
            real_ip_header = request.headers.get('X-Real-IP')
            trusted_proxies = app.config.get('TRUSTED_PROXY_IPS', [])
            
            # Detect potential header spoofing attempts
            if (forwarded_for or real_ip_header) and (not trusted_proxies or direct_ip not in trusted_proxies):
                # Someone is trying to use proxy headers but not from a trusted proxy
                app.logger.warning(
                    f'SUSPICIOUS PROXY HEADER ATTEMPT: Direct IP {direct_ip} sent '
                    f'X-Forwarded-For={forwarded_for}, X-Real-IP={real_ip_header}. '
                    f'Headers ignored, using direct IP {direct_ip}'
                )
            
            # Skip validation for localhost/development
            if client_ip_str in ['127.0.0.1', 'localhost', '::1']:
                return
            
            # Keep this at debug level to avoid heavy per-request I/O.
            app.logger.debug(f'IP Whitelist Check: Checking IP {client_ip_str} (direct: {direct_ip})')
            
            # Validate that we got a valid IP string
            if not client_ip_str or not isinstance(client_ip_str, str):
                app.logger.warning(f'Invalid client IP: {client_ip_str}')
                abort(403)
            
            try:
                client_ip = ipaddress.ip_address(client_ip_str)
            except ValueError:
                # Invalid IP address format
                app.logger.warning(f'Invalid IP address format: {client_ip_str}')
                abort(403)
            
            # Check if IP is in any allowed network
            allowed_networks = app.config.get('ALLOWED_INTERNAL_IPS', [])
            
            # If no allowed networks configured, this is a configuration error
            if not allowed_networks:
                app.logger.critical(
                    f'CRITICAL: ALLOWED_INTERNAL_IPS not configured! '
                    f'App is using {type(app.config).__name__} instead of ProductionConfig. '
                    f'IP whitelisting cannot work. Blocking all access for security.'
                )
                abort(403)  # Block access if misconfigured (secure default)
            
            allowed = False
            
            # Debug logging
            app.logger.debug(f'Checking IP {client_ip_str} against allowed networks: {allowed_networks}')
            
            for network_str in allowed_networks:
                try:
                    network = ipaddress.ip_network(network_str, strict=False)
                    # Check if IP is in network (excluding network and broadcast addresses)
                    if client_ip in network:
                        allowed = True
                        app.logger.debug(f'IP {client_ip_str} matched network {network_str}')
                        break
                except ValueError as e:
                    # Invalid network format in config, skip it
                    app.logger.warning(f'Invalid network format in config: {network_str} - {e}')
                    continue
            
            if not allowed:
                # Log detailed information for debugging
                app.logger.warning(
                    f'IP {client_ip_str} (type: {type(client_ip)}) not in allowed networks: {allowed_networks}'
                )
                # Log the blocked attempt
                app.logger.critical(
                    f'EXTERNAL IP BLOCKED: {client_ip_str} tried to access {request.path} '
                    f'(Method: {request.method}, User-Agent: {request.headers.get("User-Agent", "Unknown")[:50]})'
                )
                
                # Try to log to audit log if configured
                try:
                    audit_log_path = app.config.get('AUDIT_LOG_PATH')
                    if audit_log_path:
                        import os
                        os.makedirs(os.path.dirname(audit_log_path), exist_ok=True)
                        with open(audit_log_path, 'a', encoding='utf-8') as f:
                            from datetime import datetime
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            f.write(f'{timestamp} | BLOCKED | IP: {client_ip_str} | Path: {request.path} | Method: {request.method}\n')
                except Exception as e:
                    app.logger.error(f'Failed to write to audit log: {e}')
                
                abort(403)
                
        except Exception as e:
            # Re-raise HTTP exceptions (like Forbidden from abort(403))
            # These should propagate up, not be caught here
            from werkzeug.exceptions import HTTPException
            if isinstance(e, HTTPException):
                raise
            
            # If there's an error in IP validation, block the request for security
            # This ensures that any validation failure results in blocking access
            app.logger.error(f'Error in IP validation: {e}')
            app.logger.critical(f'IP VALIDATION ERROR - BLOCKING REQUEST from {get_client_ip()}')
            abort(403)

    @app.before_request
    def log_request():
        """Log every incoming request with enhanced user tracking"""
        try:
            from server_logger import get_server_logger
            from flask_login import current_user
            from app.utils.security import is_ajax_request
            import uuid
            
            logger = get_server_logger()
            
            client_ip = get_client_ip()
            method = request.method
            path = request.path
            user_agent = request.headers.get('User-Agent', 'Unknown')
            referrer = request.headers.get('Referer', '')
            
            # Enhanced logging for API requests
            if path.startswith('/asset-management/api/') or '/api/' in path:
                is_ajax = is_ajax_request()
                user_authenticated = current_user.is_authenticated
                app.logger.debug(f"[API REQUEST] {method} {path}")
                app.logger.debug(f"[API REQUEST] User authenticated: {user_authenticated}")
                app.logger.debug(f"[API REQUEST] Is AJAX: {is_ajax}")
                if user_authenticated:
                    user_id_str = current_user.username if hasattr(current_user, 'username') else str(current_user.id)
                    app.logger.debug(f"[API REQUEST] User: {user_id_str}")
                else:
                    app.logger.debug("[API REQUEST] WARNING: Unauthenticated API request")
            
            # Get user information
            user_id = None
            session_id = None
            
            if current_user.is_authenticated:
                user_id = current_user.username if hasattr(current_user, 'username') else str(current_user.id)
            
            # Get or create session ID
            from flask import session
            try:
                if 'session_id' not in session:
                    session['session_id'] = str(uuid.uuid4())
                session_id = session['session_id']
            except RuntimeError:
                # Working outside of request context
                session_id = 'no-session'
            
            # Skip logging static files (CSS, JS, images, etc.) - EXCLUDE THEM COMPLETELY
            if not any(path.startswith(prefix) for prefix in ['/static/', '/favicon.ico']):
                # Log page navigation for HTML pages
                if method == 'GET' and not path.startswith('/api/'):
                    logger.log_page_navigation(client_ip, path, user_id, session_id, referrer)
                
                # Log the connection with user info
                logger.log_connection(client_ip, method, path, user_agent, user_id, session_id)
                
                # Log additional details for POST requests
                if method == 'POST':
                    content_type = request.headers.get('Content-Type', 'Unknown')
                    logger.log_post_data(client_ip, content_type)
                    
                    # Log user actions for form submissions
                    action_details = f"Form submission to {path}"
                    if request.form:
                        form_keys = list(request.form.keys())[:3]  # First 3 form fields
                        action_details += f" | Fields: {', '.join(form_keys)}"
                    logger.log_user_action(client_ip, "FORM_SUBMIT", action_details, user_id, session_id)
                
                # Log special attention for admin pages
                if '/administration/' in path:
                    logger.log_admin_access(client_ip, path)
                
                # Log asset management actions (including remove-maintenance POST)
                if any(keyword in path for keyword in ['/new', '/edit', '/checkout', '/checkin', '/transfer', '/move', '/audit', '/remove-maintenance']):
                    logger.log_asset_action(client_ip, path)
                
                # Log specific user actions based on path patterns
                if '/search' in path:
                    search_term = request.args.get('q', '')
                    logger.log_user_action(client_ip, "SEARCH", f"Search term: '{search_term}'", user_id, session_id)
                elif '/export' in path:
                    logger.log_user_action(client_ip, "EXPORT", f"Exporting data from {path}", user_id, session_id)
                elif '/delete' in path or method == 'DELETE':
                    logger.log_user_action(client_ip, "DELETE", f"Deleting resource at {path}", user_id, session_id)
            # Static files are completely skipped - no logging at all
                
        except Exception as e:
            # Fallback to console logging if file logging fails
            client_ip = get_client_ip()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            method = request.method
            path = request.path
            user_agent = request.headers.get('User-Agent', 'Unknown')[:50]
            
            print(f"[{timestamp}] CONNECTION: {client_ip} -> {method} {path} | User-Agent: {user_agent}")
            print(f"[{timestamp}] LOGGING ERROR: {str(e)}")

    @app.route('/')
    def home():
        # Pass assigned_assets as empty list if not available (template checks for it)
        assigned_assets = []
        try:
            from flask_login import current_user
            if current_user.is_authenticated:
                from app.models.asset import Asset
                # Get assets assigned to current user if needed
                # For now, just pass empty list - template handles it gracefully
                assigned_assets = []
        except Exception as e:
            app.logger.warning(f"Error loading assigned assets for dashboard: {e}")
            assigned_assets = []
        
        return render_template('dashboard.html', assigned_assets=assigned_assets)
    
    @app.route('/generate-tag-numbers')
    def generate_tag_numbers_redirect():
        from flask import redirect, url_for
        return redirect(url_for('tag_number.generate_tags_interface'))
    
    # Global error handlers for user-friendly error messages
    @app.errorhandler(500)
    def internal_error(error):
        return render_template('errors/500.html'), 500

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    # Handle database integrity errors gracefully
    @app.errorhandler(Exception)
    def handle_exception(e):
        # Don't handle HTTP exceptions (403, 404, 500, etc.) - let Flask handle those
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            # Re-raise HTTP exceptions to let Flask's default handlers process them
            raise
        
        # Log the actual error for debugging
        app.logger.error(f"UNHANDLED EXCEPTION: {str(e)}")
        app.logger.error(f"ERROR TYPE: {type(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        print(f"ERROR: {str(e)}")
        print(f"ERROR TYPE: {type(e)}")
        traceback.print_exc()
        
        # Check if it's a database connection error or missing column error
        from sqlalchemy.exc import OperationalError, StatementError
        # Check both OperationalError and StatementError (which wraps OperationalError)
        is_db_error = isinstance(e, (OperationalError, StatementError))
        if hasattr(e, 'orig') and isinstance(e.orig, Exception):
            is_db_error = is_db_error or isinstance(e.orig, OperationalError)
        
        if is_db_error:
            error_str = str(e).lower()
            # Also check the original error if it exists
            if hasattr(e, 'orig') and hasattr(e.orig, '__str__'):
                error_str += ' ' + str(e.orig).lower()
            
            # Handle missing column errors - try to add the column automatically
            if 'no such column' in error_str:
                app.logger.warning(f'Missing database column detected: {e}')
                # Try to identify which column is missing and add it
                try:
                    from sqlalchemy import text, inspect
                    inspector = inspect(db.engine)
                    
                    # Extract table and column name from error message
                    # Error format: "no such column: table.column" or "no such column: column" or "users.lockout_count"
                    error_parts = str(e).split(':')
                    column_info = None
                    if len(error_parts) > 1:
                        column_info = error_parts[-1].strip()
                    else:
                        # Try to find column name in the error message directly
                        error_msg = str(e)
                        if 'users.lockout_count' in error_msg:
                            column_info = 'users.lockout_count'
                        elif 'lockout_count' in error_msg:
                            column_info = 'lockout_count'
                        elif 'ip_address' in error_msg:
                            column_info = 'ip_address'
                    
                    if column_info:
                        if '.' in column_info:
                            # Format: "users.lockout_count" or "table.column"
                            parts = column_info.split('.')
                            if len(parts) == 2:
                                table_name = parts[0].strip()
                                column_name = parts[1].strip()
                            else:
                                # Multiple dots, take first as table, rest as column
                                table_name = parts[0].strip()
                                column_name = '.'.join(parts[1:]).strip()
                        else:
                            # No table prefix, try to infer from column name
                            column_name = column_info.strip()
                            table_name = None
                            
                            # Common missing columns we know about
                            if 'lockout_count' in column_name:
                                table_name = 'users'
                            elif 'ip_address' in column_name:
                                # Try to find which history table
                                all_tables = inspector.get_table_names()
                                if 'asset_history' in all_tables:
                                    table_name = 'asset_history'
                                elif 'employee_history' in all_tables:
                                    table_name = 'employee_history'
                        
                        if table_name and column_name:
                            # Check if table exists and column doesn't
                            if table_name in inspector.get_table_names():
                                existing_columns = {col['name'] for col in inspector.get_columns(table_name)}
                                if column_name not in existing_columns:
                                    # Determine column type based on column name
                                    if 'lockout_count' in column_name:
                                        alter_sql = f'ALTER TABLE {table_name} ADD COLUMN {column_name} INTEGER DEFAULT 0'
                                    elif 'ip_address' in column_name:
                                        alter_sql = f'ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(45)'
                                    else:
                                        # Default to TEXT for unknown columns
                                        alter_sql = f'ALTER TABLE {table_name} ADD COLUMN {column_name} TEXT'
                                    
                                    app.logger.info(f'Attempting to add missing column {column_name} to {table_name}...')
                                    db.session.execute(text(alter_sql))
                                    db.session.commit()
                                    app.logger.info(f'Successfully added column {column_name} to {table_name}')
                                    # Try to retry the original request if possible
                                    # For AJAX/JSON requests, return JSON error
                                    if request.is_json or request.headers.get('Content-Type', '').startswith('application/json') or request.path.startswith('/api/'):
                                        from flask import jsonify
                                        return jsonify({
                                            'error': 'Database schema updated. Please refresh and try again.',
                                            'schema_updated': True
                                        }), 500
                                    # For regular requests, redirect
                                    flash('Database schema updated. Please try again.', 'info')
                                    referrer = request.referrer
                                    if referrer and referrer != request.url:
                                        return redirect(referrer)
                                    return redirect(url_for('home'))
                except Exception as migration_error:
                    app.logger.error(f'Failed to auto-migrate missing column: {migration_error}')
            
            # Handle database file errors
            if 'unable to open database file' in error_str or 'no such file' in error_str:
                app.logger.critical('DATABASE FILE ERROR: Database file cannot be opened. Check file permissions and path.')
                flash('Database connection error. Please contact the administrator.', 'danger')
                # Try to initialize database
                try:
                    with app.app_context():
                        db.create_all()
                        app.logger.info('Attempted to create database tables')
                except Exception as db_init_error:
                    app.logger.error(f'Failed to initialize database: {db_init_error}')
                # Redirect to home or login
                referrer = request.referrer
                if referrer and referrer != request.url:
                    return redirect(referrer)
                return redirect(url_for('home'))
        
        # Check if it's a database integrity error
        try:
            if hasattr(e, 'orig') and e.orig and hasattr(e.orig, 'sqlite_errorcode'):
                if e.orig.sqlite_errorcode == 'SQLITE_CONSTRAINT_UNIQUE':  # type: ignore
                    if 'tag_number' in str(e):
                        flash('Tag number already exists. Please choose a different tag number.', 'danger')
                    elif 'serial_number' in str(e):
                        flash('Serial number already exists. Please choose a different serial number.', 'danger')
                    elif 'email' in str(e):
                        flash('Email address already exists. Please choose a different email.', 'danger')
                    elif 'username' in str(e):
                        flash('Username already exists. Please choose a different username.', 'danger')
                    else:
                        flash('A record with this information already exists. Please check your input.', 'danger')
                    # Prevent redirect loop - only redirect if we have a valid referrer and it's not the same page
                    referrer = request.referrer
                    if referrer and referrer != request.url:
                        return redirect(referrer)
                    return redirect(url_for('asset_management.list_assets'))
        except (AttributeError, TypeError):
            # Not a SQLite error, continue with generic error handling
            pass
        
        # For other errors, show a generic message
        # Prevent redirect loop - only redirect if we have a valid referrer and it's not the same page
        referrer = request.referrer
        if referrer and referrer != request.url:
            flash('An unexpected error occurred. Please try again.', 'danger')
            return redirect(referrer)
        else:
            # If no valid referrer, show error page instead of redirecting
            flash('An unexpected error occurred. Please try again.', 'danger')
            return redirect(url_for('home'))

    return app

def get_client_ip():
    """
    Get the client's IP address, handling proxies and load balancers.
    SECURITY: Only trusts proxy headers if request comes from a trusted proxy IP.
    This prevents header spoofing attacks.
    """
    from flask import current_app
    
    # Get the direct connection IP (cannot be spoofed)
    direct_ip = request.remote_addr or '0.0.0.0'
    
    # Get trusted proxy IPs from config
    try:
        trusted_proxies = current_app.config.get('TRUSTED_PROXY_IPS', [])
    except RuntimeError:
        # Outside app context, no trusted proxies
        trusted_proxies = []
    
    # Only trust proxy headers if the direct connection is from a trusted proxy
    # This prevents attackers from spoofing X-Forwarded-For headers
    if trusted_proxies and direct_ip in trusted_proxies:
        # We're behind a trusted proxy, so we can trust proxy headers
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs: "client, proxy1, proxy2"
            # The first IP is the original client
            return forwarded_for.split(',')[0].strip()
        
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip.strip()
    
    # For direct connections or untrusted proxies, use the direct connection IP
    # This is the actual TCP connection IP and cannot be spoofed by headers
    return direct_ip

def log_user_activity(action, details, user_id=None):
    """Helper function to log user activities from route handlers"""
    try:
        from server_logger import get_server_logger
        from flask_login import current_user
        from flask import session
        
        logger = get_server_logger()
        client_ip = get_client_ip()
        
        # Handle session safely
        try:
            session_id = session.get('session_id', 'unknown')
        except RuntimeError:
            session_id = 'no-session'
        
        if not user_id and current_user.is_authenticated:
            user_id = current_user.username if hasattr(current_user, 'username') else str(current_user.id)
        
        logger.log_user_action(client_ip, action, details, user_id, session_id)
    except Exception as e:
        print(f"Error logging user activity: {e}")

# get_client_ip function is already defined above in the create_app function 