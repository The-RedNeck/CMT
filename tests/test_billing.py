import json
from datetime import timedelta

from app import db
from app.billing import ensure_subscription_columns
from app.models.user import User, _utcnow

from tests.conftest import login


def _expire(app, user_id):
    with app.app_context():
        user = db.session.get(User, user_id)
        user.trial_ends_at = _utcnow() - timedelta(days=1)
        user.subscription_status = None
        db.session.commit()


def test_new_account_starts_in_trial(app, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        assert user.in_trial
        assert user.has_access
        remaining = user.trial_ends_at - _utcnow()
        assert timedelta(days=89) < remaining <= timedelta(days=90)


def test_null_trial_is_backfilled(app, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        user.trial_ends_at = None
        db.session.commit()
        ensure_subscription_columns()
        db.session.expire(user)
        user = db.session.get(User, admin)
        assert user.in_trial
        remaining = user.trial_ends_at - _utcnow()
        assert timedelta(days=89) < remaining <= timedelta(days=90)


def test_missing_billing_columns_are_added(app, admin):
    with app.app_context():
        db.session.execute(db.text('ALTER TABLE users DROP COLUMN trial_ends_at'))
        db.session.commit()
        ensure_subscription_columns()
        user = db.session.get(User, admin)
        assert user.trial_ends_at is not None
        assert user.in_trial


def test_expired_trial_blocks_the_app(client, app, admin):
    _expire(app, admin)
    login(client)
    home = client.get('/')
    assert home.status_code == 302
    assert '/billing/pricing' in home.headers['Location']
    page = client.get('/asset-management/new', follow_redirects=True)
    assert b'free trial has ended' in page.data
    assert b'Subscription' in page.data


def test_active_subscription_keeps_access_after_trial(client, app, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        user.trial_ends_at = _utcnow() - timedelta(days=1)
        user.subscription_status = 'active'
        db.session.commit()
    login(client)
    response = client.get('/')
    assert response.status_code == 200
    assert b'Overview' in response.data


def test_past_due_does_not_keep_access(app, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        user.trial_ends_at = _utcnow() - timedelta(days=1)
        user.subscription_status = 'past_due'
        db.session.commit()
        db.session.expire(user)
        user = db.session.get(User, admin)
        assert user.has_access is False


def test_trial_banner_appears_in_the_last_week(client, app, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        user.trial_ends_at = _utcnow() + timedelta(days=3)
        db.session.commit()
    login(client)
    page = client.get('/')
    assert b'free trial ends on' in page.data


def test_fresh_trial_pricing_page(client, admin):
    login(client)
    home = client.get('/')
    assert b'free trial ends on' not in home.data
    pricing = client.get('/billing/pricing')
    assert b'free trial runs until' in pricing.data
    assert pricing.status_code == 200


def _paypal_keys(monkeypatch):
    monkeypatch.setenv('PAYPAL_CLIENT_ID', 'client')
    monkeypatch.setenv('PAYPAL_CLIENT_SECRET', 'secret')
    monkeypatch.setenv('PAYPAL_PLAN_ID', 'P-PLAN')
    monkeypatch.setenv('PAYPAL_WEBHOOK_ID', 'WH-1')


def test_checkout_without_keys_stays_on_pricing(client, admin, monkeypatch):
    monkeypatch.delenv('PAYPAL_CLIENT_ID', raising=False)
    monkeypatch.delenv('PAYPAL_CLIENT_SECRET', raising=False)
    monkeypatch.delenv('PAYPAL_PLAN_ID', raising=False)
    login(client)
    response = client.post('/billing/checkout', follow_redirects=True)
    assert b'not configured' in response.data


def test_checkout_redirects_to_paypal(client, app, admin, monkeypatch):
    from app import billing

    _paypal_keys(monkeypatch)

    def fake_request(method, path, payload=None):
        assert method == 'POST'
        assert path == '/v1/billing/subscriptions'
        assert payload['plan_id'] == 'P-PLAN'
        assert payload['custom_id'] == str(admin)
        assert payload['subscriber']['email_address'] == 'admin@example.com'
        return {
            'id': 'I-SUB123',
            'status': 'APPROVAL_PENDING',
            'links': [{'rel': 'approve', 'href': 'https://www.sandbox.paypal.com/agreements/approve?token=1'}],
        }

    monkeypatch.setattr(billing, 'paypal_request', fake_request)
    login(client)
    response = client.post('/billing/checkout')
    assert response.status_code == 303
    assert response.headers['Location'] == 'https://www.sandbox.paypal.com/agreements/approve?token=1'
    with app.app_context():
        user = db.session.get(User, admin)
        assert user.paypal_subscription_id == 'I-SUB123'
        assert user.subscription_status is None


def test_portal_requires_a_subscription(client, app, admin):
    login(client)
    response = client.post('/billing/portal', follow_redirects=True)
    assert b'Subscribe before managing billing' in response.data
    with app.app_context():
        user = db.session.get(User, admin)
        user.paypal_subscription_id = 'I-SUB123'
        db.session.commit()
    manage = client.post('/billing/portal')
    assert manage.status_code == 303
    assert manage.headers['Location'] == 'https://www.sandbox.paypal.com/myaccount/autopay/'


def test_success_page_does_not_grant_access(client, app, admin):
    _expire(app, admin)
    login(client)
    page = client.get('/billing/success')
    assert b'confirming the subscription' in page.data
    home = client.get('/')
    assert '/billing/pricing' in home.headers['Location']
    with app.app_context():
        user = db.session.get(User, admin)
        assert user.subscription_status is None


def _post_event(client, event):
    return client.post(
        '/paypal/webhook',
        data=json.dumps(event),
        headers={
            'Content-Type': 'application/json',
            'Paypal-Transmission-Id': 'tx',
            'Paypal-Transmission-Time': '2026-10-16T00:00:00Z',
            'Paypal-Transmission-Sig': 'sig',
            'Paypal-Cert-Url': 'https://api.paypal.com/cert.pem',
            'Paypal-Auth-Algo': 'SHA256withRSA',
        },
    )


def test_webhook_sets_status_and_ignores_unknown_accounts(client, app, admin, monkeypatch):
    from app import billing

    _paypal_keys(monkeypatch)
    monkeypatch.setattr(billing, 'verify_webhook', lambda event: True)
    response = _post_event(client, {
        'event_type': 'BILLING.SUBSCRIPTION.ACTIVATED',
        'resource': {'id': 'I-SUB123', 'custom_id': str(admin), 'status': 'ACTIVE'},
    })
    assert response.status_code == 200
    with app.app_context():
        user = db.session.get(User, admin)
        assert user.subscription_status == 'active'
        assert user.paypal_subscription_id == 'I-SUB123'

    ignored = _post_event(client, {
        'event_type': 'BILLING.SUBSCRIPTION.CANCELLED',
        'resource': {'id': 'I-MISSING', 'custom_id': '999999', 'status': 'CANCELLED'},
    })
    assert ignored.status_code == 200
    with app.app_context():
        assert db.session.get(User, admin).subscription_status == 'active'


def test_webhook_maps_cancelled_and_ignores_other_events(client, app, admin, monkeypatch):
    from app import billing

    _paypal_keys(monkeypatch)
    monkeypatch.setattr(billing, 'verify_webhook', lambda event: True)
    _expire(app, admin)
    with app.app_context():
        user = db.session.get(User, admin)
        user.paypal_subscription_id = 'I-SUB123'
        user.subscription_status = 'active'
        db.session.commit()
    other = _post_event(client, {
        'event_type': 'PAYMENT.SALE.COMPLETED',
        'resource': {'id': 'I-SUB123', 'custom_id': str(admin), 'status': 'CANCELLED'},
    })
    assert other.status_code == 200
    with app.app_context():
        assert db.session.get(User, admin).subscription_status == 'active'
    cancelled = _post_event(client, {
        'event_type': 'BILLING.SUBSCRIPTION.CANCELLED',
        'resource': {'id': 'I-SUB123', 'status': 'CANCELLED'},
    })
    assert cancelled.status_code == 200
    with app.app_context():
        user = db.session.get(User, admin)
        assert user.subscription_status == 'canceled'
        assert user.has_access is False


def test_webhook_rejects_a_bad_signature(client, monkeypatch):
    from app import billing

    _paypal_keys(monkeypatch)
    monkeypatch.setattr(billing, 'verify_webhook', lambda event: False)
    response = _post_event(client, {'event_type': 'BILLING.SUBSCRIPTION.ACTIVATED', 'resource': {}})
    assert response.status_code == 400
    assert response.data == b''


def test_webhook_is_exempt_from_csrf(monkeypatch, tmp_path):
    from app import create_app
    from app import billing

    _paypal_keys(monkeypatch)
    application = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(tmp_path / 'csrf.sqlite'),
        'WTF_CSRF_ENABLED': True,
        'SECRET_KEY': 'test-secret',
    })
    monkeypatch.setattr(billing, 'verify_webhook', lambda event: False)
    response = application.test_client().post(
        '/paypal/webhook',
        data=b'{}',
        headers={'Content-Type': 'application/json'},
    )
    assert response.status_code == 400
    assert b'CSRF' not in response.data
