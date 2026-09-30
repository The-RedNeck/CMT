from datetime import timedelta

import stripe

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


def test_checkout_without_keys_stays_on_pricing(client, admin, monkeypatch):
    monkeypatch.delenv('STRIPE_SECRET_KEY', raising=False)
    monkeypatch.delenv('STRIPE_PRICE_ID', raising=False)
    login(client)
    response = client.post('/billing/checkout', follow_redirects=True)
    assert b'not configured' in response.data


def test_checkout_redirects_to_stripe(client, app, admin, monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'sk_test_123')
    monkeypatch.setenv('STRIPE_PRICE_ID', 'price_123')

    class Customer:
        id = 'cus_new'

    class Session:
        url = 'https://checkout.stripe.test/pay'

    def fake_customer(**kwargs):
        assert kwargs['email'] == 'admin@example.com'
        assert kwargs['metadata']['user_id'] == str(admin)
        return Customer()

    def fake_session(**kwargs):
        assert kwargs['mode'] == 'subscription'
        assert kwargs['customer'] == 'cus_new'
        assert kwargs['line_items'] == [{'price': 'price_123', 'quantity': 1}]
        return Session()

    monkeypatch.setattr(stripe.Customer, 'create', fake_customer)
    monkeypatch.setattr(stripe.checkout.Session, 'create', fake_session)
    login(client)
    response = client.post('/billing/checkout')
    assert response.status_code == 303
    assert response.headers['Location'] == 'https://checkout.stripe.test/pay'
    with app.app_context():
        user = db.session.get(User, admin)
        assert user.stripe_customer_id == 'cus_new'


def test_portal_requires_a_customer(client, admin):
    login(client)
    response = client.post('/billing/portal', follow_redirects=True)
    assert b'Subscribe before managing billing' in response.data


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


def test_webhook_sets_status_and_ignores_unknown_customers(client, app, admin, monkeypatch):
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_test')
    with app.app_context():
        user = db.session.get(User, admin)
        user.stripe_customer_id = 'cus_123'
        db.session.commit()

    def fake_event(payload, signature, secret):
        assert secret == 'whsec_test'
        return {
            'type': 'customer.subscription.updated',
            'data': {'object': {'customer': 'cus_123', 'status': 'active'}},
        }

    monkeypatch.setattr(stripe.Webhook, 'construct_event', fake_event)
    response = client.post('/stripe/webhook', data=b'{}', headers={'Stripe-Signature': 'ok'})
    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(User, admin).subscription_status == 'active'

    def unknown_event(payload, signature, secret):
        return {
            'type': 'customer.subscription.deleted',
            'data': {'object': {'customer': 'cus_missing', 'status': 'canceled'}},
        }

    monkeypatch.setattr(stripe.Webhook, 'construct_event', unknown_event)
    ignored = client.post('/stripe/webhook', data=b'{}', headers={'Stripe-Signature': 'ok'})
    assert ignored.status_code == 200
    with app.app_context():
        assert db.session.get(User, admin).subscription_status == 'active'


def test_webhook_rejects_a_bad_signature(client, monkeypatch):
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_test')
    response = client.post(
        '/stripe/webhook',
        data=b'{}',
        headers={'Stripe-Signature': 't=1,v1=bad'},
    )
    assert response.status_code == 400
    assert response.data == b''


def test_webhook_is_exempt_from_csrf(monkeypatch, tmp_path):
    from app import create_app

    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_test')
    application = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(tmp_path / 'csrf.sqlite'),
        'WTF_CSRF_ENABLED': True,
        'SECRET_KEY': 'test-secret',
    })
    response = application.test_client().post(
        '/stripe/webhook',
        data=b'{}',
        headers={'Stripe-Signature': 't=1,v1=bad'},
    )
    assert response.status_code == 400
    assert b'CSRF' not in response.data
