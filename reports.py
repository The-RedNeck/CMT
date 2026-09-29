from flask import Blueprint, render_template, jsonify, request, send_file
from flask_login import login_required
from app.models.asset import Asset
from app.models.maintenance import Maintenance
from app.models.department import Department
from app.models.location import Location
from app.models.asset_type import AssetType
from app import db
from sqlalchemy import func, extract
from app.utils.security import (
    sanitize_search_term, sanitize_filter_value, validate_date_string,
    safe_ilike_query, safe_equals_query, validate_pagination_params,
    safe_like_query
)
import pandas as pd
from datetime import datetime, timedelta
import io
import os
from openpyxl.utils import get_column_letter

bp = Blueprint('reports', __name__, url_prefix='/reports')

@bp.route('/')
@login_required
def dashboard():
    return render_template('reports/dashboard.html')

@bp.route('/api/asset-status')
@login_required
def asset_status():
    # Enhanced status query with total value
    status_data = db.session.query(
        Asset.status,
        func.count(Asset.id).label('count'),
        func.sum(Asset.purchase_price).label('total_value')
    ).group_by(Asset.status).all()
    
    return jsonify({
        'labels': [status for status, _, _ in status_data],
        'counts': [count for _, count, _ in status_data],
        'values': [float(value) if value else 0 for _, _, value in status_data]
    })

@bp.route('/api/maintenance-costs')
@login_required
def maintenance_costs():
    # Get maintenance costs for the last 12 months with count
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    costs = db.session.query(
        func.strftime('%Y-%m', Maintenance.start_date).label('month'),
        func.sum(Maintenance.cost).label('total_cost'),
        func.count(Maintenance.id).label('maintenance_count')
    ).filter(
        Maintenance.start_date >= start_date,
        Maintenance.cost.isnot(None)
    ).group_by('month').order_by('month').all()
    
    return jsonify({
        'labels': [date for date, _, _ in costs],
        'costs': [float(cost) for _, cost, _ in costs],
        'counts': [count for _, _, count in costs]
    })

@bp.route('/api/department-assets')
@login_required
def department_assets():
    # Enhanced department query with total value
    dept_assets = db.session.query(
        Department.name,
        func.count(Asset.id).label('asset_count'),
        func.sum(Asset.purchase_price).label('total_value'),
        func.count(Maintenance.id).label('maintenance_count')
    ).join(Asset, Department.id == Asset.department_id
    ).outerjoin(Maintenance, Asset.id == Maintenance.asset_id
    ).group_by(Department.name).order_by(Department.name.asc()).all()
    
    return jsonify({
        'labels': [dept for dept, _, _, _ in dept_assets],
        'counts': [count for _, count, _, _ in dept_assets],
        'values': [float(value) if value else 0 for _, _, value, _ in dept_assets],
        'maintenance_counts': [count for _, _, _, count in dept_assets]
    })

@bp.route('/api/asset-value-trend')
@login_required
def asset_value_trend():
    # Enhanced value trend with monthly acquisitions
    assets = Asset.query.filter(
        Asset.purchase_date.isnot(None),
        Asset.purchase_price.isnot(None)
    ).all()
    
    df = pd.DataFrame([{
        'date': asset.purchase_date,
        'value': asset.purchase_price,
        'count': 1
    } for asset in assets])
    
    if not df.empty:
        df['month'] = df['date'].dt.to_period('M')
        monthly_data = df.groupby('month').agg({
            'value': 'sum',
            'count': 'count'
        })
        
        return jsonify({
            'labels': [str(date) for date in monthly_data.index],
            'values': [float(value) for value in monthly_data['value']],
            'counts': [int(count) for count in monthly_data['count']]
        })
    
    return jsonify({'labels': [], 'values': [], 'counts': []})

