import importlib.util
import sqlite3
from datetime import timedelta

from app import create_app, db
from app.models.audit import AuditEvent
from app.models.user import User

from tests.conftest import login


def test_production_session_cookies_are_secure(tmp_path, monkeypatch):
    monkeypatch.setenv('CMT_DISABLE_DEMO_SEED', '1')
    monkeypatch.delenv('CMT_DEV_HTTP', raising=False)
    application = create_app({
        'TESTING': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(tmp_path / 'prod.sqlite'),
        'SECRET_KEY': 'prod-secret',
    })
    assert application.config['SESSION_COOKIE_SECURE'] is True
    assert application.config['SESSION_COOKIE_HTTPONLY'] is True
    assert application.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
    assert application.config['REMEMBER_COOKIE_SECURE'] is True
    assert application.config['PERMANENT_SESSION_LIFETIME'] == timedelta(hours=2)
    assert application.config['REMEMBER_COOKIE_DURATION'] == timedelta(hours=2)
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


def test_https_is_required_when_cookies_are_secure(tmp_path):
    application = create_app({
        'TESTING': True,
        'SESSION_COOKIE_SECURE': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(tmp_path / 'https.sqlite'),
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret',
    })
    client = application.test_client()
    health = client.get('/health')
    assert health.status_code == 200
    page = client.get('/auth/login')
    assert page.status_code == 301
    assert page.headers['Location'].startswith('https://')
    posted = client.post('/auth/login', data={'username': 'admin', 'password': 'secret'})
    assert posted.status_code == 400
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


def test_login_rotates_the_session_and_writes_an_audit_row(client, app, admin):
    with client.session_transaction() as sess:
        sess['planted'] = 'yes'
    failed = client.post('/auth/login', data={'username': 'admin', 'password': 'wrong'})
    assert b'Invalid username or password' in failed.data
    with app.app_context():
        failure = AuditEvent.query.filter_by(event='login_failure').one()
        assert failure.username == 'admin'
        assert 'secret' not in (failure.detail or '')

    response = login(client)
    assert b'Overview' in response.data
    with client.session_transaction() as sess:
        assert 'planted' not in sess
        assert sess.get('_user_id')
        assert sess.get('_id')
    with app.app_context():
        assert AuditEvent.query.filter_by(event='login_success', username='admin').count() == 1


def test_delete_requires_a_fresh_password(client, app, admin):
    with app.app_context():
        other = User(username='other', email='other@example.com', is_super_admin=False, active=True)
        other.set_password('secret')
        db.session.add(other)
        db.session.commit()
        other_id = other.id
    login(client)
    blocked = client.post(f'/administration/users/{other_id}/delete', follow_redirects=True)
    assert b'Enter your password again' in blocked.data
    with app.app_context():
        assert db.session.get(User, other_id) is not None
    confirmed = client.post('/administration/confirm-password', data={'password': 'secret'})
    assert confirmed.status_code == 302
    deleted = client.post(f'/administration/users/{other_id}/delete', follow_redirects=True)
    assert b'User deleted successfully' in deleted.data
    with app.app_context():
        assert db.session.get(User, other_id) is None


def test_backup_refuses_a_plaintext_copy(tmp_path, monkeypatch):
    database = tmp_path / 'cmt.db'
    sqlite3.connect(database).close()
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(database))
    monkeypatch.delenv('AGE_RECIPIENT', raising=False)
    monkeypatch.delenv('GPG_RECIPIENT', raising=False)
    spec = importlib.util.spec_from_file_location('backup_db', 'scripts/backup_db.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code, message = module.backup(str(tmp_path / 'out'))
    assert code == 1
    assert 'AGE_RECIPIENT' in message
    assert list((tmp_path / 'out').iterdir()) == []
