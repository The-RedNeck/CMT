from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models.user import User
from app.models.employee import Employee
from app import db
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, HiddenField
from wtforms.validators import DataRequired, Email, Length, EqualTo

bp = Blueprint('administration', __name__, url_prefix='/administration')

class CreateUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    is_super_admin = BooleanField('Super Admin')

class EditUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    is_super_admin = BooleanField('Super Admin')
    password = PasswordField('New Password', validators=[])
    confirm = PasswordField('Confirm New Password', validators=[])
    
    def validate(self, extra_validators=None):
        # First run the standard validation
        if not super().validate(extra_validators):
            return False
            
        # Only validate password if either field has data
        if self.password.data or self.confirm.data:
            # If password is provided, confirm must also be provided
            if self.password.data and not self.confirm.data:
                self.confirm.errors = ['Please confirm your password']
                return False
            
            # If confirm is provided, password must also be provided
            if self.confirm.data and not self.password.data:
                self.password.errors = ['Please enter a password']
                return False
            
            # If both are provided, validate them
            if self.password.data and self.confirm.data:
                if len(self.password.data) < 6:
                    self.password.errors = ['Password must be at least 6 characters long']
                    return False
                if self.password.data != self.confirm.data:
                    self.confirm.errors = ['Passwords do not match']
                    return False
        return True

class DeleteUserForm(FlaskForm):
    submit = HiddenField('submit')

class ToggleUserActiveForm(FlaskForm):
    submit = HiddenField('submit')

class ProfileEditForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    
class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('new_password', message='Passwords must match')])

@bp.route('/users')
@login_required
def list_users():
    if not current_user.is_super_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
    users = User.query.all()
    delete_form = DeleteUserForm()
    toggle_form = ToggleUserActiveForm()
    return render_template('administration/users.html', users=users, delete_form=delete_form, toggle_form=toggle_form)