@bp.route('/api/maintenance-frequency')
@login_required
def maintenance_frequency():
    # Enhanced maintenance frequency with average cost
    maintenance_data = db.session.query(
        Asset.asset_type_id,
        func.count(Maintenance.id).label('count'),
        func.avg(Maintenance.cost).label('avg_cost'),
        func.sum(Maintenance.cost).label('total_cost')
    ).join(Maintenance
    ).group_by(Asset.asset_type_id).all()
    
    from app.models.asset_type import AssetType
    asset_types = {at.id: at.name for at in AssetType.query.order_by(AssetType.name.asc()).all()}
    
    return jsonify({
        'labels': [asset_types.get(at_id, 'Unknown') for at_id, _, _, _ in maintenance_data],
        'counts': [count for _, count, _, _ in maintenance_data],
        'avg_costs': [float(cost) if cost else 0 for _, _, cost, _ in maintenance_data],
        'total_costs': [float(cost) if cost else 0 for _, _, _, cost in maintenance_data]
    })

# --- BEGIN: Comprehensive Asset Management Reporting Endpoints ---

@bp.route('/api/asset-status-detailed')
@login_required
def asset_status_detailed():
    query = Asset.query
    
    # Apply filters
    location = request.args.get('location', '').strip()
    asset_type = request.args.get('type', '').strip()
    status_filter = request.args.get('status', '').strip()
    department = request.args.get('department', '').strip()
    date_from = request.args.get('dateFrom', '').strip()
    date_to = request.args.get('dateTo', '').strip()
    
    if location:
        query = query.join(Location).filter(Location.name == location)
    if asset_type:
        query = query.join(AssetType).filter(AssetType.name == asset_type)
    if status_filter:
        query = query.filter(Asset.status == status_filter)
    if department:
        query = query.join(Department).filter(Department.name == department)
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
    
    # Get current asset status counts
    status_data = db.session.query(
        Asset.status,
        func.count(Asset.id).label('count'),
        func.sum(Asset.purchase_price).label('total_value')
    ).filter(Asset.id.in_(query.with_entities(Asset.id))).group_by(Asset.status).all()
    

    
    return jsonify({
        'labels': [status for status, _, _ in status_data],
        'counts': [count for _, count, _ in status_data],
        'values': [float(value) if value else 0 for _, _, value in status_data]
    })

@bp.route('/api/assignments')
@login_required
def assignments():
    from app.models.employee import Employee
    assigned = db.session.query(Employee.id, Employee.first_name, Employee.last_name, func.count(Asset.id)).join(Asset, Asset.current_employee_id == Employee.id).group_by(Employee.id, Employee.first_name, Employee.last_name).all()
    # Unassigned
    unassigned = db.session.query(func.count(Asset.id)).filter(Asset.current_employee_id == None).scalar()
    # By department
    from app.models.department import Department
    by_department = db.session.query(Department.name, func.count(Asset.id)).join(Asset, Asset.department_id == Department.id).group_by(Department.name).all()
    return jsonify({
        'assigned': [{'employee': f"{first} {last}", 'count': count} for _, first, last, count in assigned],
        'unassigned': unassigned,
        'by_department': [{'department': dept, 'count': count} for dept, count in by_department]
    })

@bp.route('/api/disposed-assets')
@login_required
def disposed_assets():
    query = Asset.query.filter(Asset.status == 'Disposed')
    # Filtering with sanitized inputs
    search = sanitize_search_term(request.args.get('search', ''))
    department = sanitize_filter_value(request.args.get('department', ''))
    location = sanitize_filter_value(request.args.get('location', ''))
    asset_type = sanitize_filter_value(request.args.get('type', ''))
    date_from = validate_date_string(request.args.get('dateFrom', ''))
    date_to = validate_date_string(request.args.get('dateTo', ''))
    
    if search:
        # Use safe parameterized queries
        query = query.filter((Asset.name.ilike(f"%{search}%")) | (Asset.tag_number.ilike(f"%{search}%")))
    if department:
        query = query.join(Department).filter(Department.name == department)
    if location:
        query = query.join(Location).filter(Location.name == location)
    if asset_type:
        query = query.join(AssetType).filter(AssetType.name == asset_type)
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(Asset.updated_at >= dt_from)
        except Exception:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(Asset.updated_at <= dt_to)
        except Exception:
            pass
    assets = query.all()
    return jsonify([{'id': a.id, 'name': a.name, 'tag': a.tag_number, 'disposed_on': a.updated_at.isoformat() if a.updated_at else None} for a in assets])



