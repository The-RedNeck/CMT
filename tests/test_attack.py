import urllib.parse

from app import db
from app.attack import sync_enterprise_attack
from app.models.attack import AttackSync, AttackTechnique

from tests.conftest import login


def _object(stix_id, external_id, name, **extra):
    body = {
        'id': stix_id,
        'name': name,
        'description': extra.get('description', 'A technique description.'),
        'modified': extra.get('modified', '2026-08-01T00:00:00.000Z'),
        'revoked': extra.get('revoked', False),
        'x_mitre_deprecated': extra.get('deprecated', False),
        'x_mitre_is_subtechnique': extra.get('is_subtechnique', False),
        'x_mitre_version': extra.get('version', '1.0'),
        'kill_chain_phases': [{'phase_name': extra.get('tactic', 'credential-access')}],
        'external_references': [{
            'source_name': 'mitre-attack',
            'external_id': external_id,
            'url': f'https://attack.mitre.org/techniques/{external_id}',
        }],
    }
    return body


def _fake_feed(calls):
    def get(url):
        calls.append(url)
        match = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get('match[type]', [''])[0]
        cursor = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get('next', [None])[0]
        if match == 'x-mitre-collection':
            return {'objects': [{'x_mitre_version': '19.2', 'modified': '2026-08-05T14:26:46.746Z', 'name': 'Enterprise ATT&CK'}]}
        if match == 'x-mitre-tactic':
            return {'more': False, 'objects': [_object(
                'x-mitre-tactic--1', 'TA0006', 'Credential Access', tactic='credential-access',
            ) | {'x_mitre_shortname': 'credential-access'}]}
        if cursor == '1':
            return {'more': False, 'objects': [_object(
                'attack-pattern--2', 'T1110.001', 'Password Guessing', is_subtechnique=True,
            )]}
        return {'more': True, 'next': '1', 'objects': [
            _object('attack-pattern--1', 'T1110', 'Old Brute', modified='2020-01-01T00:00:00.000Z'),
            _object('attack-pattern--1', 'T1110', 'Brute Force'),
        ]}
    return get


def test_sync_stores_enterprise_objects_and_a_failed_refresh_keeps_them(app):
    calls = []
    with app.app_context():
        state = sync_enterprise_attack(_fake_feed(calls))
        assert state.attack_version == '19.2'
        assert state.technique_count == 2
        assert state.tactic_count == 1
        stored = AttackTechnique.query.filter_by(external_id='T1110').one()
        assert stored.name == 'Brute Force'
        assert stored.url.startswith('https://attack.mitre.org/techniques/T1110')

        def broken(_url):
            raise RuntimeError('offline')

        try:
            sync_enterprise_attack(broken)
        except RuntimeError:
            pass
        else:
            raise AssertionError('a broken feed should not look successful')
        assert db.session.get(AttackSync, 1).technique_count == 2
        assert AttackTechnique.query.count() == 2


def test_super_admin_sees_gaps_and_can_refresh(client, admin):
    calls = []
    from app import attack as attack_module
    original = attack_module.taxii_get
    attack_module.taxii_get = _fake_feed(calls)
    try:
        login(client)
        page = client.get('/administration/attack/')
        assert page.status_code == 200
        assert b'Open gaps' in page.data
        assert b'T1078.001' in page.data
        assert b'not a promise' in page.data
        refreshed = client.post('/administration/attack/sync', follow_redirects=True)
        assert b'Enterprise ATT&CK 19.2' in refreshed.data
        assert b'Brute Force' in refreshed.data
        found = client.get('/administration/attack/?q=T1110.001')
        assert b'Password Guessing' in found.data
        assert b'T1110.001' in found.data
    finally:
        attack_module.taxii_get = original


def test_regular_user_cannot_open_attack(client, app):
    from app.models.user import User
    with app.app_context():
        user = User(username='clerk', email='clerk@example.com', is_super_admin=False, active=True)
        user.set_password('secret')
        db.session.add(user)
        db.session.commit()
    login(client, 'clerk', 'secret')
    response = client.get('/administration/attack/', follow_redirects=True)
    assert b'Access denied' in response.data


def test_new_password_must_be_12_characters(client, admin):
    login(client)
    rejected = client.post('/administration/users/create', data={
        'username': 'shortpw',
        'email': 'short@example.com',
        'password': 'short-pass',
        'confirm': 'short-pass',
    })
    assert b'at least 12' in rejected.data
    accepted = client.post('/administration/users/create', data={
        'username': 'longpw',
        'email': 'long@example.com',
        'password': 'a-long-password',
        'confirm': 'a-long-password',
    }, follow_redirects=True)
    assert b'User created successfully' in accepted.data
