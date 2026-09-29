from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, send_file, make_response
from flask_login import login_required, current_user
from app.models.asset import Asset, AssetHistory
from app.models.maintenance import Maintenance
from app import db
from datetime import datetime
from app.models.asset_type import AssetType
from app.models.location import Location
from app.models.employee import Employee
from app.models.department import Department
from app.models.manufacturer import Manufacturer
from app.utils.history import log_asset_history, get_client_ip
from app.utils.receipt_generator import generate_checkout_receipt, generate_checkin_receipt, generate_bulk_checkout_receipt, generate_bulk_checkin_receipt
from app.utils.security import (
    sanitize_search_term, sanitize_filter_value, validate_date_string,
    safe_equals_query, validate_pagination_params,
    safe_like_query, ajax_login_required
)
import tempfile
import os
from app.utils.export import export_to_excel
from sqlalchemy import and_, or_, func
import os

bp = Blueprint('asset_management', __name__, url_prefix='/asset-management')

def _is_checkout_eligible(asset: Asset) -> bool:
    """
    Allow checkout when asset is truly available, or when it is in an
    inconsistent legacy state ('Checked Out' with no assigned employee).
    """
    status = (asset.status or '').strip()
    return status == 'Available' or (status == 'Checked Out' and not asset.current_employee_id)


def _apply_asset_text_search_filters(query, search_term: str):
    """
    Apply search as whitespace-separated tokens (AND). Each token may match asset
    name, tag, serial, or assignee first/last name, or full name as 'First Last'.
    This fixes advanced search when multiple fields are joined into one string
    and when users type a full employee name.
    """
    if not search_term or not str(search_term).strip():
        return query
    tokens = [t for t in str(search_term).split() if t.strip()]
    if not tokens:
        return query
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        pat = f"%{token}%"
        assignee_full = func.trim(
            func.concat(
                func.coalesce(Employee.first_name, ''),
                " ",
                func.coalesce(Employee.last_name, ""),
            )
        )
        query = query.filter(
            or_(
                Asset.name.ilike(pat),
                Asset.tag_number.ilike(pat),
                Asset.serial_number.ilike(pat),
                Employee.first_name.ilike(pat),
                Employee.last_name.ilike(pat),
                assignee_full.ilike(pat),
            )
        )
    return query

def generate_and_send_checkout_receipt(asset, employee):
    """Generate checkout receipt and return as downloadable response"""
    try:
        # Create a temporary file for the receipt
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_path = temp_file.name
        
        # Generate the receipt
        receipt_path = generate_checkout_receipt(asset, employee, temp_path)
        
        # Read the file content
        with open(receipt_path, 'rb') as f:
            file_content = f.read()
        
        # Clean up the temporary file
        os.unlink(receipt_path)
        
        # Create response with proper headers
        from flask import Response
        response = Response(
            file_content,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="checkout_receipt_{asset.tag_number}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
            }
        )
        return response
        
    except Exception as e:
        print(f"Error generating checkout receipt: {e}")
        return None

def generate_and_send_checkin_receipt(asset, employee):
    """Generate checkin receipt and return as downloadable response"""
    try:
        # Create a temporary file for the receipt
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_path = temp_file.name
        
        # Generate the receipt
        receipt_path = generate_checkin_receipt(asset, employee, temp_path)
        
        # Read the file content
        with open(receipt_path, 'rb') as f:
            file_content = f.read()
        
        # Clean up the temporary file
        os.unlink(receipt_path)
        
        # Create response with proper headers
        from flask import Response
        response = Response(
            file_content,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="checkin_receipt_{asset.tag_number}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
            }
        )
        return response
        
    except Exception as e:
        print(f"Error generating checkin receipt: {e}")
        return None

@bp.route('/')
@login_required
def index():
    # Get assets that are currently assigned to an employee
    assigned_assets = Asset.query.filter(Asset.current_employee_id.isnot(None)).all()
    return render_template('asset_management/index.html', assigned_assets=assigned_assets)

@bp.route('/list')
@login_required
def list_assets():
    # Sanitize search term to prevent SQL injection
    search_term = sanitize_search_term(request.args.get('q', ''))
    query = Asset.query
    
    if search_term:
        query = query.outerjoin(Employee, Asset.current_employee_id == Employee.id)
        query = _apply_asset_text_search_filters(query, search_term)
    
    assets = query.order_by(Asset.tag_number.asc()).all()
    asset_types = AssetType.query.order_by(AssetType.name.asc()).all()
    # Only show locations that currently have assets (matching reports dashboard behavior)
    locations = Location.query.join(Asset, Location.id == Asset.location_id).distinct().order_by(Location.name.asc()).all()
    employees = Employee.query.filter_by(is_active=True).all()
    
    # Prepare options for select fields
    asset_type_options = [(t.id, t.name) for t in asset_types]
    location_options = [(l.id, l.name) for l in locations]
    department_options = [(d.id, d.name) for d in Department.query.order_by(Department.name.asc()).all()]
    employee_options = [(e.id, e.full_name) for e in employees]
    
    return render_template('assets/list.html', 
                         assets=assets,
                         asset_type_options=asset_type_options,
                         location_options=location_options,
                         department_options=department_options,
                         employee_options=employee_options)

@bp.route('/export')
@login_required
def export_assets():
    # Get and sanitize filter parameters from query string
    location = sanitize_filter_value(request.args.get('location', ''))
    asset_type = sanitize_filter_value(request.args.get('asset_type', ''))
    status = sanitize_filter_value(request.args.get('status', ''))
    department = sanitize_filter_value(request.args.get('department', ''))
    date_from = validate_date_string(request.args.get('date_from', ''))
    date_to = validate_date_string(request.args.get('date_to', ''))
    search = sanitize_search_term(request.args.get('search', ''))
    
    # Build the query with filters
    query = db.session.query(
        Asset,
        AssetType.name.label('asset_type_name'),
        Location.name.label('location_name'),
        Department.name.label('department_name'),
        Employee.first_name.label('employee_first'),
        Employee.last_name.label('employee_last')
    ).outerjoin(AssetType, Asset.asset_type_id == AssetType.id
    ).outerjoin(Location, Asset.location_id == Location.id
    ).outerjoin(Department, Asset.department_id == Department.id
    ).outerjoin(Employee, Asset.current_employee_id == Employee.id)
    
    # Apply filters with safe parameterized queries
    if location:
        query = safe_equals_query(query, Location.name, location)
    if asset_type:
        query = safe_equals_query(query, AssetType.name, asset_type)
    if status:
        query = safe_equals_query(query, Asset.status, status)
    if department:
        query = safe_equals_query(query, Department.name, department)
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(Asset.created_at >= dt_from)
        except Exception:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(Asset.created_at <= dt_to)
        except Exception:
            pass
    query = _apply_asset_text_search_filters(query, search)
    
    # Order by tag number
    query = query.order_by(Asset.tag_number.asc())
    
    # Execute query
    results = query.all()
    
    # Format data for export
    data = []
    for asset, type_name, loc_name, dept_name, emp_first, emp_last in results:
        employee_name = f"{emp_first} {emp_last}" if emp_first and emp_last else "Unassigned"
        
        data.append({
            'Tag Number': asset.tag_number,
            'Name': asset.name,
            'Serial Number': asset.serial_number or '',
            'Status': asset.status,
            'Asset Type': type_name or '',
            'Location': loc_name or '',
            'Department': dept_name or '',
            'Assigned To': employee_name,
            'Purchase Price': asset.purchase_price or 0,
            'Purchase Date': asset.purchase_date.strftime('%Y-%m-%d') if asset.purchase_date else '',
            'Manufacturer': asset.manufacturer.name if asset.manufacturer else '',
            'Model Number': asset.model_number or '',
            'Warranty Expiration': asset.warranty_expiration.strftime('%Y-%m-%d') if asset.warranty_expiration else ''
        })
    
    response = export_to_excel(data, 'Assets', 'assets')
    if response:
        return response
    return redirect(url_for('asset_management.list_assets'))