@bp.route('/api/transferred-assets')
@login_required
def transferred_assets():
    from app.models.asset import AssetHistory, Asset
    from app.models.department import Department
    from app.models.location import Location
    from app.models.asset_type import AssetType
    query = AssetHistory.query.filter(AssetHistory.action == 'transferred')
    # Filtering with sanitized inputs
    search = sanitize_search_term(request.args.get('search', ''))
    department = sanitize_filter_value(request.args.get('department', ''))
    location = sanitize_filter_value(request.args.get('location', ''))
    asset_type = sanitize_filter_value(request.args.get('type', ''))
    date_from = validate_date_string(request.args.get('dateFrom', ''))
    date_to = validate_date_string(request.args.get('dateTo', ''))
    
    if search:
        # Use safe parameterized queries
        query = query.filter((AssetHistory.name.ilike(f"%{search}%")) | (AssetHistory.tag_number.ilike(f"%{search}%")))
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(AssetHistory.changed_at >= dt_from)
        except Exception:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(AssetHistory.changed_at <= dt_to)
        except Exception:
            pass
    # Join Asset for department/location/type
    if department or location or asset_type:
        query = query.join(Asset, Asset.id == AssetHistory.asset_id)
        if department:
            query = query.join(Department, Asset.department_id == Department.id).filter(Department.name == department)
        if location:
            query = query.join(Location, Asset.location_id == Location.id).filter(Location.name == location)
        if asset_type:
            query = query.join(AssetType, Asset.asset_type_id == AssetType.id).filter(AssetType.name == asset_type)
    transferred = query.order_by(AssetHistory.changed_at.desc()).all()
    return jsonify([
        {'id': h.asset_id, 'name': h.name, 'tag': h.tag_number, 'transferred_on': h.changed_at.isoformat()} for h in transferred
    ])

@bp.route('/api/audit-overview')
@login_required
def audit_overview():
    overdue = db.session.query(Asset).filter(Asset.last_audit_date == None).count()
    recent = db.session.query(Asset).order_by(Asset.last_audit_date.desc()).limit(10).all()
    return jsonify({
        'overdue': overdue,
        'recent': [{'id': a.id, 'name': a.name, 'last_audit': a.last_audit_date.isoformat() if a.last_audit_date else None} for a in recent]
    })

@bp.route('/api/recent-activity')
@login_required
def recent_activity():
    from app.models.asset import AssetHistory, Asset
    from app.models.department import Department
    from app.models.location import Location
    from app.models.asset_type import AssetType
    query = AssetHistory.query
    # Filtering with sanitized inputs
    search = sanitize_search_term(request.args.get('search', ''))
    department = sanitize_filter_value(request.args.get('department', ''))
    location = sanitize_filter_value(request.args.get('location', ''))
    asset_type = sanitize_filter_value(request.args.get('type', ''))
    date_from = validate_date_string(request.args.get('dateFrom', ''))
    date_to = validate_date_string(request.args.get('dateTo', ''))
    
    if search:
        # Use safe parameterized queries
        query = query.filter((AssetHistory.name.ilike(f"%{search}%")) | (AssetHistory.tag_number.ilike(f"%{search}%")))
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(AssetHistory.changed_at >= dt_from)
        except Exception:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(AssetHistory.changed_at <= dt_to)
        except Exception:
            pass
    # Join Asset for department/location/type
    if department or location or asset_type:
        query = query.join(Asset, Asset.id == AssetHistory.asset_id)
        if department:
            query = query.join(Department, Asset.department_id == Department.id).filter(Department.name == department)
        if location:
            query = query.join(Location, Asset.location_id == Location.id).filter(Location.name == location)
        if asset_type:
            query = query.join(AssetType, Asset.asset_type_id == AssetType.id).filter(AssetType.name == asset_type)
    recent = query.order_by(AssetHistory.changed_at.desc()).limit(20).all()
    return jsonify([
        {'id': h.asset_id, 'name': h.name, 'action': h.action, 'by': h.changed_by, 'at': h.changed_at.isoformat()} for h in recent
    ])

