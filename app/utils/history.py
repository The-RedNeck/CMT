"""Audit-trail writers used by asset and employee changes."""

from flask import request

from app import db


def get_client_ip():
    """Client address. X-Forwarded-For is used only when a trusted proxy is configured."""
    from flask import current_app

    if current_app and current_app.config.get('TRUST_PROXY'):
        forwarded = request.headers.get('X-Forwarded-For')
        if forwarded:
            return forwarded.split(',')[0].strip()[:64]
    return (request.remote_addr or 'unknown')[:64]


def log_asset_history(asset, action, changed_by=None):
    from app.models.asset import AssetHistory

    record = AssetHistory(
        asset_id=asset.id,
        tag_number=asset.tag_number,
        name=asset.name,
        description=asset.description,
        serial_number=asset.serial_number,
        model_number=asset.model_number,
        purchase_date=asset.purchase_date,
        purchase_price=asset.purchase_price,
        warranty_expiration=asset.warranty_expiration,
        status=asset.status,
        asset_type_id=asset.asset_type_id,
        manufacturer_id=asset.manufacturer_id,
        location_id=asset.location_id,
        department_id=asset.department_id,
        current_employee_id=asset.current_employee_id,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        last_audit_date=asset.last_audit_date,
        last_maintenance_date=asset.last_maintenance_date,
        action=action,
        changed_by=changed_by,
        ip_address=get_client_ip(),
    )
    db.session.add(record)
    return record


def log_employee_history(employee, action, changed_by=None):
    from app.models.employee import EmployeeHistory

    record = EmployeeHistory(
        employee_id=employee.id,
        username=employee.username,
        email=employee.email,
        first_name=employee.first_name,
        last_name=employee.last_name,
        title=employee.title,
        department_id=employee.department_id,
        location_id=employee.location_id,
        phone=employee.phone,
        mobile=employee.mobile,
        is_active=employee.is_active,
        is_admin=employee.is_admin,
        hire_date=employee.hire_date,
        termination_date=employee.termination_date,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
        last_login=employee.last_login,
        action=action,
        changed_by=changed_by,
        ip_address=get_client_ip(),
    )
    db.session.add(record)
    return record