@bp.route('/api/filtered-assets')
@ajax_login_required
def filtered_assets():
    """API endpoint for filtered assets with DataTables integration"""
    try:
        import traceback
        
        print(f"[filtered_assets] API called by user: {current_user.username if current_user.is_authenticated else 'anonymous'}")
        
        # Get and sanitize filter parameters
        location = sanitize_filter_value(request.args.get('location', ''))
        asset_type = sanitize_filter_value(request.args.get('asset_type', ''))
        status = sanitize_filter_value(request.args.get('status', ''))
        department = sanitize_filter_value(request.args.get('department', ''))
        date_from = validate_date_string(request.args.get('date_from', ''))
        date_to = validate_date_string(request.args.get('date_to', ''))
        search = sanitize_search_term(request.args.get('search', ''))
        
        print(f"[filtered_assets] Filters - location: {location}, type: {asset_type}, status: {status}, search: {search}")
        
        # Build the query - use proper join syntax
        query = db.session.query(
            Asset,
            AssetType.name.label('asset_type_name'),
            Location.name.label('location_name'),
            Department.name.label('department_name'),
            Employee.first_name.label('employee_first'),
            Employee.last_name.label('employee_last')
        ).outerjoin(AssetType, Asset.asset_type_id == AssetType.id
        ).outerjoin(Location, Asset.location_id == Location.id
        ).outerjoin(Department, Asset.department_id == Department.id
        ).outerjoin(Employee, Asset.current_employee_id == Employee.id
        ).filter(Asset.id.isnot(None))  # Ensure we only get valid assets
        
        # Apply filters with safe parameterized queries
        if location:
            query = safe_equals_query(query, Location.name, location)
        if asset_type:
            query = safe_equals_query(query, AssetType.name, asset_type)
        if status:
            query = safe_equals_query(query, Asset.status, status)
        if department:
            query = safe_equals_query(query, Department.name, department)
        if date_from:
            try:
                dt_from = datetime.fromisoformat(date_from)
                query = query.filter(Asset.created_at >= dt_from)
            except Exception:
                pass
        if date_to:
            try:
                dt_to = datetime.fromisoformat(date_to)
                query = query.filter(Asset.created_at <= dt_to)
            except Exception:
                pass
        query = _apply_asset_text_search_filters(query, search)
        
        # Order by tag number
        query = query.order_by(Asset.tag_number.asc())
        
        # Execute query
        print(f"[filtered_assets] Executing query...")
        results = query.all()
        print(f"[filtered_assets] Query returned {len(results)} results")
        
        # Format data for DataTables
        data = []
        processed_count = 0
        error_count = 0
        for result in results:
            try:
                # Unpack the result tuple
                asset, type_name, loc_name, dept_name, emp_first, emp_last = result
                
                # Skip if asset is None (shouldn't happen with proper joins, but safety check)
                if asset is None:
                    print("Warning: Found None asset in results, skipping")
                    continue
                
                # Handle employee name - combine first and last name, or show Unassigned
                if emp_first and emp_last:
                    employee_name = f"{emp_first} {emp_last}".strip()
                elif emp_first:
                    employee_name = emp_first.strip()
                elif emp_last:
                    employee_name = emp_last.strip()
                else:
                    employee_name = "Unassigned"
                
                data.append({
                    'id': asset.id,
                    'name': asset.name,
                    'tag_number': asset.tag_number,
                    'serial_number': asset.serial_number or '',
                    'status': asset.status,
                    'asset_type_name': type_name or '',
                    'employee_name': employee_name,
                    'location_name': loc_name or '',
                    'department_name': dept_name or '',
                    'purchase_price': float(asset.purchase_price) if asset.purchase_price else 0,
                    'purchase_date': asset.purchase_date.isoformat() if asset.purchase_date else None,
                    'created_at': asset.created_at.isoformat() if asset.created_at else None
                })
                processed_count += 1
            except Exception as e:
                error_count += 1
                print(f"[filtered_assets] Error processing asset result {error_count}: {e}")
                print(f"[filtered_assets] Result tuple type: {type(result)}, length: {len(result) if hasattr(result, '__len__') else 'N/A'}")
                import traceback
                traceback.print_exc()
                # Skip this asset but continue with others
                continue
        
        print(f"[filtered_assets] Processed {processed_count} assets successfully, {error_count} errors")
        print(f"[filtered_assets] Returning {len(data)} assets to client")
        
        # Refresh session to keep it alive (prevent expiration during long page views)
        from flask import session
        if session.get('_permanent'):
            session.permanent = True
            # Touch the session to update its expiration time
            session.modified = True
        
        return jsonify({
            'data': data,
            'recordsTotal': len(data),
            'recordsFiltered': len(data)
        })
        
    except Exception as e:
        print(f"[filtered_assets] CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'data': [],
            'recordsTotal': 0,
            'recordsFiltered': 0,
            'error': f'Failed to load assets data: {str(e)}'
        }), 500