@bp.route('/api/value-by-status')
@login_required
def value_by_status():
    data = db.session.query(Asset.status, func.sum(Asset.purchase_price)).group_by(Asset.status).all()
    return jsonify({
        'labels': [status for status, _ in data],
        'values': [float(value) if value else 0 for _, value in data]
    })

@bp.route('/api/value-by-type')
@login_required
def value_by_type():
    from app.models.asset_type import AssetType
    query = Asset.query
    
    # Apply filters
    location = request.args.get('location', '').strip()
    status_filter = request.args.get('status', '').strip()
    date_from = request.args.get('dateFrom', '').strip()
    date_to = request.args.get('dateTo', '').strip()
    

    
    if location:
        query = query.join(Location).filter(Location.name == location)
    if status_filter:
        query = query.filter(Asset.status == status_filter)
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
    
    data = db.session.query(
        AssetType.name, 
        func.sum(Asset.purchase_price)
    ).join(Asset, Asset.asset_type_id == AssetType.id
    ).filter(Asset.id.in_(query.with_entities(Asset.id))
    ).group_by(AssetType.name).order_by(AssetType.name.asc()).all()
    
    return jsonify({
        'labels': [name for name, _ in data],
        'values': [float(value) if value else 0 for _, value in data]
    })

@bp.route('/api/value-by-department')
@login_required
def value_by_department():
    from app.models.department import Department
    
    # Get filter parameters
    status_filter = request.args.get('status', '').strip()
    

    
    query = Asset.query
    
    # Apply status filter
    if status_filter:
        query = query.filter(Asset.status == status_filter)
    
    data = db.session.query(Department.name, func.sum(Asset.purchase_price)).join(Asset, Asset.department_id == Department.id).filter(Asset.id.in_(query.with_entities(Asset.id))).group_by(Department.name).order_by(Department.name.asc()).all()
    return jsonify({
        'labels': [name for name, _ in data],
        'values': [float(value) if value else 0 for _, value in data]
    })

@bp.route('/api/value-by-location')
@login_required
def value_by_location():
    from app.models.location import Location
    query = Asset.query
    
    # Apply filters
    asset_type = request.args.get('type', '').strip()
    status_filter = request.args.get('status', '').strip()
    date_from = request.args.get('dateFrom', '').strip()
    date_to = request.args.get('dateTo', '').strip()
    

    
    if asset_type:
        query = query.join(AssetType).filter(AssetType.name == asset_type)
    if status_filter:
        query = query.filter(Asset.status == status_filter)
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
    
    data = db.session.query(
        Location.name, 
        func.sum(Asset.purchase_price)
    ).join(Asset, Asset.location_id == Location.id
    ).filter(Asset.id.in_(query.with_entities(Asset.id))
    ).group_by(Location.name).order_by(Location.name.asc()).all()
    
    return jsonify({
        'labels': [name for name, _ in data],
        'values': [float(value) if value else 0 for _, value in data]
    })

