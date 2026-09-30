import re

import pyotp

from app import db
from app.models.audit import AuditEvent
from app.models.user import User

from tests.conftest import login


def _password(client):
    return client.post(
        '/auth/login',
        data={'username': 'admin', 'password': 'secret'},
        follow_redirects=True,
    )


def _secret_from(page):
    match = re.search(br'id="mfa-secret">([^<]+)', page.data)
    assert match, page.data[:300]
    return match.group(1).decode()


def test_admin_password_stops_at_authenticator_setup(client, app, admin):
    page = _password(client)
    assert b'Set up two-factor authentication' in page.data
    assert b'Overview' not in page.data
    with app.app_context():
        user = db.session.get(User, admin)
        assert not user.mfa_enabled
        assert user.totp_secret is None


def test_wrong_setup_code_does_not_enroll(client, app, admin):
    _password(client)
    rejected = client.post('/auth/mfa/setup', data={'code': '000000'})
    assert b'not valid' in rejected.data
    with app.app_context():
        assert db.session.get(User, admin).mfa_enabled is not True


def test_setup_then_code_and_recovery_code(client, app, admin):
    page = _password(client)
    secret = _secret_from(page)
    enrolled = client.post('/auth/mfa/setup', data={'code': pyotp.TOTP(secret).now()})
    assert b'Save your recovery codes' in enrolled.data
    recovery = re.findall(br'class="recovery-code">([^<]+)', enrolled.data)
    assert len(recovery) == 8
    home = client.get('/')
    assert b'Overview' in home.data

    client.get('/auth/logout', follow_redirects=True)
    again = _password(client)
    assert b'Authentication code' in again.data
    assert b'Set up two-factor' not in again.data
    rejected = client.post('/auth/mfa/verify', data={'code': '000000'})
    assert b'not valid' in rejected.data
    accepted = client.post(
        '/auth/mfa/verify',
        data={'code': pyotp.TOTP(secret).now()},
        follow_redirects=True,
    )
    assert b'Overview' in accepted.data

    client.get('/auth/logout', follow_redirects=True)
    _password(client)
    used = client.post(
        '/auth/mfa/verify',
        data={'code': recovery[0].decode()},
        follow_redirects=True,
    )
    assert b'Overview' in used.data
    client.get('/auth/logout', follow_redirects=True)
    _password(client)
    reused = client.post('/auth/mfa/verify', data={'code': recovery[0].decode()})
    assert b'not valid' in reused.data
    with app.app_context():
        used = AuditEvent.query.filter_by(event='recovery_code_used').one()
        assert used.username == 'admin'
        assert recovery[0].decode() not in (used.detail or '')


def test_regular_user_skips_mfa(client, app):
    with app.app_context():
        user = User(username='clerk', email='clerk@example.com', is_super_admin=False, active=True)
        user.set_password('secret')
        db.session.add(user)
        db.session.commit()
    response = login(client, 'clerk', 'secret')
    assert b'Overview' in response.data
    assert b'Set up two-factor' not in response.data


def test_signed_in_admin_can_finish_setup(client, app, admin):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin)
        sess['_fresh'] = True
    page = client.get('/auth/mfa/setup')
    secret = _secret_from(page)
    enrolled = client.post('/auth/mfa/setup', data={'code': pyotp.TOTP(secret).now()})
    assert enrolled.status_code == 200
    assert b'Save your recovery codes' in enrolled.data
    home = client.get('/')
    assert b'Overview' in home.data


def test_existing_admin_session_must_enroll(client, admin):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin)
        sess['_fresh'] = True
    home = client.get('/')
    assert home.status_code == 302
    assert '/auth/mfa/setup' in home.headers['Location']


def test_repeated_bad_codes_lock_the_admin(client, app, admin):
    app.config['MAX_LOGIN_ATTEMPTS_BEFORE_PROGRESSIVE_LOCKOUT'] = 3
    _password(client)
    last = None
    for _ in range(3):
        last = client.post('/auth/mfa/setup', data={'code': '000000'}, follow_redirects=True)
    assert b'Account locked' in last.data
    locked = client.post('/auth/login', data={'username': 'admin', 'password': 'secret'})
    assert b'Account is locked' in locked.data


def test_profile_can_replace_the_authenticator(client, app, admin):
    login(client)
    profile = client.get('/administration/profile')
    assert b'Set up a new authenticator' in profile.data
    with app.app_context():
        secret = db.session.get(User, admin).totp_secret
    reset = client.post(
        '/auth/mfa/reset',
        data={'password': 'secret', 'code': pyotp.TOTP(secret).now()},
        follow_redirects=True,
    )
    assert b'Set up two-factor authentication' in reset.data
    with app.app_context():
        user = db.session.get(User, admin)
        assert not user.mfa_enabled
