from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models.asset_type import AssetType
from app.models.location import Location
from flask_login import login_required, current_user
from app.models.employee import Employee
from app.models.department import Department
from werkzeug.security import generate_password_hash
from app.models.manufacturer import Manufacturer
from app.utils.export import export_to_excel
from app.utils.history import log_employee_history
from app.models.employee import EmployeeHistory
from app.models.asset import AssetHistory, Asset
from app.utils.security import (
    sanitize_search_term, sanitize_filter_value, validate_date_string,
    safe_ilike_query, safe_equals_query, validate_pagination_params,
    safe_like_query
)
from datetime import datetime
from sqlalchemy import or_

bp = Blueprint('list_forms', __name__, url_prefix='/list-forms')


def _apply_employee_text_search(query, search_term: str):
    """
    Each whitespace-separated token must match employee_id, first name, last name, or email.
    This allows queries like 'Ahmed Mohamed' to match split first/last names.
    """
    if not search_term or not search_term.strip():
        return query
    tokens = [t for t in search_term.split() if t.strip()]
    if not tokens:
        return query
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        pat = f"%{token}%"
        query = query.filter(
            or_(
                Employee.employee_id.ilike(pat),
                Employee.first_name.ilike(pat),
                Employee.last_name.ilike(pat),
                Employee.email.ilike(pat),
            )
        )
    return query

# Add your list_forms routes here 