@bp.route('/api/assets-by-location')
@login_required
def assets_by_location():
    """Get all assets grouped by location with complete details and pagination per location"""
    from app.models.location import Location
    from app.models.asset_type import AssetType
    from app.models.department import Department
    from app.models.employee import Employee
    
    # Get filter parameters
    location_filter = request.args.get('location', '').strip()
    asset_type_filter = request.args.get('type', '').strip()
    status_filter = request.args.get('status', '').strip()
    department_filter = request.args.get('department', '').strip()
    date_from = request.args.get('dateFrom', '').strip()
    date_to = request.args.get('dateTo', '').strip()
    
    # Get pagination parameters for each location
    page_size = 25  # Assets per page per location
    

    
    # Build the query
    query = db.session.query(
        Asset,
        Location.name.label('location_name'),
        AssetType.name.label('asset_type_name'),
        Department.name.label('department_name'),
        Employee.first_name.label('employee_first'),
        Employee.last_name.label('employee_last')
    ).join(Location, Asset.location_id == Location.id
    ).outerjoin(AssetType, Asset.asset_type_id == AssetType.id
    ).outerjoin(Department, Asset.department_id == Department.id
    ).outerjoin(Employee, Asset.current_employee_id == Employee.id)
    
    # Apply filters
    if location_filter:
        query = query.filter(Location.name == location_filter)
    if asset_type_filter:
        query = query.filter(AssetType.name == asset_type_filter)
    if status_filter:
        query = query.filter(Asset.status == status_filter)
    if department_filter:
        query = query.filter(Department.name == department_filter)
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
    
    # Order by location, then by asset name
    query = query.order_by(Location.name, Asset.name)
    
    assets = query.all()
    
    
    # Group assets by location
    location_assets = {}
    for asset, loc_name, type_name, dept_name, emp_first, emp_last in assets:
        if loc_name not in location_assets:
            location_assets[loc_name] = []
        
        employee_name = f"{emp_first} {emp_last}" if emp_first and emp_last else "Unassigned"
        
        location_assets[loc_name].append({
            'id': asset.id,
            'tag_number': asset.tag_number,
            'name': asset.name,
            'description': asset.description,
            'serial_number': asset.serial_number,
            'model_number': asset.model_number,
            'status': asset.status,
            'purchase_date': asset.purchase_date.isoformat() if asset.purchase_date else None,
            'purchase_price': float(asset.purchase_price) if asset.purchase_price else 0,
            'warranty_expiration': asset.warranty_expiration.isoformat() if asset.warranty_expiration else None,
            'asset_type': type_name or 'Unknown',
            'department': dept_name or 'Unknown',
            'employee': employee_name,
            'created_at': asset.created_at.isoformat() if asset.created_at else None,
            'updated_at': asset.updated_at.isoformat() if asset.updated_at else None,
            'last_audit_date': asset.last_audit_date.isoformat() if asset.last_audit_date else None,
            'last_maintenance_date': asset.last_maintenance_date.isoformat() if asset.last_maintenance_date else None
        })
    
    # Add pagination info for each location
    for location in location_assets:
        total_assets = len(location_assets[location])
        total_pages = (total_assets + page_size - 1) // page_size  # Ceiling division
        
        location_assets[location] = {
            'assets': location_assets[location],
            'pagination': {
                'total_assets': total_assets,
                'total_pages': total_pages,
                'page_size': page_size,
                'current_page': 1  # Default to first page
            }
        }
    
    return jsonify(location_assets)

@bp.route('/api/assets-by-location/<location_name>/page/<int:page>')
@login_required
def assets_by_location_paginated(location_name, page):
    """Get paginated assets for a specific location"""
    from app.models.location import Location
    from app.models.asset_type import AssetType
    from app.models.department import Department
    from app.models.employee import Employee
    
    # Get filter parameters
    asset_type_filter = request.args.get('type', '').strip()
    status_filter = request.args.get('status', '').strip()
    department_filter = request.args.get('department', '').strip()
    date_from = request.args.get('dateFrom', '').strip()
    date_to = request.args.get('dateTo', '').strip()
    
    # Pagination parameters
    page_size = 25
    offset = (page - 1) * page_size
    

    
    # Build the query for the specific location
    query = db.session.query(
        Asset,
        Location.name.label('location_name'),
        AssetType.name.label('asset_type_name'),
        Department.name.label('department_name'),
        Employee.first_name.label('employee_first'),
        Employee.last_name.label('employee_last')
    ).join(Location, Asset.location_id == Location.id
    ).outerjoin(AssetType, Asset.asset_type_id == AssetType.id
    ).outerjoin(Department, Asset.department_id == Department.id
    ).outerjoin(Employee, Asset.current_employee_id == Employee.id
    ).filter(Location.name == location_name)
    
    # Apply filters
    if asset_type_filter:
        query = query.filter(AssetType.name == asset_type_filter)
    if status_filter:
        query = query.filter(Asset.status == status_filter)
    if department_filter:
        query = query.filter(Department.name == department_filter)
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
    
    # Get total count for pagination
    total_assets = query.count()
    total_pages = (total_assets + page_size - 1) // page_size
    
    # Apply pagination
    query = query.order_by(Asset.name).offset(offset).limit(page_size)
    assets = query.all()
    
    # Format assets
    formatted_assets = []
    for asset, loc_name, type_name, dept_name, emp_first, emp_last in assets:
        employee_name = f"{emp_first} {emp_last}" if emp_first and emp_last else "Unassigned"
        
        formatted_assets.append({
            'id': asset.id,
            'tag_number': asset.tag_number,
            'name': asset.name,
            'description': asset.description,
            'serial_number': asset.serial_number,
            'model_number': asset.model_number,
            'status': asset.status,
            'purchase_date': asset.purchase_date.isoformat() if asset.purchase_date else None,
            'purchase_price': float(asset.purchase_price) if asset.purchase_price else 0,
            'warranty_expiration': asset.warranty_expiration.isoformat() if asset.warranty_expiration else None,
            'asset_type': type_name or 'Unknown',
            'department': dept_name or 'Unknown',
            'employee': employee_name,
            'created_at': asset.created_at.isoformat() if asset.created_at else None,
            'updated_at': asset.updated_at.isoformat() if asset.updated_at else None,
            'last_audit_date': asset.last_audit_date.isoformat() if asset.last_audit_date else None,
            'last_maintenance_date': asset.last_maintenance_date.isoformat() if asset.last_maintenance_date else None
        })
    
    return jsonify({
        'assets': formatted_assets,
        'pagination': {
            'current_page': page,
            'total_pages': total_pages,
            'total_assets': total_assets,
            'page_size': page_size,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }
    })