@bp.route('/<int:asset_id>', endpoint='asset_detail')
@login_required
def asset_detail(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    return render_template('assets/detail.html', asset=asset)

@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_asset():
    asset_types = AssetType.query.order_by(AssetType.name.asc()).all()
    # Show all locations (not just those with assets)
    locations = Location.query.order_by(Location.name.asc()).all()
    departments = Department.query.order_by(Department.name.asc()).all()
    manufacturers = Manufacturer.query.order_by(Manufacturer.name.asc()).all()
    # Get all active employees for assignment
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.first_name, Employee.last_name).all()
    
    
    if request.method == 'POST':
        tag_number = request.form.get('tag_number')
        serial_number = request.form.get('serial_number')
        status = request.form.get('status')
        asset_type_id = request.form.get('asset_type_id')
        location_id = request.form.get('location_id')
        department_id = request.form.get('department_id')
        manufacturer_id = request.form.get('manufacturer_id')
        purchase_price = request.form.get('purchase_price')
        
        if not all([tag_number, status, asset_type_id, location_id, purchase_price]):
            flash('All fields are required.', 'danger')
            return render_template('assets/new.html', asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
            
        # Check if tag_number already exists
        existing_asset = Asset.query.filter_by(tag_number=tag_number).first()
        if existing_asset:
            flash(f'Tag number "{tag_number}" already exists. Please choose a different tag number.', 'danger')
            return render_template('assets/new.html', asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        
        # Check if serial_number already exists (if provided)
        if serial_number:
            existing_asset = Asset.query.filter_by(serial_number=serial_number).first()
            if existing_asset:
                flash(f'Serial number "{serial_number}" already exists. Please choose a different serial number.', 'danger')
                return render_template('assets/new.html', asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
            
        try:
            purchase_price = float(purchase_price) if purchase_price else None
        except (TypeError, ValueError):
            flash('Purchase price must be a valid number.', 'danger')
            return render_template('assets/new.html', asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
            
        try:
            # Get employee_id if status is "Checked Out"
            employee_id = None
            if status == 'Checked Out':
                employee_id = request.form.get('employee_id')
                if not employee_id:
                    flash('Employee assignment is required when status is "Checked Out".', 'danger')
                    return render_template('assets/new.html', asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
            
            # Get the asset type to set the name
            asset_type = AssetType.query.get(asset_type_id)
            asset_name = asset_type.name if asset_type else ""
            
            # Fallback: use form data if asset type lookup fails
            if not asset_name:
                asset_name = request.form.get('name', '')
            
            # Calculate next ID using Approach 3 from your solution
            max_id = db.session.query(db.func.max(Asset.id)).scalar()
            next_id = (max_id or 0) + 1
            
            asset = Asset()
            asset.id = next_id  # Explicitly set the ID
            asset.name = asset_name  # Set name from asset type
            asset.tag_number = tag_number
            asset.serial_number = serial_number
            asset.status = status
            asset.asset_type_id = asset_type_id
            asset.location_id = location_id
            asset.department_id = department_id if department_id else None
            asset.manufacturer_id = manufacturer_id if manufacturer_id else None
            asset.purchase_price = purchase_price
            asset.current_employee_id = employee_id
            
            # Ensure the name is synchronized with the asset type (backup)
            asset.sync_name_with_type()
            db.session.add(asset)
            
            # Flush to get the ID without committing
            db.session.flush()
            
            # Get asset details while still in session
            asset_id = asset.id
            asset_tag = asset.tag_number
            asset_name = asset.name
            
            # Commit the asset
            db.session.commit()
            
            # Log the history using the asset ID (re-query the asset to ensure it's fresh)
            fresh_asset = Asset.query.get(asset_id)
            if fresh_asset:
                log_asset_history(fresh_asset, 'created', changed_by=current_user.username)
                
                # Log IP address for audit trail
                client_ip = get_client_ip()
                print(f"Asset created: {asset_tag} by {current_user.username} from IP: {client_ip}")
                
                # Commit the history
                db.session.commit()
                
                # If asset is checked out, generate and return checkout receipt
                if fresh_asset.status == 'Checked Out' and fresh_asset.current_employee_id:
                    employee = Employee.query.get(fresh_asset.current_employee_id)
                    if employee:
                        receipt_response = generate_and_send_checkout_receipt(fresh_asset, employee)
                        if receipt_response:
                            flash('Asset added successfully. Checkout receipt downloaded.', 'success')
                            return receipt_response
                
            else:
                print(f"Warning: Could not find asset with ID {asset_id} for history logging")
            
            flash('Asset added successfully.', 'success')
            return redirect(url_for('asset_management.list_assets', refresh='true'))
            
        except Exception as e:
            db.session.rollback()  # Rollback the session on error
            flash(f'Failed to add asset: {str(e)}', 'danger')
            return render_template('assets/new.html', asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
            
    return render_template('assets/new.html', asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)

@bp.route('/move/<int:asset_id>', methods=['GET', 'POST'])
@login_required
def move_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    if request.method == 'POST':
        # Handle asset movement
        pass
    return render_template('asset_management/move.html', asset=asset)

@bp.route('/checkout/<int:asset_id>', methods=['POST'])
@login_required
def checkout_asset(asset_id):
    try:
        asset = Asset.query.get_or_404(asset_id)
        if asset.status != 'Available':
            flash('Asset is not available for checkout.', 'danger')
            return redirect(url_for('asset_management.list_assets'))
        
        employee_id = request.form.get('employee_id')
        if not employee_id:
            flash('No employee selected for checkout.', 'danger')
            return redirect(url_for('asset_management.list_assets'))
        
        employee = Employee.query.get(employee_id)
        if not employee:
            flash('Selected employee does not exist.', 'danger')
            return redirect(url_for('asset_management.list_assets'))
        
        # Update asset status
        asset.current_employee_id = employee.id
        asset.status = 'Checked Out'
        
        # Log the history AFTER updating asset
        log_asset_history(asset, 'checked_out', changed_by=current_user.username)
        
        # Log IP address for audit trail
        client_ip = get_client_ip()
        print(f"Asset checked out: {asset.tag_number} to {employee.full_name} by {current_user.username} from IP: {client_ip}")
        
        # Commit all changes together
        db.session.commit()
        
        # Generate and return checkout receipt
        receipt_response = generate_and_send_checkout_receipt(asset, employee)
        if receipt_response:
            flash(f'Asset checked out to {employee.full_name}. Checkout receipt downloaded.', 'success')
            return receipt_response
        
        flash(f'Asset checked out to {employee.full_name}.', 'success')
        return redirect(url_for('asset_management.list_assets'))
        
    except Exception as e:
        db.session.rollback()
        print(f"Error during checkout: {str(e)}")
        flash(f'Error during checkout: {str(e)}', 'danger')
        return redirect(url_for('asset_management.list_assets'))

@bp.route('/checkin/<int:asset_id>', methods=['POST'])
@login_required
def checkin_asset(asset_id):
    try:
        asset = Asset.query.get_or_404(asset_id)
        if asset.status != 'Checked Out':
            flash('Asset is not checked out.', 'danger')
            return redirect(url_for('asset_management.list_assets'))
        
        
        # Store the employee ID before clearing it for history logging
        previous_employee_id = asset.current_employee_id
        previous_employee = Employee.query.get(previous_employee_id) if previous_employee_id else None
        
        # Update asset status
        asset.current_employee_id = None
        asset.status = 'Available'
        
        # Log the history AFTER updating asset
        log_asset_history(asset, 'checked_in', changed_by=current_user.username)
        
        # Log IP address for audit trail
        client_ip = get_client_ip()
        print(f"Asset checked in: {asset.tag_number} by {current_user.username} from IP: {client_ip}")
        
        # Commit all changes together
        db.session.commit()
        
        # Generate and return checkin receipt if we have the previous employee
        if previous_employee:
            receipt_response = generate_and_send_checkin_receipt(asset, previous_employee)
            if receipt_response:
                flash('Asset checked in successfully. Checkin receipt downloaded.', 'success')
                return receipt_response
        
        flash('Asset checked in successfully.', 'success')
        return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))
        
    except Exception as e:
        db.session.rollback()
        print(f"Error during check-in: {str(e)}")
        flash(f'Error during check-in: {str(e)}', 'danger')
        return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))

@bp.route('/audit/<int:asset_id>', methods=['GET', 'POST'])
@login_required
def audit_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    if request.method == 'POST':
        # Handle asset audit
        pass
    return render_template('asset_management/audit.html', asset=asset)

# maintenance route to list all asset with In Maintenance status
@bp.route('/maintenance')
@login_required
def maintenance():
    # Pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 25

    # Get assets in maintenance (fresh query so list updates after remove-maintenance)
    query = Asset.query.filter_by(status='In Maintenance')
    total = query.count()
    assets = query.order_by(Asset.name).offset((page - 1) * per_page).limit(per_page).all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    response = make_response(render_template('maintenance/list.html',
                         assets=assets,
                         pagination={
                             'page': page,
                             'per_page': per_page,
                             'total': total,
                             'total_pages': total_pages,
                             'has_next': page < total_pages,
                             'has_prev': page > 1
                         }))
    # Prevent caching so after "Remove Maintenance" the list shows current data
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

@bp.route('/maintenance/<int:asset_id>', methods=['POST'])
@login_required
def send_to_maintenance(asset_id):
    try:
        asset = Asset.query.get_or_404(asset_id)
        
        # Check if asset can be sent to maintenance
        if asset.status == 'In Maintenance':
            flash('Asset is already in maintenance.', 'warning')
            return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))
        
        if asset.status == 'Disposed':
            flash('Cannot send disposed asset to maintenance.', 'danger')
            return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))
        
        if asset.status == 'Checked Out':
            flash('Asset is currently checked out. Please check it in first before sending to maintenance.', 'warning')
            return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))
        
        # Update asset status
        asset.status = 'In Maintenance'
        asset.last_maintenance_date = datetime.now()
        
        # Log the maintenance action
        log_asset_history(asset, 'maintenance_in', changed_by=current_user.username)
        
        # Commit all changes together
        db.session.commit()
        flash('Asset sent to maintenance successfully.', 'success')
        return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error sending asset to maintenance: {str(e)}', 'danger')
        return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))

