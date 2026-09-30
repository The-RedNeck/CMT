"""Local demo records so the application can be clicked through after a fresh start."""

import os
from datetime import date

from app import db
from app.models.asset import Asset
from app.models.asset_type import AssetType
from app.models.department import Department
from app.models.employee import Employee
from app.models.location import Location
from app.models.manufacturer import Manufacturer
from app.models.user import User


def seed_demo_data():
    if os.environ.get('CMT_DISABLE_DEMO_SEED', '').strip().lower() in ('1', 'true', 'yes'):
        return
    if User.query.first():
        return

    admin = User(
        username='admin',
        email='admin@example.com',
        is_super_admin=True,
        active=True,
    )
    admin.set_password('admin123')
    db.session.add(admin)

    location = Location(name='Headquarters', code='HQ', description='Main office', is_active=True)
    department = Department(name='Information Technology', code='IT', description='IT department', budget=50000)
    asset_type = AssetType(name='Laptop', description='Portable computer')
    manufacturer = Manufacturer(name='Dell', description='Dell Technologies', is_active=True)
    db.session.add_all([location, department, asset_type, manufacturer])
    db.session.flush()

    employee = Employee(
        employee_id='E1001',
        username='jdoe',
        email='jane.doe@example.com',
        first_name='Jane',
        last_name='Doe',
        title='Analyst',
        department_id=department.id,
        location_id=location.id,
        phone='555-0100',
        is_active=True,
    )
    db.session.add(employee)
    db.session.flush()

    available = Asset(
        tag_number='BHSN-T0000001',
        name='Laptop',
        serial_number='SN-1001',
        status='Available',
        asset_type_id=asset_type.id,
        location_id=location.id,
        department_id=department.id,
        manufacturer_id=manufacturer.id,
        purchase_price=1200,
        purchase_date=date(2024, 6, 1),
    )
    checked_out = Asset(
        tag_number='BHSN-T0000002',
        name='Laptop',
        serial_number='SN-1002',
        status='Checked Out',
        asset_type_id=asset_type.id,
        location_id=location.id,
        department_id=department.id,
        manufacturer_id=manufacturer.id,
        current_employee_id=employee.id,
        purchase_price=1400,
        purchase_date=date(2024, 7, 1),
    )
    db.session.add_all([available, checked_out])
    db.session.commit()
