import os
import re
import tempfile

import pyotp
import pytest

from app import create_app, db
from app.models.asset import Asset
from app.models.asset_type import AssetType
from app.models.department import Department
from app.models.employee import Employee
from app.models.location import Location
from app.models.manufacturer import Manufacturer
from app.models.user import User


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.auth import _RATE_HITS as auth_hits
    from app.search import _RATE_HITS as search_hits
    from app.tag_number import _RATE_HITS as tag_hits

    auth_hits.clear()
    search_hits.clear()
    tag_hits.clear()
    yield
    auth_hits.clear()
    search_hits.clear()
    tag_hits.clear()


@pytest.fixture
def app():
    handle, path = tempfile.mkstemp(suffix='.sqlite')
    os.close(handle)
    application = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + path,
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret',
    })
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    os.remove(path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(app):
    with app.app_context():
        user = User(
            username='admin',
            email='admin@example.com',
            is_super_admin=True,
            active=True,
        )
        user.set_password('secret')
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def catalog(app):
    with app.app_context():
        location = Location(name='Headquarters', code='HQ', is_active=True)
        department = Department(name='Information Technology', code='IT', budget=1000)
        asset_type = AssetType(name='Laptop', description='Portable computer')
        manufacturer = Manufacturer(name='Dell', is_active=True)
        db.session.add_all([location, department, asset_type, manufacturer])
        db.session.flush()
        employee = Employee(
            employee_id='E1001',
            username='jdoe',
            email='jane.doe@example.com',
            first_name='Jane',
            last_name='Doe',
            department_id=department.id,
            location_id=location.id,
            is_active=True,
        )
        asset = Asset(
            tag_number='BHSN-T0000001',
            name='Laptop',
            serial_number='SN-1001',
            status='Available',
            asset_type_id=asset_type.id,
            location_id=location.id,
            department_id=department.id,
            manufacturer_id=manufacturer.id,
            purchase_price=1200,
        )
        db.session.add_all([employee, asset])
        db.session.commit()
        return {
            'location_id': location.id,
            'department_id': department.id,
            'asset_type_id': asset_type.id,
            'manufacturer_id': manufacturer.id,
            'employee_id': employee.id,
            'asset_id': asset.id,
        }


def login(client, username='admin', password='secret'):
    """Sign in, completing authenticator setup or the code prompt for super admins."""
    response = client.post(
        '/auth/login',
        data={'username': username, 'password': password},
        follow_redirects=True,
    )
    secret_match = re.search(br'id="mfa-secret">([^<]+)', response.data)
    if secret_match:
        code = pyotp.TOTP(secret_match.group(1).decode()).now()
        response = client.post('/auth/mfa/setup', data={'code': code}, follow_redirects=True)
    if b'Save your recovery codes' in response.data:
        response = client.get('/', follow_redirects=True)
    elif b'Authentication code' in response.data and b'id="mfa-secret"' not in response.data:
        with client.application.app_context():
            user = User.query.filter_by(username=username).first()
            code = pyotp.TOTP(user.totp_secret).now()
        response = client.post('/auth/mfa/verify', data={'code': code}, follow_redirects=True)
    return response