@bp.route('/new-asset-type', methods=['GET', 'POST'])
@login_required
def new_asset_type():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        if not name:
            flash('Name is required.', 'danger')
            return render_template('list_forms/new_asset_type.html')
        
        # Check for uniqueness
        if AssetType.query.filter(AssetType.name == name).first():
            flash('Asset type name already exists.', 'danger')
            return render_template('list_forms/new_asset_type.html')
        
        try:
            asset_type = AssetType()
            asset_type.name = name
            asset_type.description = description
            db.session.add(asset_type)
            db.session.commit()
            flash('Asset type added successfully.', 'success')
            return redirect(url_for('list_forms.asset_types'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating asset type: {str(e)}', 'danger')
            return render_template('list_forms/new_asset_type.html')
    
    return render_template('list_forms/new_asset_type.html')

@bp.route('/new-location', methods=['GET', 'POST'])
@login_required
def new_location():
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        description = request.form.get('description')
        is_active = bool(request.form.get('is_active'))
        
        if not name or not code:
            flash('Name and code are required.', 'danger')
            return render_template('list_forms/new_location.html')
        
        # Check for uniqueness
        if Location.query.filter((Location.name == name) | (Location.code == code)).first():
            flash('Location name or code already exists.', 'danger')
            return render_template('list_forms/new_location.html')
        
        try:
            location = Location()
            location.name = name
            location.code = code
            location.description = description
            location.is_active = is_active
            db.session.add(location)
            db.session.commit()
            flash('Location added successfully.', 'success')
            return redirect(url_for('list_forms.locations'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating location: {str(e)}', 'danger')
            return render_template('list_forms/new_location.html')
    
    return render_template('list_forms/new_location.html')

@bp.route('/locations')
@login_required
def locations():
    # Pagination parameters
    page = validate_pagination_params(request.args.get('page', 1))
    per_page = 25
    
    # Sanitize search term to prevent SQL injection
    search_term = sanitize_search_term(request.args.get('q', ''))
    query = Location.query
    
    if search_term:
        # Use safe parameterized queries
        query = query.filter(
            (Location.code.ilike(f"%{search_term}%")) |
            (Location.name.ilike(f"%{search_term}%"))
        )
    
    # Get total count for pagination
    total = query.count()
    
    # Apply pagination
    locations = query.order_by(Location.name).offset((page - 1) * per_page).limit(per_page).all()
    
    # Calculate pagination info
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('list_forms/locations.html', 
                         locations=locations,
                         pagination={
                             'page': page,
                             'per_page': per_page,
                             'total': total,
                             'total_pages': total_pages,
                             'has_next': page < total_pages,
                             'has_prev': page > 1
                         })

@bp.route('/locations/export')
@login_required
def export_locations():
    # Get and sanitize search term from query parameters
    search_term = sanitize_search_term(request.args.get('q', ''))
    query = Location.query
    
    if search_term:
        # Use safe parameterized queries
        query = query.filter(
            (Location.code.ilike(f"%{search_term}%")) |
            (Location.name.ilike(f"%{search_term}%"))
        )
    
    locations = query.order_by(Location.name).all()
    data = []
    
    for l in locations:
        try:
            row = {
                'Code': l.code or '',
                'Name': l.name or '',
                'Description': getattr(l, 'description', '') or '',
                'Address': getattr(l, 'address', '') or '',
                'City': getattr(l, 'city', '') or '',
                'State': getattr(l, 'state', '') or '',
                'Country': getattr(l, 'country', '') or '',
                'Postal Code': getattr(l, 'postal_code', '') or '',
                'Floor': getattr(l, 'floor', '') or '',
                'Room': getattr(l, 'room', '') or '',
                'Capacity': getattr(l, 'capacity', '') or '',
                'Status': 'Active' if getattr(l, 'is_active', True) else 'Inactive'
            }
            
            # Add created_at if it exists
            if hasattr(l, 'created_at') and l.created_at:
                row['Created At'] = l.created_at.strftime('%Y-%m-%d')
            else:
                row['Created At'] = ''
                
            data.append(row)
        except Exception as e:
            print(f"Error processing location {l.id}: {e}")
            continue
    
    if not data:
        flash('No data to export', 'warning')
        return redirect(url_for('list_forms.locations'))
    
    response = export_to_excel(data, 'Locations', 'locations')
    if response:
        return response
    
    flash('Export failed. Please try again.', 'danger')
    return redirect(url_for('list_forms.locations'))

@bp.route('/employees')
@login_required
def employees():
    if request.args.get('as_options') == '1':
        employees = Employee.query.order_by(Employee.first_name, Employee.last_name).all()
        return jsonify([[e.id, e.full_name] for e in employees])
    
    # Pagination parameters
    page = validate_pagination_params(request.args.get('page', 1))
    per_page = 25
    
    # Sanitize search term to prevent SQL injection
    search_term = sanitize_search_term(request.args.get('q', ''))
    query = Employee.query
    query = _apply_employee_text_search(query, search_term)
    
    # Get total count for pagination
    total = query.count()
    
    # Apply pagination
    employees = query.order_by(Employee.first_name, Employee.last_name).offset((page - 1) * per_page).limit(per_page).all()
    
    # Calculate pagination info
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('list_forms/employees.html', 
                         employees=employees,
                         pagination={
                             'page': page,
                             'per_page': per_page,
                             'total': total,
                             'total_pages': total_pages,
                             'has_next': page < total_pages,
                             'has_prev': page > 1
                         })

@bp.route('/employees/new', methods=['GET', 'POST'])
@login_required
def new_employee():
    departments = Department.query.all()
    locations = Location.query.all()
    department_options = [(dept.id, dept.name) for dept in departments]
    location_options = [(loc.id, loc.name) for loc in locations]
    if request.method == 'POST':
        # Accept minimal fields for AJAX/modal
        employee_id = request.form.get('employee_id')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        # Try to get username, otherwise auto-generate
        username = request.form.get('username') or (email if email else employee_id)
        # Set defaults for other fields
        title = request.form.get('title', '')
        department_id = request.form.get('department_id') or None
        location_id = request.form.get('location_id') or None
        phone = request.form.get('phone', '')
        mobile = request.form.get('mobile', '')
        hire_date = request.form.get('hire_date')
        termination_date = request.form.get('termination_date')
        is_active = bool(True)
        is_admin = bool(False)
        # Only require minimal fields
        if not all([employee_id, first_name, last_name, email]):
            if request.headers.get('Accept') == 'application/json' or request.is_json or request.form:
                return jsonify({'success': False, 'message': 'Missing required fields.'}), 400
            flash('Please fill in all required fields.', 'danger')
            return render_template('list_forms/new_employee.html', departments=departments, locations=locations, department_options=department_options, location_options=location_options)
        if Employee.query.filter((Employee.username == username) | (Employee.email == email)).first():
            if request.headers.get('Accept') == 'application/json' or request.is_json or request.form:
                return jsonify({'success': False, 'message': 'Username or email already exists.'}), 400
            flash('Username or email already exists.', 'danger')
            return render_template('list_forms/new_employee.html', departments=departments, locations=locations, department_options=department_options, location_options=location_options)
        employee = Employee()
        employee.employee_id = employee_id
        employee.username = username
        employee.email = email
        employee.first_name = first_name
        employee.last_name = last_name
        employee.title = title
        employee.department_id = department_id
        employee.location_id = location_id
        employee.phone = phone
        employee.mobile = mobile
        setattr(employee, 'is_active', is_active)
        setattr(employee, 'is_admin', is_admin)
        if hire_date:
            try:
                employee.hire_date = datetime.strptime(hire_date, '%Y-%m-%d').date()
            except ValueError:
                # If date parsing fails, set to None
                employee.hire_date = None
        if termination_date:
            try:
                employee.termination_date = datetime.strptime(termination_date, '%Y-%m-%d').date()
            except ValueError:
                # If date parsing fails, set to None
                employee.termination_date = None
        try:
            db.session.add(employee)
            db.session.commit()
            log_employee_history(employee, 'created', changed_by=current_user.username)
            # Commit the history if it was added
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            error_msg = f'Failed to add employee: {str(e)}'
            print(f"Employee creation error: {error_msg}")
            if request.headers.get('Accept') == 'application/json' or request.is_json or request.form:
                return jsonify({'success': False, 'message': error_msg}), 500
            flash(error_msg, 'danger')
            return render_template('list_forms/new_employee.html', departments=departments, locations=locations, department_options=department_options, location_options=location_options)
        # If AJAX/modal, return JSON
        if request.headers.get('Accept') == 'application/json' or request.is_json or request.form:
            return jsonify({'success': True, 'id': employee.id, 'name': employee.full_name})
        flash('Employee added successfully.', 'success')
        return redirect(url_for('list_forms.employees'))
    return render_template('list_forms/new_employee.html', departments=departments, locations=locations, employee=None, department_options=department_options, location_options=location_options)

@bp.route('/employees/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_employee(id):
    employee = Employee.query.get_or_404(id)
    departments = Department.query.order_by(Department.name.asc()).all()
    locations = Location.query.order_by(Location.name.asc()).all()
    department_options = [(dept.id, dept.name) for dept in departments]
    location_options = [(loc.id, loc.name) for loc in locations]
    if request.method == 'POST':
        try:
            employee.employee_id = request.form.get('employee_id')
            employee.username = request.form.get('username')
            employee.email = request.form.get('email')
            employee.first_name = request.form.get('first_name')
            employee.last_name = request.form.get('last_name')
            employee.title = request.form.get('title')
            employee.department_id = request.form.get('department_id') or None
            employee.location_id = request.form.get('location_id') or None
            employee.phone = request.form.get('phone')
            employee.mobile = request.form.get('mobile')
            employee.is_active = bool(request.form.get('is_active'))
            employee.is_admin = bool(request.form.get('is_admin'))
            hire_date = request.form.get('hire_date')
            termination_date = request.form.get('termination_date')
            if hire_date:
                try:
                    employee.hire_date = datetime.strptime(hire_date, '%Y-%m-%d').date()
                except ValueError:
                    # If date parsing fails, set to None
                    employee.hire_date = None
            else:
                employee.hire_date = None
            if termination_date:
                try:
                    employee.termination_date = datetime.strptime(termination_date, '%Y-%m-%d').date()
                except ValueError:
                    # If date parsing fails, set to None
                    employee.termination_date = None
            else:
                employee.termination_date = None
            db.session.commit()
            log_employee_history(employee, 'updated', changed_by=current_user.username)
            
            # Check if this is an AJAX request
            if request.headers.get('Accept') == 'application/json' or request.is_json:
                return jsonify({'success': True, 'message': 'Employee updated successfully.'})
            
            flash('Employee updated successfully.', 'success')
            return redirect(url_for('list_forms.employees'))
        except Exception as e:
            db.session.rollback()
            error_message = f'Error updating employee: {str(e)}'
            
            # Check if this is an AJAX request
            if request.headers.get('Accept') == 'application/json' or request.is_json:
                return jsonify({'success': False, 'message': error_message}), 400
            
            flash(error_message, 'danger')
            return render_template('list_forms/new_employee.html', departments=departments, locations=locations, employee=employee, department_options=department_options, location_options=location_options)
    
    return render_template('list_forms/new_employee.html', departments=departments, locations=locations, employee=employee, department_options=department_options, location_options=location_options)

@bp.route('/employees/export')
@login_required
def export_employees():
    employees = Employee.query.all()
    data = [{
        'Employee ID': e.employee_id,
        'Name': e.full_name,
        'Email': e.email,
        'Department': e.department.name if e.department else '',
        'Title': e.title,
        'Phone': e.phone,
        'Status': 'Active' if e.is_active else 'Inactive'
    } for e in employees]
    response = export_to_excel(data, 'Employees', 'employees')
    if response:
        return response
    return redirect(url_for('list_forms.employees'))

@bp.route('/employees/<int:employee_id>/delete', methods=['POST'])
@login_required
def delete_employee(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    # Prevent deletion if employee has assigned assets
    if hasattr(employee, 'checked_out_assets') and employee.checked_out_assets:
        flash('Cannot delete employee: they have assigned assets.', 'danger')
        return redirect(url_for('list_forms.employees'))
    log_employee_history(employee, 'deleted', changed_by=current_user.username)
    db.session.delete(employee)
    db.session.commit()
    flash('Employee deleted successfully.', 'success')
    return redirect(url_for('list_forms.employees'))

@bp.route('/departments')
@login_required
def departments():
    # Pagination parameters
    page = validate_pagination_params(request.args.get('page', 1))
    per_page = 25
    
    # Sanitize search term to prevent SQL injection
    search_term = sanitize_search_term(request.args.get('q', ''))
    query = Department.query
    
    if search_term:
        # Use safe parameterized queries
        query = query.filter(
            (Department.code.ilike(f"%{search_term}%")) |
            (Department.name.ilike(f"%{search_term}%"))
        )
    
    # Get total count for pagination
    total = query.count()
    
    # Apply pagination
    departments = query.order_by(Department.name).offset((page - 1) * per_page).limit(per_page).all()
    
    # Calculate pagination info
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('list_forms/departments.html', 
                         departments=departments,
                         pagination={
                             'page': page,
                             'per_page': per_page,
                             'total': total,
                             'total_pages': total_pages,
                             'has_next': page < total_pages,
                             'has_prev': page > 1
                         })

@bp.route('/departments/export')
@login_required
def export_departments():
    # Get and sanitize search term from query parameters
    search_term = sanitize_search_term(request.args.get('q', ''))
    query = Department.query
    
    if search_term:
        # Use safe parameterized queries
        query = query.filter(
            (Department.code.ilike(f"%{search_term}%")) |
            (Department.name.ilike(f"%{search_term}%"))
        )
    
    departments = query.order_by(Department.name).all()
    data = [{
        'Code': d.code,
        'Name': d.name,
        'Description': d.description or '',
        'Manager': d.manager.full_name if d.manager else '',
        'Parent Department': d.parent_department.name if d.parent_department else '',
        'Cost Center': d.cost_center or '',
        'Budget': f"${d.budget:,.2f}" if d.budget else '',
        'Created At': d.created_at.strftime('%Y-%m-%d') if d.created_at else ''
    } for d in departments]
    response = export_to_excel(data, 'Departments', 'departments')
    if response:
        return response
    return redirect(url_for('list_forms.departments'))

@bp.route('/departments/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_department(id):
    department = Department.query.get_or_404(id)
    if request.method == 'POST':
        department.name = request.form.get('name')
        department.code = request.form.get('code')
        department.description = request.form.get('description')
        department.cost_center = request.form.get('cost_center')
        budget = request.form.get('budget')
        if budget:
            try:
                department.budget = float(budget)
            except ValueError:
                flash('Budget must be a valid number.', 'danger')
                return render_template('list_forms/edit_department.html', department=department)
        else:
            department.budget = None
        
        manager_id = request.form.get('manager_id')
        department.manager_id = manager_id if manager_id else None
        
        parent_id = request.form.get('parent_department_id')
        department.parent_department_id = parent_id if parent_id else None
        
        db.session.commit()
        flash('Department updated successfully.', 'success')
        return redirect(url_for('list_forms.departments'))
    
    # Get all departments for parent selection (excluding self)
    all_departments = Department.query.filter(Department.id != id).all()
    # Get all employees for manager selection
    all_employees = Employee.query.filter_by(is_active=True).all()
    
    return render_template('list_forms/edit_department.html', 
                         department=department, 
                         all_departments=all_departments,
                         all_employees=all_employees)





@bp.route('/asset-types')
@login_required
def asset_types():
    # Pagination parameters
    page = validate_pagination_params(request.args.get('page', 1))
    per_page = 25
    
    # Sanitize search term to prevent SQL injection
    search_term = sanitize_search_term(request.args.get('q', ''))
    query = AssetType.query
    
    if search_term:
        # Use safe parameterized queries
        query = query.filter(
            (AssetType.name.ilike(f"%{search_term}%")) |
            (AssetType.description.ilike(f"%{search_term}%"))
        )
    
    # Get total count for pagination
    total = query.count()
    
    # Apply pagination
    asset_types = query.order_by(AssetType.name).offset((page - 1) * per_page).limit(per_page).all()
    
    # Calculate pagination info
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('list_forms/asset_types.html', 
                         asset_types=asset_types,
                         pagination={
                             'page': page,
                             'per_page': per_page,
                             'total': total,
                             'total_pages': total_pages,
                             'has_next': page < total_pages,
                             'has_prev': page > 1
                         })

@bp.route('/asset-types/export')
@login_required
def export_asset_types():
    # Get and sanitize search term from query parameters
    search_term = sanitize_search_term(request.args.get('q', ''))
    query = AssetType.query
    
    if search_term:
        # Use safe parameterized queries
        query = query.filter(
            (AssetType.name.ilike(f"%{search_term}%")) |
            (AssetType.description.ilike(f"%{search_term}%"))
        )
    
    asset_types = query.order_by(AssetType.name).all()
    data = []
    
    for at in asset_types:
        try:
            row = {
                'Name': at.name or '',
                'Description': getattr(at, 'description', '') or '',
                'Category': getattr(at, 'category', '') or '',
                'Expected Lifespan (Years)': getattr(at, 'expected_lifespan_years', '') or ''
            }
            
            # Add created_at if it exists
            if hasattr(at, 'created_at') and at.created_at:
                row['Created At'] = at.created_at.strftime('%Y-%m-%d')
            else:
                row['Created At'] = ''
                
            data.append(row)
        except Exception as e:
            print(f"Error processing asset type {at.id}: {e}")
            continue
    
    if not data:
        flash('No data to export', 'warning')
        return redirect(url_for('list_forms.asset_types'))
    
    response = export_to_excel(data, 'Asset Types', 'asset_types')
    if response:
        return response
    
    flash('Export failed. Please try again.', 'danger')
    return redirect(url_for('list_forms.asset_types'))

@bp.route('/asset-types/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_asset_type(id):
    asset_type = AssetType.query.get_or_404(id)
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        if not name:
            flash('Name is required.', 'danger')
            return render_template('list_forms/edit_asset_type.html', asset_type=asset_type)
        
        # Check for uniqueness (excluding current asset type)
        existing = AssetType.query.filter(
            AssetType.name == name,
            AssetType.id != id
        ).first()
        if existing:
            flash('Asset type name already exists.', 'danger')
            return render_template('list_forms/edit_asset_type.html', asset_type=asset_type)
        
        try:
            asset_type.name = name
            asset_type.description = description
            db.session.commit()
            flash('Asset type updated successfully.', 'success')
            return redirect(url_for('list_forms.asset_types'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating asset type: {str(e)}', 'danger')
            return render_template('list_forms/edit_asset_type.html', asset_type=asset_type)
    
    return render_template('list_forms/edit_asset_type.html', asset_type=asset_type)





@bp.route('/manufacturers')
@login_required
def manufacturers():
    # Sanitize search term to prevent SQL injection
    search_term = sanitize_search_term(request.args.get('q', ''))
    query = Manufacturer.query.filter_by(is_active=True)  # Security: Only show active manufacturers
    if search_term:
        # Use safe parameterized queries
        query = query.filter(
            Manufacturer.name.ilike(f"%{search_term}%")
        )
    manufacturers = query.all()
    return render_template('list_forms/manufacturers.html', manufacturers=manufacturers)

@bp.route('/manufacturers/new', methods=['GET', 'POST'])
@login_required
def new_manufacturer():
    """Create a new manufacturer with security validation"""
    if request.method == 'POST':
        try:
            # Security: Validate required fields
            name = request.form.get('name', '').strip()
            
            if not name:
                if request.headers.get('Accept') == 'application/json':
                    return jsonify({'success': False, 'message': 'Manufacturer name is required.'}), 400
                flash('Manufacturer name is required.', 'danger')
                return render_template('list_forms/new_manufacturer.html')
            
            # Security: Check for duplicate names
            existing_manufacturer = Manufacturer.query.filter_by(name=name).first()
            if existing_manufacturer:
                if request.headers.get('Accept') == 'application/json':
                    return jsonify({'success': False, 'message': 'A manufacturer with this name already exists.'}), 400
                flash('A manufacturer with this name already exists.', 'danger')
                return render_template('list_forms/new_manufacturer.html')
            
            # Create manufacturer with sanitized data
            manufacturer = Manufacturer()
            manufacturer.name = name
            manufacturer.description = request.form.get('description', '').strip()
            manufacturer.is_active = 'is_active' in request.form
            
            db.session.add(manufacturer)
            db.session.commit()
            
            if request.headers.get('Accept') == 'application/json':
                return jsonify({'success': True, 'message': 'Manufacturer created successfully.', 'id': manufacturer.id, 'name': manufacturer.name})
            
            flash('Manufacturer created successfully.', 'success')
            return redirect(url_for('list_forms.manufacturers'))
            
        except Exception as e:
            db.session.rollback()
            if request.headers.get('Accept') == 'application/json':
                return jsonify({'success': False, 'message': f'Error creating manufacturer: {str(e)}'}), 500
            flash(f'Error creating manufacturer: {str(e)}', 'danger')
            return render_template('list_forms/new_manufacturer.html')
    
    return render_template('list_forms/new_manufacturer.html')

@bp.route('/manufacturers/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_manufacturer(id):
    """Edit an existing manufacturer with security validation"""
    manufacturer = Manufacturer.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Security: Validate required fields
            name = request.form.get('name', '').strip()
            
            if not name:
                flash('Manufacturer name is required.', 'danger')
                return render_template('list_forms/new_manufacturer.html', manufacturer=manufacturer)
            
            # Security: Check for duplicate names (excluding current record)
            existing_manufacturer = Manufacturer.query.filter(
                Manufacturer.name == name,
                Manufacturer.id != id
            ).first()
            if existing_manufacturer:
                flash('A manufacturer with this name already exists.', 'danger')
                return render_template('list_forms/new_manufacturer.html', manufacturer=manufacturer)
            
            # Update manufacturer with sanitized data
            manufacturer.name = name
            manufacturer.description = request.form.get('description', '').strip()
            manufacturer.is_active = 'is_active' in request.form
            
            db.session.commit()
            flash('Manufacturer updated successfully.', 'success')
            return redirect(url_for('list_forms.manufacturers'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating manufacturer: {str(e)}', 'danger')
            return render_template('list_forms/new_manufacturer.html', manufacturer=manufacturer)
    
    return render_template('list_forms/new_manufacturer.html', manufacturer=manufacturer)

@bp.route('/manufacturers/<int:id>/delete', methods=['POST'])
@login_required
def delete_manufacturer(id):
    """Delete a manufacturer with security checks"""
    try:
        manufacturer = Manufacturer.query.get_or_404(id)
        
        # Security: Check if manufacturer is in use by any assets
        assets_using_manufacturer = db.session.query(Asset).filter_by(manufacturer_id=id).count()
        if assets_using_manufacturer > 0:
            flash(f'Cannot delete manufacturer. It is currently used by {assets_using_manufacturer} asset(s).', 'danger')
            return redirect(url_for('list_forms.manufacturers'))
        
        # Security: Soft delete by setting is_active to False instead of hard delete
        manufacturer.is_active = False
        db.session.commit()
        flash('Manufacturer deactivated successfully.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting manufacturer: {str(e)}', 'danger')
    
    return redirect(url_for('list_forms.manufacturers'))



@bp.route('/api/employees/<int:employee_id>/history')
@login_required
def employee_history_api(employee_id):
    try:
        # Get employee record changes
        emp_history = EmployeeHistory.query.filter_by(employee_id=employee_id).all()
        
        # Get ALL asset actions involving this employee (both checkouts and check-ins)
        # First, find all assets this employee has ever checked out
        employee_assets = db.session.query(AssetHistory.asset_id).filter(
            AssetHistory.current_employee_id == employee_id
        ).distinct().subquery()
        
        # Then get all history records for those assets (including check-ins)
        # Also include any check-in actions where this employee was the one who had the asset
        asset_history = AssetHistory.query.filter(
            (AssetHistory.asset_id.in_(employee_assets)) |
            # Include check-ins where this employee was the previous holder
            ((AssetHistory.action == 'checked_in') & 
             (AssetHistory.asset_id.in_(
                 db.session.query(AssetHistory.asset_id).filter(
                     AssetHistory.current_employee_id == employee_id,
                     AssetHistory.action == 'checked_out'
                 ).distinct()
             )))
        ).order_by(AssetHistory.changed_at.desc()).all()
        
        
        # Helper functions
        def get_department_name(dept_id):
            if not dept_id:
                return None
            from app.models.department import Department
            dept = Department.query.get(dept_id)
            return dept.name if dept else None
            
        def get_manager_name(manager_id):
            if not manager_id:
                return None
            mgr = Employee.query.get(manager_id)
            return mgr.full_name if mgr else None
            
        def get_asset_name(asset_id):
            if not asset_id:
                return None
            asset = Asset.query.get(asset_id)
            return asset.name if asset else None
        
        # Format both histories
        formatted = []
        
        # Process employee history
        for h in emp_history:
            try:
                record = {
                    'action': h.action,
                    'changed_by': h.changed_by,
                    'changed_at': h.changed_at.isoformat(),
                    'type': 'employee',
                    'data': {
                        'username': h.username,
                        'email': h.email,
                        'first_name': h.first_name,
                        'last_name': h.last_name,
                        'title': h.title,
                        'department_id': h.department_id,
                        'department_name': get_department_name(h.department_id),
                        'manager_id': h.manager_id,
                        'manager_name': get_manager_name(h.manager_id),
                        'phone': h.phone,
                        'mobile': h.mobile,
                        'is_active': h.is_active,
                        'is_admin': h.is_admin,
                        'hire_date': h.hire_date.isoformat() if h.hire_date else None,
                        'termination_date': h.termination_date.isoformat() if h.termination_date else None,
                        'created_at': h.created_at.isoformat() if h.created_at else None,
                        'updated_at': h.updated_at.isoformat() if h.updated_at else None,
                        'last_login': h.last_login.isoformat() if h.last_login else None
                    }
                }
                formatted.append(record)
            except Exception as e:
                print(f"Error processing employee history record {h.id}: {e}")
                continue
        
        # Process asset history
        for h in asset_history:
            try:
                # Determine if this action directly involved the employee
                is_direct_involvement = (h.current_employee_id == employee_id)
                
                record = {
                    'action': h.action,
                    'changed_by': h.changed_by,
                    'changed_at': h.changed_at.isoformat(),
                    'type': 'asset',
                    'data': {
                        'asset_id': h.asset_id,
                        'asset_name': get_asset_name(h.asset_id),
                        'status': h.status,
                        'tag_number': h.tag_number,
                        'name': h.name,
                        'description': h.description,
                        'serial_number': h.serial_number,
                        'model_number': h.model_number,
                        'location_id': h.location_id,
                        'location_name': None,  # Can be filled if needed
                        'checked_action': h.action,
                        'is_direct_involvement': is_direct_involvement,  # True for checkouts, False for check-ins
                        'action_context': f"{'Directly involved' if is_direct_involvement else 'Asset returned'}"
                    }
                }
                formatted.append(record)
            except Exception as e:
                print(f"Error processing asset history record {h.id}: {e}")
                continue
        
        # Sort all by changed_at descending
        formatted.sort(key=lambda x: x['changed_at'], reverse=True)
        return jsonify(formatted)
        
    except Exception as e:
        print(f"Error in employee history API: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to load employee history'}), 500

@bp.route('/employees/<int:employee_id>/export-history')
@login_required
def export_employee_history(employee_id):
    from app.utils.export import export_to_excel
    emp_history = EmployeeHistory.query.filter_by(employee_id=employee_id).all()
    
    # Get ALL asset actions involving this employee (both checkouts and check-ins)
    # First, find all assets this employee has ever checked out
    employee_assets = db.session.query(AssetHistory.asset_id).filter(
        AssetHistory.current_employee_id == employee_id
    ).distinct().subquery()
    
    # Then get all history records for those assets (including check-ins)
    # Also include any check-in actions where this employee was the one who had the asset
    asset_history = AssetHistory.query.filter(
        (AssetHistory.asset_id.in_(employee_assets)) |
        # Include check-ins where this employee was the previous holder
        ((AssetHistory.action == 'checked_in') & 
         (AssetHistory.asset_id.in_(
             db.session.query(AssetHistory.asset_id).filter(
                 AssetHistory.current_employee_id == employee_id,
                 AssetHistory.action == 'checked_out'
             ).distinct()
         )))
    ).order_by(AssetHistory.changed_at.desc()).all()
    def get_department_name(dept_id):
        if not dept_id:
            return None
        from app.models.department import Department
        dept = Department.query.get(dept_id)
        return dept.name if dept else None
    def get_asset_name(asset_id):
        if not asset_id:
            return None
        asset = Asset.query.get(asset_id)
        return asset.name if asset else None
    data = []
    for h in emp_history:
        data.append({
            'Date': h.changed_at.strftime('%Y-%m-%d %H:%M:%S') if h.changed_at else '',
            'Action': h.action,
            'User': h.changed_by,
            'Type': 'employee',
            'First Name': h.first_name,
            'Last Name': h.last_name,
            'Email': h.email,
            'Title': h.title,
            'Department': get_department_name(h.department_id),
            'Phone': h.phone,
            'Mobile': h.mobile,
            'Is Active': h.is_active,
            'Is Admin': h.is_admin,
        })
    for h in asset_history:
        # Determine if this action directly involved the employee
        is_direct_involvement = (h.current_employee_id == employee_id)
        
        data.append({
            'Date': h.changed_at.strftime('%Y-%m-%d %H:%M:%S') if h.changed_at else '',
            'Action': h.action,
            'User': h.changed_by,
            'Type': 'asset',
            'Asset Name': get_asset_name(h.asset_id),
            'Status': h.status,
            'Tag Number': h.tag_number,
            'Serial Number': h.serial_number,
            'Model Number': h.model_number,
            'Involvement': 'Direct' if is_direct_involvement else 'Asset Returned',
            'Context': f"{'Employee directly involved' if is_direct_involvement else 'Asset was returned by someone else'}"
        })
    data.sort(key=lambda x: x['Date'], reverse=True)
    response = export_to_excel(data, sheet_name='Employee History', base_filename=f'employee_{employee_id}_history')
    if response:
        return response
    else:
        flash('Export failed. No data to export.', 'danger')
        return redirect(url_for('list_forms.employees'))


@bp.route('/departments/new', methods=['GET', 'POST'])
@login_required
def new_department():
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        description = request.form.get('description')
        cost_center = request.form.get('cost_center')
        budget = request.form.get('budget')
        manager_id = request.form.get('manager_id')
        parent_department_id = request.form.get('parent_department_id')
        
        if not name or not code:
            flash('Name and code are required.', 'danger')
            # Get all departments for parent selection
            all_departments = Department.query.order_by(Department.name.asc()).all()
            # Get all employees for manager selection
            all_employees = Employee.query.filter_by(is_active=True).all()
            return render_template('list_forms/new_department.html', 
                                 departments=all_departments,
                                 employees=all_employees)
        
        # Check for uniqueness
        if Department.query.filter((Department.name == name) | (Department.code == code)).first():
            flash('Department name or code already exists.', 'danger')
            # Get all departments for parent selection
            all_departments = Department.query.order_by(Department.name.asc()).all()
            # Get all employees for manager selection
            all_employees = Employee.query.filter_by(is_active=True).all()
            return render_template('list_forms/new_department.html', 
                                 departments=all_departments,
                                 employees=all_employees)
        
        try:
            department = Department()
            department.name = name
            department.code = code
            department.description = description
            department.cost_center = cost_center
            department.budget = float(budget) if budget else None
            department.manager_id = manager_id if manager_id else None
            department.parent_department_id = parent_department_id if parent_department_id else None
            db.session.add(department)
            db.session.commit()
            flash('Department added successfully.', 'success')
            return redirect(url_for('list_forms.departments'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating department: {str(e)}', 'danger')
            # Get all departments for parent selection
            all_departments = Department.query.order_by(Department.name.asc()).all()
            # Get all employees for manager selection
            all_employees = Employee.query.filter_by(is_active=True).all()
            return render_template('list_forms/new_department.html', 
                                 departments=all_departments,
                                 employees=all_employees)
    
    # Get all departments for parent selection
    all_departments = Department.query.order_by(Department.name.asc()).all()
    # Get all employees for manager selection
    all_employees = Employee.query.filter_by(is_active=True).all()
    
    return render_template('list_forms/new_department.html', 
                         departments=all_departments,
                         employees=all_employees)

@bp.route('/departments/new-ajax', methods=['POST'])
@login_required
def new_department_ajax():
    name = request.form.get('name')
    code = request.form.get('code')
    if not name or not code:
        return jsonify({'success': False, 'message': 'Name and code are required.'}), 400
    # Check for uniqueness
    if Department.query.filter((Department.name == name) | (Department.code == code)).first():
        return jsonify({'success': False, 'message': 'Department name or code already exists.'}), 400
    department = Department()
    department.name = name
    department.code = code
    db.session.add(department)
    db.session.commit()
    return jsonify({'success': True, 'id': department.id, 'name': department.name})

@bp.route('/locations/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_location(id):
    location = Location.query.get_or_404(id)
    if request.method == 'POST':
        location.name = request.form.get('name')
        location.code = request.form.get('code')
        location.description = request.form.get('description')
        location.is_active = bool(request.form.get('is_active'))
        
        db.session.commit()
        flash('Location updated successfully.', 'success')
        return redirect(url_for('list_forms.locations'))
    
    return render_template('list_forms/edit_location.html', location=location)



# If you have routes for assigning/unassigning employees or customers to assets, add:
# log_employee_history(employee, 'assigned', changed_by=current_user.username)
# log_employee_history(employee, 'unassigned', changed_by=current_user.username)