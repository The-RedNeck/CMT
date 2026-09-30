import json

from werkzeug.security import generate_password_hash

from app import db
from app.mfa import consume_recovery_code, new_recovery_codes
from app.models.employee import Employee
from app.models.user import User
from app.passwords import DEFAULT_PASSWORD_METHOD, password_method


def test_production_default_is_strong_scrypt():
    assert DEFAULT_PASSWORD_METHOD == 'scrypt:131072:8:1'


def test_login_rewrites_an_older_password_hash(client, app, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        user.password_hash = generate_password_hash('secret', method='scrypt:16384:8:1')
        db.session.commit()
        assert user.password_hash.startswith('scrypt:16384:8:1$')

    response = client.post('/auth/login', data={'username': 'admin', 'password': 'secret'})
    assert response.status_code == 302

    with app.app_context():
        user = db.session.get(User, admin)
        assert user.password_hash.startswith(password_method() + '$')
        assert user.check_password('secret')
        assert not user.check_password('wrong')


def test_failed_login_leaves_the_old_hash(client, app, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        old = generate_password_hash('secret', method='scrypt:16384:8:1')
        user.password_hash = old
        db.session.commit()

    client.post('/auth/login', data={'username': 'admin', 'password': 'wrong'})

    with app.app_context():
        user = db.session.get(User, admin)
        assert user.password_hash == old


def test_employee_password_upgrades_on_check(app):
    with app.app_context():
        employee = Employee(
            employee_id='E2002',
            username='alex',
            email='alex@example.com',
            is_active=True,
        )
        employee.password_hash = generate_password_hash('secret', method='scrypt:16384:8:1')
        db.session.add(employee)
        db.session.commit()
        assert employee.check_password('secret')
        assert employee.password_hash.startswith(password_method() + '$')


def test_new_recovery_codes_are_80_bits():
    codes = new_recovery_codes()
    assert len(codes) == 8
    normalized = [code.replace('-', '') for code in codes]
    assert len(set(normalized)) == 8
    assert all(len(code) == 20 for code in normalized)


def test_previously_issued_short_recovery_code_still_works(app, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        user.mfa_recovery_hashes = json.dumps([
            generate_password_hash('AB12CD34', method='scrypt:32768:8:1'),
        ])
        db.session.commit()
        assert consume_recovery_code(user, 'AB12-CD34') is True
        db.session.commit()
        assert consume_recovery_code(user, 'AB12-CD34') is False