@bp.route('/users/create', methods=['GET', 'POST'])
@login_required
def create_user():
    if not current_user.is_super_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
    
    form = CreateUserForm()
    if form.validate_on_submit():
        try:
            username = form.username.data
            email = form.email.data
            password = form.password.data
            is_super_admin = form.is_super_admin.data

            if User.query.filter((User.username == username) | (User.email == email)).first():
                flash('Username or email already exists.', 'danger')
                return render_template('administration/create_user.html', form=form)

            user = User(
                username=username,
                email=email,
                is_super_admin=is_super_admin,
                active=True  # Admin-created accounts are automatically active
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('User created successfully.', 'success')
            return redirect(url_for('administration.list_users'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating user: {str(e)}', 'danger')
            return render_template('administration/create_user.html', form=form)

    return render_template('administration/create_user.html', form=form)

@bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    form = DeleteUserForm()
    if not current_user.is_super_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('administration.list_users'))
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully.', 'success')
    return redirect(url_for('administration.list_users'))

@bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
def toggle_user_active(user_id):
    form = ToggleUserActiveForm()
    if not current_user.is_super_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Cannot modify your own account status.', 'danger')
        return redirect(url_for('administration.list_users'))
    user.active = not user.active
    db.session.commit()
    flash(f'User {"activated" if user.active else "deactivated"} successfully.', 'success')
    return redirect(url_for('administration.list_users'))

@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if not current_user.is_super_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
    
    user = User.query.get_or_404(user_id)
    form = EditUserForm(obj=user)
    
    if request.method == 'POST':
        if form.validate_on_submit():
            try:
                # Check if username or email already exists (excluding current user)
                existing_user = User.query.filter(
                    (User.username == form.username.data) | (User.email == form.email.data)
                ).filter(User.id != user_id).first()
                
                if existing_user:
                    flash('Username or email already exists.', 'danger')
                    return render_template('administration/edit_user.html', form=form, user=user)
                
                # Update user information
                user.username = form.username.data
                user.email = form.email.data
                user.is_super_admin = form.is_super_admin.data
                
                # Only update password if provided
                if form.password.data:
                    user.set_password(form.password.data)
                
                db.session.commit()
                flash('User updated successfully.', 'success')
                return redirect(url_for('administration.list_users'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Error updating user: {str(e)}', 'danger')
                return render_template('administration/edit_user.html', form=form, user=user)
        else:
            # Form validation failed
            flash('Please check the form for errors.', 'danger')
            return render_template('administration/edit_user.html', form=form, user=user)
    
    # If form validation fails, show the form with errors
    return render_template('administration/edit_user.html', form=form, user=user)

@bp.route('/employees/<int:employee_id>/delete', methods=['POST'])
@login_required
def delete_employee(employee_id):
    if not current_user.is_super_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
    employee = Employee.query.get_or_404(employee_id)
    if employee.has_assets():
        flash('Cannot delete employee: they have assigned assets.', 'danger')
        return redirect(url_for('list_forms.employees'))
    db.session.delete(employee)
    db.session.commit()
    flash('Employee deleted successfully.', 'success')
    return redirect(url_for('list_forms.employees'))

@bp.route('/connections')
@login_required
def view_connections():
    """View recent connections and IP addresses"""
    try:
        # Check if user is super admin
        if not hasattr(current_user, 'is_super_admin') or not current_user.is_super_admin:
            flash('Access denied.', 'danger')
            return redirect(url_for('home'))
        
        # Get recent asset history with IP addresses
        from app.models.asset import AssetHistory
        from app.models.employee import EmployeeHistory
        from sqlalchemy import desc
        
        # Get recent asset history (last 50 records)
        recent_asset_history = AssetHistory.query.filter(
            AssetHistory.ip_address.isnot(None)
        ).order_by(desc(AssetHistory.changed_at)).limit(50).all()
        
        # Get recent employee history (last 50 records)
        recent_employee_history = EmployeeHistory.query.filter(
            EmployeeHistory.ip_address.isnot(None)
        ).order_by(desc(EmployeeHistory.changed_at)).limit(50).all()
        
        # Combine and sort by timestamp
        all_history = []
        for record in recent_asset_history:
            all_history.append({
                'type': 'Asset',
                'action': record.action,
                'details': f"Asset: {record.tag_number}",
                'user': record.changed_by,
                'ip_address': record.ip_address,
                'timestamp': record.changed_at
            })
        
        for record in recent_employee_history:
            all_history.append({
                'type': 'Employee',
                'action': record.action,
                'details': f"Employee: {record.username}",
                'user': record.changed_by,
                'ip_address': record.ip_address,
                'timestamp': record.changed_at
            })
        
        # Sort by timestamp (most recent first)
        all_history.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Get unique IP addresses
        unique_ips = set()
        for record in all_history:
            if record['ip_address']:
                unique_ips.add(record['ip_address'])
        
        return render_template('administration/connections.html', 
                             history=all_history[:100],  # Show last 100 records
                             unique_ips=sorted(unique_ips))
    
    except Exception as e:
        print(f"ERROR in view_connections: {str(e)}")
        print(f"ERROR TYPE: {type(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Error loading connections: {str(e)}', 'danger')
        return redirect(url_for('administration.list_users'))

@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile management - allows users to edit their own profile and change password"""
    profile_form = ProfileEditForm(obj=current_user)
    password_form = ChangePasswordForm()
    
    # Handle profile update
    if profile_form.validate_on_submit() and 'update_profile' in request.form:
        try:
            # Check if username or email already exists (excluding current user)
            existing_user = User.query.filter(
                (User.username == profile_form.username.data) | (User.email == profile_form.email.data)
            ).filter(User.id != current_user.id).first()
            
            if existing_user:
                flash('Username or email already exists.', 'danger')
                return render_template('administration/profile.html', 
                                     profile_form=profile_form, 
                                     password_form=password_form, 
                                     user=current_user)
            
            # Update user information (but not role)
            current_user.username = profile_form.username.data
            current_user.email = profile_form.email.data
            
            db.session.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('administration.profile'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating profile: {str(e)}', 'danger')
            return render_template('administration/profile.html', 
                                 profile_form=profile_form, 
                                 password_form=password_form, 
                                 user=current_user)
    
    # Handle password change
    if request.method == 'POST' and 'change_password' in request.form:
        if password_form.validate_on_submit():
            try:
                # Verify current password
                if not current_user.check_password(password_form.current_password.data):
                    flash('Current password is incorrect.', 'danger')
                    return render_template('administration/profile.html', 
                                         profile_form=profile_form, 
                                         password_form=password_form, 
                                         user=current_user)
                
                # Update password
                current_user.set_password(password_form.new_password.data)
                db.session.commit()
                flash('Password changed successfully.', 'success')
                return redirect(url_for('administration.profile'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Error changing password: {str(e)}', 'danger')
                return render_template('administration/profile.html', 
                                     profile_form=profile_form, 
                                     password_form=password_form, 
                                     user=current_user)
        else:
            # Form validation failed
            flash('Please check the form for errors.', 'danger')
            return render_template('administration/profile.html', 
                                 profile_form=profile_form, 
                                 password_form=password_form, 
                                 user=current_user)
    
    return render_template('administration/profile.html', 
                         profile_form=profile_form, 
                         password_form=password_form, 
                         user=current_user)

# Add your administration routes here 