@bp.route('/api/export-assets-by-location')
@login_required
def export_assets_by_location():
    """Export assets by location to Excel file"""
    from app.models.location import Location
    from app.models.asset_type import AssetType
    from app.models.department import Department
    from app.models.employee import Employee
    
    # Get filter parameters
    location_filter = request.args.get('location', '').strip()
    asset_type_filter = request.args.get('type', '').strip()
    status_filter = request.args.get('status', '').strip()
    department_filter = request.args.get('department', '').strip()
    date_from = request.args.get('dateFrom', '').strip()
    date_to = request.args.get('dateTo', '').strip()
    

    
    # Build the query (same as assets_by_location)
    query = db.session.query(
        Asset,
        Location.name.label('location_name'),
        AssetType.name.label('asset_type_name'),
        Department.name.label('department_name'),
        Employee.first_name.label('employee_first'),
        Employee.last_name.label('employee_last')
    ).join(Location, Asset.location_id == Location.id
    ).outerjoin(AssetType, Asset.asset_type_id == AssetType.id
    ).outerjoin(Department, Asset.department_id == Department.id
    ).outerjoin(Employee, Asset.current_employee_id == Employee.id)
    
    # Apply filters
    if location_filter:
        query = query.filter(Location.name == location_filter)
    if asset_type_filter:
        query = query.filter(AssetType.name == asset_type_filter)
    if status_filter:
        query = query.filter(Asset.status == status_filter)
    if department_filter:
        query = query.filter(Department.name == department_filter)
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
    
    # Order by location, then by asset name
    query = query.order_by(Location.name, Asset.name)
    
    assets = query.all()
    
    # Prepare data for Excel
    excel_data = []
    for asset, loc_name, type_name, dept_name, emp_first, emp_last in assets:
        employee_name = f"{emp_first} {emp_last}" if emp_first and emp_last else "Unassigned"
        
        excel_data.append({
            'Location': loc_name,
            'Asset ID': asset.id,
            'Tag Number': asset.tag_number,
            'Name': asset.name,
            'Description': asset.description or '',
            'Serial Number': asset.serial_number or '',
            'Model Number': asset.model_number or '',
            'Asset Type': type_name or 'Unknown',
            'Status': asset.status,
            'Department': dept_name or 'Unknown',
            'Assigned Employee': employee_name,
            'Purchase Price': float(asset.purchase_price) if asset.purchase_price else 0,
            'Purchase Date': asset.purchase_date.strftime('%Y-%m-%d') if asset.purchase_date else '',
            'Warranty Expiration': asset.warranty_expiration.strftime('%Y-%m-%d') if asset.warranty_expiration else '',
            'Last Audit Date': asset.last_audit_date.strftime('%Y-%m-%d') if asset.last_audit_date else '',
            'Last Maintenance Date': asset.last_maintenance_date.strftime('%Y-%m-%d') if asset.last_maintenance_date else '',
            'Created At': asset.created_at.strftime('%Y-%m-%d %H:%M:%S') if asset.created_at else '',
            'Updated At': asset.updated_at.strftime('%Y-%m-%d %H:%M:%S') if asset.updated_at else ''
        })
    
    # Create DataFrame
    df = pd.DataFrame(excel_data)
    
    # Create Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Assets by Location', index=False)
        
        # Auto-adjust column widths
        worksheet = writer.sheets['Assets by Location']
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
    
    output.seek(0)
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'assets_by_location_{timestamp}.xlsx'
    
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@bp.route('/api/export-disposed-assets')
@login_required
def export_disposed_assets():
    """Export disposed assets to Excel file"""
    from app.models.department import Department
    from app.models.location import Location
    from app.models.asset_type import AssetType
    
    # Get and sanitize filter parameters
    search = sanitize_search_term(request.args.get('search', ''))
    department = sanitize_filter_value(request.args.get('department', ''))
    location = sanitize_filter_value(request.args.get('location', ''))
    asset_type = sanitize_filter_value(request.args.get('type', ''))
    date_from = validate_date_string(request.args.get('dateFrom', ''))
    date_to = validate_date_string(request.args.get('dateTo', ''))
    
    # Build the query for disposed assets
    query = db.session.query(
        Asset,
        Location.name.label('location_name'),
        AssetType.name.label('asset_type_name'),
        Department.name.label('department_name')
    ).filter(Asset.status == 'Disposed'
    ).join(Location, Asset.location_id == Location.id
    ).outerjoin(AssetType, Asset.asset_type_id == AssetType.id
    ).outerjoin(Department, Asset.department_id == Department.id)
    
    # Apply filters with safe parameterized queries
    if search:
        # Use safe parameterized queries
        query = query.filter((Asset.name.ilike(f"%{search}%")) | (Asset.tag_number.ilike(f"%{search}%")))
    if department:
        query = query.filter(Department.name == department)
    if location:
        query = query.filter(Location.name == location)
    if asset_type:
        query = query.filter(AssetType.name == asset_type)
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(Asset.updated_at >= dt_from)
        except Exception:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(Asset.updated_at <= dt_to)
        except Exception:
            pass
    
    assets = query.order_by(Asset.updated_at.desc()).all()
    
    # Prepare data for Excel
    excel_data = []
    for asset, loc_name, type_name, dept_name in assets:
        excel_data.append({
            'Asset ID': asset.id,
            'Tag Number': asset.tag_number,
            'Name': asset.name,
            'Description': asset.description or '',
            'Serial Number': asset.serial_number or '',
            'Model Number': asset.model_number or '',
            'Asset Type': type_name or 'Unknown',
            'Location': loc_name or 'Unknown',
            'Department': dept_name or 'Unknown',
            'Purchase Price': float(asset.purchase_price) if asset.purchase_price else 0,
            'Purchase Date': asset.purchase_date.strftime('%Y-%m-%d') if asset.purchase_date else '',
            'Warranty Expiration': asset.warranty_expiration.strftime('%Y-%m-%d') if asset.warranty_expiration else '',
            'Disposed On': asset.updated_at.strftime('%Y-%m-%d %H:%M:%S') if asset.updated_at else '',
            'Created At': asset.created_at.strftime('%Y-%m-%d %H:%M:%S') if asset.created_at else ''
        })
    
    # Create DataFrame
    df = pd.DataFrame(excel_data)
    
    # Create Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Disposed Assets', index=False)
        
        # Auto-adjust column widths
        worksheet = writer.sheets['Disposed Assets']
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
    
    output.seek(0)
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'disposed_assets_{timestamp}.xlsx'
    
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )



# Add your reports routes here 