# remove asset from maintenance
@bp.route('/remove-maintenance/<int:asset_id>', methods=['POST'])
@login_required
def remove_maintenance(asset_id):
    # Redirect back to the page the user came from
    referrer = request.referrer or ''
    from_maintenance_list = '/asset-management/maintenance' in referrer
    from_assets_list = '/asset-management/list' in referrer

    def _redirect():
        if from_maintenance_list:
            return redirect(url_for('asset_management.maintenance'))
        if from_assets_list:
            return redirect(url_for('asset_management.list_assets'))
        return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))

    try:
        asset = Asset.query.get_or_404(asset_id)

        # Check if asset is actually in maintenance (strip in case DB has whitespace)
        current_status = (asset.status or '').strip()
        if current_status != 'In Maintenance':
            flash('Asset is not currently in maintenance.', 'warning')
            return _redirect()

        # Determine the appropriate status to restore.
        # Important: If someone edited the asset (e.g. changed location) while it was In Maintenance,
        # there will be an "updated" history record with status still "In Maintenance". We must
        # ignore any history record whose status is "In Maintenance" and use the last record that
        # had a real non-maintenance status (Available, Checked Out, or Disposed).
        VALID_STATUSES_TO_RESTORE = ('Available', 'Checked Out', 'Disposed')
        try:
            last_status_record = (
                AssetHistory.query.filter_by(asset_id=asset_id)
                .filter(AssetHistory.action.notin_(['maintenance_in', 'maintenance_out']))
                .filter(AssetHistory.status.in_(VALID_STATUSES_TO_RESTORE))
                .order_by(AssetHistory.changed_at.desc())
                .first()
            )

            if last_status_record and (last_status_record.status or '').strip():
                asset.status = (last_status_record.status or '').strip()
            else:
                asset.status = 'Available'

            # Safety: never leave as In Maintenance (e.g. if history had unexpected value)
            if (asset.status or '').strip() == 'In Maintenance':
                asset.status = 'Available'

        except Exception as e:
            print(f"Error determining previous status: {e}")
            asset.status = 'Available'

        # Flush so the status update is written before we add history (ensures DB sees new status)
        db.session.flush()

        # Log the maintenance removal (history will show the new status)
        log_asset_history(asset, 'maintenance_out', changed_by=current_user.username)

        # Commit all changes together
        db.session.commit()
        flash('Asset removed from maintenance successfully.', 'success')
        return _redirect()

    except Exception as e:
        db.session.rollback()
        flash(f'Error removing asset from maintenance: {str(e)}', 'danger')
        return _redirect()

@bp.route('/dispose/<int:asset_id>', methods=['POST'])
@login_required
def dispose_asset(asset_id):
    try:
        asset = Asset.query.get_or_404(asset_id)
        
        # Check if asset can be disposed
        if asset.status == 'Disposed':
            flash('Asset is already disposed.', 'warning')
            return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))
        
        if asset.status == 'Checked Out':
            flash('Cannot dispose asset: it is currently checked out to an employee. Please check it in first.', 'danger')
            return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))
        
        if asset.status == 'In Maintenance':
            flash('Cannot dispose asset: it is currently in maintenance. Please remove it from maintenance first.', 'danger')
            return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))
        
        # Update asset status
        asset.status = 'Disposed'
        asset.current_employee_id = None
        
        # Log the disposal action
        log_asset_history(asset, 'disposed', changed_by=current_user.username)
        
        # Commit all changes together
        db.session.commit()
        flash('Asset disposed successfully.', 'success')
        return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error disposing asset: {str(e)}', 'danger')
        return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))

