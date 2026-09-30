from app import db
from app.models.user import User

from tests.conftest import login


def test_login_page_and_home_requires_auth(client):
    home = client.get('/')
    assert home.status_code == 302
    assert '/auth/login' in home.headers['Location']
    page = client.get('/auth/login')
    assert page.status_code == 200
    assert b'Sign in' in page.data


def test_successful_login(client, admin):
    response = login(client)
    assert response.status_code == 200
    assert b'Overview' in response.data


def test_bad_password_and_lockout(client, app, admin):
    app.config['MAX_LOGIN_ATTEMPTS_BEFORE_PROGRESSIVE_LOCKOUT'] = 3
    for _ in range(2):
        response = client.post('/auth/login', data={'username': 'admin', 'password': 'wrong'})
        assert b'Invalid username or password' in response.data
    locked = client.post('/auth/login', data={'username': 'admin', 'password': 'wrong'})
    assert b'Account locked' in locked.data
    with app.app_context():
        user = db.session.get(User, admin)
        assert user.locked_until is not None
        assert user.failed_logins == 3


def test_deactivated_account(client, app, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        user.active = False
        db.session.commit()
    response = client.post('/auth/login', data={'username': 'admin', 'password': 'secret'})
    assert b'deactivated' in response.data


def test_login_rate_limit(client, admin):
    last = None
    for _ in range(31):
        last = client.post('/auth/login', data={'username': 'admin', 'password': 'wrong'})
    assert last.status_code == 200
    assert b'Too many login attempts' in last.data


def test_logout(client, admin):
    login(client)
    response = client.get('/auth/logout', follow_redirects=True)
    assert b'Sign in' in response.data


def test_regular_user_cannot_open_user_admin(client, app):
    with app.app_context():
        user = User(username='clerk', email='clerk@example.com', is_super_admin=False, active=True)
        user.set_password('secret')
        db.session.add(user)
        db.session.commit()
    login(client, 'clerk', 'secret')
    response = client.get('/administration/users', follow_redirects=True)
    assert b'Access denied' in response.data


def test_admin_cannot_delete_self(client, admin):
    login(client)
    response = client.post(f'/administration/users/{admin}/delete', follow_redirects=True)
    assert b'Cannot delete your own account' in response.data
    with client.application.app_context():
        assert db.session.get(User, admin) is not None