@bp.route('/maintenance/<int:asset_id>')
@login_required
def maintenance_history(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    maintenance_records = Maintenance.query.filter_by(asset_id=asset_id).order_by(Maintenance.start_date.desc()).all()
    return render_template('maintenance/history.html', asset=asset, maintenance_records=maintenance_records)

@bp.route('/maintenance/new/<int:asset_id>', methods=['GET', 'POST'])
@login_required
def new_maintenance(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    if request.method == 'POST':
        maintenance = Maintenance()
        maintenance.asset_id = asset_id
        maintenance.maintenance_type = request.form['maintenance_type']
        maintenance.priority = request.form['priority']
        maintenance.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        maintenance.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date() if request.form.get('end_date') else None
        maintenance.cost = request.form.get('cost')
        maintenance.description = request.form['description']
        maintenance.findings = request.form.get('findings')
        maintenance.recommendations = request.form.get('recommendations')
        maintenance.requires_followup = bool(request.form.get('requires_followup'))
        db.session.add(maintenance)
        db.session.commit()
        flash('Maintenance record created successfully.', 'success')
        return redirect(url_for('asset_management.maintenance_history', asset_id=asset_id))
    return render_template('maintenance/new.html', asset=asset)

@bp.route('/maintenance/edit/<int:record_id>', methods=['GET', 'POST'])
@login_required
def edit_maintenance(record_id):
    """Edit an existing maintenance record"""
    maintenance = Maintenance.query.get_or_404(record_id)
    
    if request.method == 'POST':
        maintenance.maintenance_type = request.form['maintenance_type']
        maintenance.priority = request.form['priority']
        maintenance.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        maintenance.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date() if request.form.get('end_date') else None
        maintenance.cost = request.form.get('cost')
        maintenance.description = request.form['description']
        maintenance.findings = request.form.get('findings')
        maintenance.recommendations = request.form.get('recommendations')
        maintenance.requires_followup = bool(request.form.get('requires_followup'))
        
        db.session.commit()
        flash('Maintenance record updated successfully.', 'success')
        return redirect(url_for('asset_management.maintenance_history', asset_id=maintenance.asset_id))
    
    return render_template('asset_management/maintenance.html', 
                         asset=maintenance.asset,
                         maintenance=maintenance,
                         today=datetime.now().date())

@bp.route('/find')
@login_required
def find_asset():
    # Sanitize search query to prevent SQL injection
    query = sanitize_search_term(request.args.get('q', ''))
    if query:
        assets = Asset.query.outerjoin(Employee, Asset.current_employee_id == Employee.id).filter(
            (Asset.tag_number.ilike(f'%{query}%')) |
            (Asset.name.ilike(f'%{query}%')) |
            (Asset.serial_number.ilike(f'%{query}%')) |
            (Employee.first_name.ilike(f'%{query}%')) |
            (Employee.last_name.ilike(f'%{query}%'))
        ).all()
    else:
        assets = []
    return render_template('asset_management/find.html', assets=assets, query=query)

@bp.route('/advanced-find', methods=['GET', 'POST'])
@login_required
def advanced_find():
    if request.method == 'POST':
        # Handle advanced search
        pass
    return render_template('asset_management/advanced_find.html')

@bp.route('/bulk-assign', methods=['GET', 'POST'])
@login_required
def bulk_assign():
    """Handle bulk assignment of multiple assets to one employee"""
    if request.method == 'POST':
        selected_assets = request.form.getlist('selected_assets[]')
        employee_id = request.form.get('employee_id')
        
        if not selected_assets:
            flash('Please select at least one asset to assign.', 'warning')
            return redirect(url_for('asset_management.bulk_assign'))
        
        if not employee_id:
            flash('Please select an employee to assign assets to.', 'warning')
            return redirect(url_for('asset_management.bulk_assign'))
        
        employee = Employee.query.get(employee_id)
        if not employee:
            flash('Selected employee does not exist.', 'danger')
            return redirect(url_for('asset_management.bulk_assign'))
        
        # Get the selected assets
        assets = Asset.query.filter(Asset.id.in_(selected_assets)).all()
        
        # Check if any assets are already checked out
        unavailable_assets = [asset for asset in assets if not _is_checkout_eligible(asset)]
        if unavailable_assets:
            unavailable_tags = [asset.tag_number for asset in unavailable_assets]
            flash(f'Some assets are not available for assignment: {", ".join(unavailable_tags)}', 'warning')
            # Filter out unavailable assets
            assets = [asset for asset in assets if _is_checkout_eligible(asset)]
        
        if not assets:
            flash('No available assets to assign.', 'warning')
            return redirect(url_for('asset_management.bulk_assign'))
        
        # Assign all available assets
        assigned_count = 0
        failed_assignments = []
        
        for asset in assets:
            try:
                # Update asset status
                asset.current_employee_id = employee.id
                asset.status = 'Checked Out'
                
                # Log the assignment
                log_asset_history(asset, 'checked_out', changed_by=current_user.username)
                assigned_count += 1
                
            except Exception as e:
                failed_assignments.append(f"{asset.tag_number}: {str(e)}")
                print(f"Error assigning asset {asset.tag_number}: {e}")
        
        # Commit all changes
        try:
            db.session.commit()
            
            # Generate ONE bulk checkout receipt for the newly assigned assets only
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                    temp_path = temp_file.name
                
                # Generate bulk receipt for only the assets that were just checked out
                bulk_receipt_path = generate_bulk_checkout_receipt(assets, employee, temp_path)
                
                # Read the file content
                with open(bulk_receipt_path, 'rb') as f:
                    file_content = f.read()
                
                # Clean up the temporary file
                os.unlink(bulk_receipt_path)
                
                # Create success message
                success_msg = f'Successfully checked out {assigned_count} asset(s) to {employee.full_name}.'
                if failed_assignments:
                    success_msg += f' Failed assignments: {"; ".join(failed_assignments)}'
                
                flash(success_msg, 'success')
                
                # Return the bulk receipt as download
                from flask import Response
                response = Response(
                    file_content,
                    mimetype='application/pdf',
                    headers={
                        'Content-Disposition': f'attachment; filename="bulk_checkout_receipt_{employee.full_name.replace(" ", "_")}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
                    }
                )
                return response
                
            except Exception as e:
                print(f"Error generating bulk receipt: {e}")
                flash('Assets checked out successfully, but receipt generation failed.', 'warning')
            
            return redirect(url_for('asset_management.list_assets'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error during bulk assignment: {str(e)}', 'danger')
            return redirect(url_for('asset_management.bulk_assign'))
    
    # GET request - include available assets plus legacy inconsistent assets
    # where status is "Checked Out" but no employee is assigned.
    assets = Asset.query.filter(
        or_(
            Asset.status == 'Available',
            and_(Asset.status == 'Checked Out', Asset.current_employee_id.is_(None))
        )
    ).order_by(Asset.tag_number).all()
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.first_name, Employee.last_name).all()
    
    return render_template('asset_management/bulk_assign.html',
        assets=assets,
        employees=employees)

@bp.route('/bulk-checkin', methods=['GET', 'POST'])
@login_required
def bulk_checkin():
    """Handle bulk check-in of multiple assets from one employee"""
    if request.method == 'POST':
        selected_assets = request.form.getlist('selected_assets[]')
        employee_id = request.form.get('employee_id')
        
        if not selected_assets:
            flash('Please select at least one asset to check in.', 'warning')
            return redirect(url_for('asset_management.bulk_checkin'))
        
        if not employee_id:
            flash('Please select an employee to check in assets from.', 'warning')
            return redirect(url_for('asset_management.bulk_checkin'))
        
        employee = Employee.query.get(employee_id)
        if not employee:
            flash('Selected employee does not exist.', 'danger')
            return redirect(url_for('asset_management.bulk_checkin'))
        
        # Get the selected assets
        assets = Asset.query.filter(Asset.id.in_(selected_assets)).all()
        
        # Check if any assets are not checked out to this employee
        unavailable_assets = [asset for asset in assets if asset.status != 'Checked Out' or asset.current_employee_id != employee.id]
        if unavailable_assets:
            unavailable_tags = [asset.tag_number for asset in unavailable_assets]
            flash(f'Some assets are not checked out to this employee: {", ".join(unavailable_tags)}', 'warning')
            # Filter out unavailable assets
            assets = [asset for asset in assets if asset.status == 'Checked Out' and asset.current_employee_id == employee.id]
        
        if not assets:
            flash('No assets checked out to this employee to check in.', 'warning')
            return redirect(url_for('asset_management.bulk_checkin'))
        
        # Check in all available assets
        checked_in_count = 0
        failed_checkins = []
        
        for asset in assets:
            try:
                # Update asset status
                asset.current_employee_id = None
                asset.status = 'Available'
                
                # Log the check-in
                log_asset_history(asset, 'checked_in', changed_by=current_user.username)
                checked_in_count += 1
                
            except Exception as e:
                failed_checkins.append(f"{asset.tag_number}: {str(e)}")
                print(f"Error checking in asset {asset.tag_number}: {e}")
        
        # Commit all changes
        try:
            db.session.commit()
            
            # Generate ONE bulk check-in receipt for the newly checked in assets only
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                    temp_path = temp_file.name
                
                # Generate bulk receipt for only the assets that were just checked in
                bulk_receipt_path = generate_bulk_checkin_receipt(assets, employee, temp_path)
                
                # Read the file content
                with open(bulk_receipt_path, 'rb') as f:
                    file_content = f.read()
                
                # Clean up the temporary file
                os.unlink(bulk_receipt_path)
                
                # Create success message
                success_msg = f'Successfully checked in {checked_in_count} asset(s) from {employee.full_name}.'
                if failed_checkins:
                    success_msg += f' Failed check-ins: {"; ".join(failed_checkins)}'
                
                flash(success_msg, 'success')
                
                # Return the bulk receipt as download
                from flask import Response
                response = Response(
                    file_content,
                    mimetype='application/pdf',
                    headers={
                        'Content-Disposition': f'attachment; filename="bulk_checkin_receipt_{employee.full_name.replace(" ", "_")}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
                    }
                )
                return response
                
            except Exception as e:
                print(f"Error generating bulk receipt: {e}")
                flash('Assets checked in successfully, but receipt generation failed.', 'warning')
            
            return redirect(url_for('asset_management.list_assets'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error during bulk check-in: {str(e)}', 'danger')
            return redirect(url_for('asset_management.bulk_checkin'))
    
    # GET request - show all checked out assets grouped by employee
    checked_out_assets = Asset.query.filter_by(status='Checked Out').order_by(Asset.current_employee_id, Asset.tag_number).all()
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.first_name, Employee.last_name).all()
    
    return render_template('asset_management/bulk_checkin.html',
        assets=checked_out_assets,
        employees=employees)

@bp.route('/print-labels', methods=['GET', 'POST'])
@login_required
def print_labels():
    """Handle asset label printing"""
    if request.method == 'POST':
        selected_assets = request.form.getlist('selected_assets[]')
        label_size = request.form.get('label_size', 'medium')
        label_type = request.form.get('label_type', 'standard')
        copies = int(request.form.get('copies', 1))
        
        if not selected_assets:
            flash('Please select at least one asset to print labels.', 'warning')
            return redirect(url_for('asset_management.print_labels'))
        
        # Get the selected assets
        assets = Asset.query.filter(Asset.id.in_(selected_assets)).all()
        
        # Store label preferences in session for potential future use
        session['label_preferences'] = {
            'size': label_size,
            'type': label_type,
            'copies': copies
        }
        
        return render_template('asset_management/print_labels.html',
            assets=assets,
            selected_assets=selected_assets,
            label_size=label_size,
            label_type=label_type,
            copies=copies)
    
    # GET request - show all assets
    assets = Asset.query.order_by(Asset.tag_number).all()
    
    # Get saved preferences if any
    preferences = session.get('label_preferences', {})
    
    return render_template('asset_management/print_labels.html',
        assets=assets,
        label_size=preferences.get('size', 'medium'),
        label_type=preferences.get('type', 'standard'),
        copies=preferences.get('copies', 1))

@bp.route('/maintenance/<int:maintenance_id>')
@login_required
def maintenance_detail(maintenance_id):
    maintenance = Maintenance.query.get_or_404(maintenance_id)
    return render_template('asset_management/maintenance_detail.html', maintenance=maintenance)

@bp.route('/api/add-asset-type', methods=['POST'])
@login_required
def api_add_asset_type():
    # Validate CSRF token
    from flask_wtf.csrf import validate_csrf
    from wtforms import ValidationError
    try:
        validate_csrf(request.form.get('csrf_token'))
    except ValidationError:
        return jsonify({'success': False, 'message': 'Invalid CSRF token.'}), 400
    
    try:
        name = request.form.get('name')
        description = request.form.get('description')
        
        if not name:
            return jsonify({'success': False, 'message': 'Name is required.'}), 400
        
        # Check for uniqueness
        if AssetType.query.filter(AssetType.name == name).first():
            return jsonify({'success': False, 'message': 'Asset type name already exists.'}), 400
        
        asset_type = AssetType()
        asset_type.name = name
        asset_type.description = description
        db.session.add(asset_type)
        db.session.commit()
        
        return jsonify({'success': True, 'id': asset_type.id, 'name': asset_type.name})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error creating asset type: {str(e)}'}), 500

@bp.route('/api/add-location', methods=['POST'])
@login_required
def api_add_location():
    # Validate CSRF token
    from flask_wtf.csrf import validate_csrf
    from wtforms import ValidationError
    try:
        validate_csrf(request.form.get('csrf_token'))
    except ValidationError:
        return jsonify({'success': False, 'message': 'Invalid CSRF token.'}), 400
    
    try:
        name = request.form.get('name')
        code = request.form.get('code')
        
        if not name or not code:
            return jsonify({'success': False, 'message': 'Name and code are required.'}), 400
        
        # Check for uniqueness
        if Location.query.filter((Location.name == name) | (Location.code == code)).first():
            return jsonify({'success': False, 'message': 'Location name or code already exists.'}), 400
        
        location = Location()
        location.name = name
        location.code = code
        db.session.add(location)
        db.session.commit()
        
        return jsonify({'success': True, 'id': location.id, 'name': location.name})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error creating location: {str(e)}'}), 500

@bp.route('/api/add-department', methods=['POST'])
@login_required
def api_add_department():
    name = request.form.get('name')
    code = request.form.get('code')
    if not name or not code:
        return jsonify({'success': False, 'message': 'Name and code are required.'}), 400
    
    # Check for uniqueness
    if Department.query.filter((Department.name == name) | (Department.code == code)).first():
        return jsonify({'success': False, 'message': 'Department name or code already exists.'}), 400
    
    try:
        department = Department()
        department.name = name
        department.code = code
        db.session.add(department)
        db.session.commit()
        return jsonify({'success': True, 'id': department.id, 'name': department.name})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error creating department: {str(e)}'}), 500

@bp.route('/api/add-manufacturer', methods=['POST'])
@login_required
def api_add_manufacturer():
    # Validate CSRF token
    from flask_wtf.csrf import validate_csrf
    from wtforms import ValidationError
    try:
        validate_csrf(request.form.get('csrf_token'))
    except ValidationError:
        return jsonify({'success': False, 'message': 'Invalid CSRF token.'}), 400
    
    name = request.form.get('name')
    description = request.form.get('description')
    
    if not name:
        return jsonify({'success': False, 'message': 'Manufacturer name is required.'}), 400
    
    # Check for uniqueness
    if Manufacturer.query.filter(Manufacturer.name == name).first():
        return jsonify({'success': False, 'message': 'Manufacturer name already exists.'}), 400
    
    try:
        manufacturer = Manufacturer()
        manufacturer.name = name
        manufacturer.description = description if description else None
        db.session.add(manufacturer)
        db.session.commit()
        return jsonify({'success': True, 'id': manufacturer.id, 'name': manufacturer.name})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error creating manufacturer: {str(e)}'}), 500

@bp.route('/<int:asset_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    asset_types = AssetType.query.order_by(AssetType.name.asc()).all()
    # Include all locations that have assets, and ensure current asset's location is included
    locations_with_assets = Location.query.join(Asset, Location.id == Asset.location_id).distinct().order_by(Location.name.asc()).all()
    # Get current asset's location if it exists and isn't in the list
    locations = list(locations_with_assets)
    if asset.location_id:
        current_location = Location.query.get(asset.location_id)
        if current_location:
            # Add current location if not already in the list
            location_ids = [loc.id for loc in locations]
            if current_location.id not in location_ids:
                locations.insert(0, current_location)
    departments = Department.query.order_by(Department.name.asc()).all()
    manufacturers = Manufacturer.query.order_by(Manufacturer.name.asc()).all()
    employees = Employee.query.filter_by(is_active=True).all()
    if request.method == 'POST':
        # Get form data
        new_tag_number = request.form.get('tag_number')
        new_serial_number = request.form.get('serial_number')
        
        # Check if tag number is being changed and if it conflicts with another asset
        if new_tag_number != asset.tag_number:
            existing_asset = Asset.query.filter_by(tag_number=new_tag_number).first()
            if existing_asset and existing_asset.id != asset.id:
                flash(f'Tag number "{new_tag_number}" already exists. Please choose a different tag number.', 'danger')
                return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        
        # Check if serial number is being changed and if it conflicts with another asset
        if new_serial_number and new_serial_number != asset.serial_number:
            existing_asset = Asset.query.filter_by(serial_number=new_serial_number).first()
            if existing_asset and existing_asset.id != asset.id:
                flash(f'Serial number "{new_serial_number}" already exists. Please choose a different serial number.', 'danger')
                return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        
        # Update asset fields
        asset.tag_number = new_tag_number
        asset.serial_number = new_serial_number if new_serial_number else None
        asset.status = request.form.get('status')
        
        # Validate and set asset_type_id
        new_asset_type_id = request.form.get('asset_type_id')
        if new_asset_type_id:
            try:
                new_asset_type_id = int(new_asset_type_id)
                # Verify the asset type exists
                if not AssetType.query.get(new_asset_type_id):
                    flash('Invalid asset type selected.', 'danger')
                    return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
                asset.asset_type_id = new_asset_type_id
            except (ValueError, TypeError):
                flash('Invalid asset type selected.', 'danger')
                return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        else:
            flash('Asset type is required.', 'danger')
            return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        
        # Validate and set location_id
        location_id = request.form.get('location_id')
        if location_id:
            try:
                location_id = int(location_id)
                # Verify the location exists
                if not Location.query.get(location_id):
                    flash('Invalid location selected.', 'danger')
                    return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
                asset.location_id = location_id
            except (ValueError, TypeError):
                flash('Invalid location selected.', 'danger')
                return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        else:
            flash('Location is required.', 'danger')
            return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        
        # Handle optional fields
        department_id = request.form.get('department_id')
        asset.department_id = int(department_id) if department_id else None
        
        manufacturer_id = request.form.get('manufacturer_id')
        asset.manufacturer_id = int(manufacturer_id) if manufacturer_id else None
        
        asset.description = request.form.get('description') if request.form.get('description') else None
        asset.model_number = request.form.get('model_number') if request.form.get('model_number') else None
        
        # Handle employee assignment when status is "Checked Out"
        if asset.status == 'Checked Out':
            employee_id = request.form.get('employee_id')
            if not employee_id:
                flash('Employee assignment is required when status is "Checked Out".', 'danger')
                return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
            asset.current_employee_id = employee_id
        else:
            # Clear employee assignment for other statuses
            asset.current_employee_id = None
        
        # Automatically update the asset name based on the asset type
        if new_asset_type_id:
            asset.sync_name_with_type()
        
        # Handle purchase price validation
        purchase_price = request.form.get('purchase_price')
        if not purchase_price:
            flash('Purchase price is required.', 'danger')
            return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        try:
            asset.purchase_price = float(purchase_price)
        except (TypeError, ValueError):
            flash('Purchase price must be a valid number.', 'danger')
            return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        
        # Handle purchase date
        purchase_date = request.form.get('purchase_date')
        if purchase_date and purchase_date.strip():
            try:
                asset.purchase_date = datetime.strptime(purchase_date.strip(), '%Y-%m-%d').date()
            except ValueError:
                flash('Purchase date must be in YYYY-MM-DD format.', 'danger')
                return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        else:
            asset.purchase_date = None
        
        # Handle warranty expiration
        warranty_expiration = request.form.get('warranty_expiration')
        if warranty_expiration and warranty_expiration.strip():
            try:
                asset.warranty_expiration = datetime.strptime(warranty_expiration.strip(), '%Y-%m-%d').date()
            except ValueError:
                flash('Warranty expiration must be in YYYY-MM-DD format.', 'danger')
                return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
        else:
            asset.warranty_expiration = None
        
        try:
            # Log the change after updating asset
            log_asset_history(asset, 'updated', changed_by=current_user.username)
            
            # Commit all changes together
            db.session.commit()
            
            flash('Asset updated successfully.', 'success')
            return redirect(url_for('asset_management.asset_detail', asset_id=asset.id))
            
        except Exception as e:
            # Rollback on any error
            db.session.rollback()
            flash(f'Error updating asset: {str(e)}', 'danger')
            return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)
            
    return render_template('assets/edit.html', asset=asset, asset_types=asset_types, locations=locations, departments=departments, manufacturers=manufacturers, employees=employees)



@bp.route('/api/assets/<int:asset_id>/history')
@login_required
def asset_history_api(asset_id):
    try:
        history = AssetHistory.query.filter_by(asset_id=asset_id).order_by(AssetHistory.changed_at.desc()).all()
        
        def get_employee_name(emp_id):
            if not emp_id:
                return None
            emp = Employee.query.get(emp_id)
            return emp.full_name if emp else None
        
        result = []
        for h in history:
            try:
                record = {
                    'action': h.action,
                    'changed_by': h.changed_by,
                    'changed_at': h.changed_at.isoformat(),
                    'data': {
                        'tag_number': h.tag_number,
                        'name': h.name,
                        'status': h.status,
                        'current_employee_id': h.current_employee_id,
                        'current_employee_name': get_employee_name(h.current_employee_id),
                        'description': h.description,
                        'serial_number': h.serial_number,
                        'model_number': h.model_number,
                        'purchase_date': h.purchase_date.isoformat() if h.purchase_date else None,
                        'purchase_price': h.purchase_price,
                        'warranty_expiration': h.warranty_expiration.isoformat() if h.warranty_expiration else None,
                        'asset_type_id': h.asset_type_id,
                        'manufacturer_id': h.manufacturer_id,
                        'location_id': h.location_id,
                        'department_id': h.department_id,
                        'created_at': h.created_at.isoformat() if h.created_at else None,
                        'updated_at': h.updated_at.isoformat() if h.updated_at else None,
                        'last_audit_date': h.last_audit_date.isoformat() if h.last_audit_date else None,
                        'last_maintenance_date': h.last_maintenance_date.isoformat() if h.last_maintenance_date else None
                    }
                }
                result.append(record)
            except Exception as e:
                print(f"Error processing history record {h.id}: {e}")
                # Skip this record but continue with others
                continue
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error in asset history API: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to load asset history'}), 500

@bp.route('/<int:asset_id>/export-history')
@login_required
def export_asset_history(asset_id):
    from app.utils.export import export_to_excel
    history = AssetHistory.query.filter_by(asset_id=asset_id).order_by(AssetHistory.changed_at.desc()).all()
    def get_employee_name(emp_id):
        if not emp_id:
            return None
        emp = Employee.query.get(emp_id)
        return emp.full_name if emp else None
    data = []
    for h in history:
        data.append({
            'Date': h.changed_at.strftime('%Y-%m-%d %H:%M:%S') if h.changed_at else '',
            'Action': h.action,
            'User': h.changed_by,
            'Status': h.status,
            'Assigned To': get_employee_name(h.current_employee_id) or '',
            'Tag Number': h.tag_number,
            'Asset Name': h.name,
            'Serial Number': h.serial_number,
            'Model Number': h.model_number,
            'Department': h.department_id,
            'Location': h.location_id,
            'Notes': h.description,
        })
    response = export_to_excel(data, sheet_name='Asset History', base_filename=f'asset_{asset_id}_history')
    if response:
        return response
    else:
        flash('Export failed. No data to export.', 'danger')
        return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))

@bp.route('/assign/<int:asset_id>', methods=['GET', 'POST'])
@login_required
def assign_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    if request.method == 'POST':
        # check what data we are receiving
        print("request data: ", request.form)
        assignee_type = request.form.get('assignee_type')
        # Get all assignee_id values and filter out empty strings
        assignee_ids = request.form.getlist('assignee_id')
        assignee_id = next((id for id in assignee_ids if id), None)  # Get first non-empty ID
        notes = request.form.get('notes')
        
        if not all([assignee_type, assignee_id]):
            flash('Assignee type and assignee are required.', 'danger')
            return redirect(url_for('asset_management.assign_asset', asset_id=asset_id))
        
        if assignee_type == 'employee':
            employee = Employee.query.get(assignee_id)
            if not employee:
                flash('Selected employee does not exist.', 'danger')
                return redirect(url_for('asset_management.assign_asset', asset_id=asset_id))
            
            asset.current_employee_id = employee.id
            asset.status = 'Checked Out'
            
            # Log the assignment
            log_asset_history(
                asset, 
                'checked_out',
                changed_by=current_user.username
                # notes=notes
            )
            
            # Commit all changes together
            db.session.commit()
            
            # Generate receipt
            try:
                receipts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'receipts')
                os.makedirs(receipts_dir, exist_ok=True)
                output_path = os.path.join(receipts_dir, f'checkout_receipt_{asset.tag_number}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf')
                receipt_path = generate_checkout_receipt(asset, employee, output_path)
                
                flash(f'Asset checked out to {employee.full_name} successfully.', 'success')
                return send_file(
                    receipt_path,
                    as_attachment=True,
                    download_name=os.path.basename(receipt_path),
                    mimetype='application/pdf'
                )
            except Exception as e:
                flash(f'Asset assigned but receipt generation failed: {str(e)}', 'warning')
                return redirect(url_for('asset_management.list_assets'))
        
        elif assignee_type == 'department':
            department = Department.query.get(assignee_id)
            if not department:
                flash('Selected department does not exist.', 'danger')
                return redirect(url_for('asset_management.assign_asset', asset_id=asset_id))
            
            asset.department_id = department.id
            asset.status = 'Assigned'
            
            # Log the assignment
            log_asset_history(
                asset,
                'assigned_to_department',
                changed_by=current_user.username
                # notes=notes
            )
            
            # Commit all changes together
            db.session.commit()
            
            flash(f'Asset assigned to department {department.name} successfully.', 'success')
            return redirect(url_for('asset_management.list_assets'))
        
    
    # GET request - show the form
    departments = Department.query.order_by(Department.name.asc()).all()
    department_data = [{'id': d.id, 'text': d.name} for d in departments]
    return render_template('asset_management/assign_asset.html',
        asset=asset,
        department_data=department_data,
        today=datetime.now().date())

@bp.route('/asset/<int:asset_id>/checkout_receipt')
def generate_checkout_receipt_route(asset_id):
    """Generate and download a check-out receipt for an asset."""
    asset = Asset.query.get_or_404(asset_id)
    if not asset.current_employee:
        flash('Asset is not checked out to any employee.', 'error')
        return redirect(url_for('asset_management.asset_detail', asset_id=asset_id))
    
    # Create receipts directory if it doesn't exist
    receipts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'receipts')
    os.makedirs(receipts_dir, exist_ok=True)
    
    # Generate receipt
    output_path = os.path.join(receipts_dir, f'checkout_receipt_{asset.tag_number}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf')
    receipt_path = generate_checkout_receipt(asset, asset.current_employee, output_path)
    
    # Send the file
    return send_file(
        receipt_path,
        as_attachment=True,
        download_name=os.path.basename(receipt_path),
        mimetype='application/pdf'
    )

@bp.route('/asset/<int:asset_id>/checkin_receipt')
def generate_checkin_receipt_route(asset_id):
    try:
        asset = Asset.query.get_or_404(asset_id)
        
        if asset.status != 'Available':
            return jsonify({
                'success': False,
                'error': 'Asset must be available to generate a check-in receipt.'
            }), 400
        
        # Get the last employee who had the asset
        last_history = (
            AssetHistory.query.filter_by(asset_id=asset_id, action="checked_in")
            .order_by(AssetHistory.changed_at.desc())
            .first()
        )

        if not last_history:
            return jsonify({
                'success': False,
                'error': 'No check-in history found for this asset.'
            }), 404

        # get last checkout history to get employee
        last_checkout_history = (
            AssetHistory.query.filter_by(asset_id=asset_id, action="checked_out")
            .order_by(AssetHistory.changed_at.desc())
            .first()
        )
        
        if not last_checkout_history:
            return jsonify({
                'success': False,
                'error': 'No check-out history found for this asset.'
            }), 404
        
        employee = Employee.query.get(last_checkout_history.current_employee_id)
        if not employee:
            return jsonify({
                'success': False,
                'error': 'Employee information not found.'
            }), 404
        
        # Create receipts directory if it doesn't exist
        receipts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'receipts')
        os.makedirs(receipts_dir, exist_ok=True)
        
        # Generate receipt
        output_path = os.path.join(receipts_dir, f'checkin_receipt_{asset.tag_number}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf')
        receipt_path = generate_checkin_receipt(asset, employee, output_path)
        
        # Send the file
        return send_file(
            receipt_path,
            as_attachment=True,
            download_name=os.path.basename(receipt_path),
            mimetype='application/pdf'
        )
    except Exception as e:
        print(f"Error generating check-in receipt: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred while generating the receipt.'
        }), 500