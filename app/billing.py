"""App-managed 90-day trial. PayPal collects payment only after the trial ends."""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from functools import wraps

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text

from app import db
from app.models.user import User, trial_end_from_now

bp = Blueprint('billing', __name__)

_SUBSCRIPTION_EVENTS = (
    'BILLING.SUBSCRIPTION.ACTIVATED',
    'BILLING.SUBSCRIPTION.UPDATED',
    'BILLING.SUBSCRIPTION.CANCELLED',
    'BILLING.SUBSCRIPTION.SUSPENDED',
    'BILLING.SUBSCRIPTION.EXPIRED',
    'BILLING.SUBSCRIPTION.RE-ACTIVATED',
)

# PayPal's words, stored in the same lowercase values the rest of the app already checks.
_STATUS = {
    'ACTIVE': 'active',
    'SUSPENDED': 'past_due',
    'CANCELLED': 'canceled',
    'EXPIRED': 'canceled',
    'APPROVED': 'approved',
    'APPROVAL_PENDING': 'pending',
}


class PayPalError(Exception):
    """PayPal rejected the call or could not be reached."""


def ensure_subscription_columns():
    """Add billing columns on existing databases and give every account a trial end."""
    inspector = inspect(db.engine)
    if 'users' not in inspector.get_table_names():
        return
    columns = {column['name'] for column in inspector.get_columns('users')}
    statements = []
    if 'trial_ends_at' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN trial_ends_at DATETIME')
    if 'stripe_customer_id' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(64)')
    if 'paypal_subscription_id' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN paypal_subscription_id VARCHAR(64)')
    if 'subscription_status' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN subscription_status VARCHAR(32)')
    for statement in statements:
        db.session.execute(text(statement))
    if statements:
        db.session.commit()

    missing = User.query.filter(User.trial_ends_at.is_(None)).all()
    if not missing:
        return
    ends = trial_end_from_now()
    for user in missing:
        user.trial_ends_at = ends
    db.session.commit()


def subscription_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.has_access:
            flash('Your free trial has ended. Please subscribe to continue.', 'warning')
            return redirect(url_for('billing.pricing'))
        return view(*args, **kwargs)
    return wrapper


def _paypal_mode():
    return os.environ.get('PAYPAL_MODE', 'sandbox').strip().lower()


def paypal_api_base():
    if _paypal_mode() == 'live':
        return 'https://api-m.paypal.com'
    return 'https://api-m.sandbox.paypal.com'


def manage_url():
    if _paypal_mode() == 'live':
        return 'https://www.paypal.com/myaccount/autopay/'
    return 'https://www.sandbox.paypal.com/myaccount/autopay/'


def _billing_ready():
    return bool(
        os.environ.get('PAYPAL_CLIENT_ID')
        and os.environ.get('PAYPAL_CLIENT_SECRET')
        and os.environ.get('PAYPAL_PLAN_ID')
    )


def access_token():
    client_id = os.environ.get('PAYPAL_CLIENT_ID', '')
    secret = os.environ.get('PAYPAL_CLIENT_SECRET', '')
    basic = base64.b64encode(f'{client_id}:{secret}'.encode()).decode('ascii')
    body = urllib.parse.urlencode({'grant_type': 'client_credentials'}).encode()
    call = urllib.request.Request(
        paypal_api_base() + '/v1/oauth2/token',
        data=body,
        headers={
            'Authorization': f'Basic {basic}',
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(call, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise PayPalError(exc.read().decode(errors='replace')[:500]) from exc
    except urllib.error.URLError as exc:
        raise PayPalError('PayPal could not be reached.') from exc
    token = payload.get('access_token')
    if not token:
        raise PayPalError('PayPal did not return an access token.')
    return token


def paypal_request(method, path, payload=None):
    """Call one PayPal REST path with the app's client-credentials token."""
    data = None
    headers = {
        'Authorization': f'Bearer {access_token()}',
        'Accept': 'application/json',
    }
    if payload is not None:
        data = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    call = urllib.request.Request(
        paypal_api_base() + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(call, timeout=20) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise PayPalError(exc.read().decode(errors='replace')[:500]) from exc
    except urllib.error.URLError as exc:
        raise PayPalError('PayPal could not be reached.') from exc


def _approve_url(subscription):
    for link in subscription.get('links') or []:
        if link.get('rel') == 'approve' and link.get('href'):
            return link['href']
    return None


def verify_webhook(event):
    """Ask PayPal whether this delivery was signed for our webhook id."""
    webhook_id = os.environ.get('PAYPAL_WEBHOOK_ID')
    transmission_id = request.headers.get('Paypal-Transmission-Id')
    transmission_time = request.headers.get('Paypal-Transmission-Time')
    transmission_sig = request.headers.get('Paypal-Transmission-Sig')
    cert_url = request.headers.get('Paypal-Cert-Url')
    auth_algo = request.headers.get('Paypal-Auth-Algo')
    if not all((webhook_id, transmission_id, transmission_time, transmission_sig, cert_url, auth_algo)):
        return False
    result = paypal_request('POST', '/v1/notifications/verify-webhook-signature', {
        'auth_algo': auth_algo,
        'cert_url': cert_url,
        'transmission_id': transmission_id,
        'transmission_sig': transmission_sig,
        'transmission_time': transmission_time,
        'webhook_id': webhook_id,
        'webhook_event': event,
    })
    return result.get('verification_status') == 'SUCCESS'


def _user_for_subscription(resource):
    custom_id = str(resource.get('custom_id') or '')
    if custom_id.isdigit():
        user = db.session.get(User, int(custom_id))
        if user is not None:
            return user
    subscription_id = resource.get('id')
    if not subscription_id:
        return None
    return User.query.filter_by(paypal_subscription_id=subscription_id).first()


@bp.route('/billing/pricing')
def pricing():
    return render_template(
        'billing/pricing.html',
        billing_ready=_billing_ready(),
        price_label=os.environ.get('PAYPAL_PRICE_LABEL', ''),
    )


@bp.route('/billing/checkout', methods=['POST'])
@login_required
def checkout():
    plan_id = os.environ.get('PAYPAL_PLAN_ID')
    if not _billing_ready() or not plan_id:
        flash('Billing is not configured yet. Set PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, and PAYPAL_PLAN_ID.', 'warning')
        return redirect(url_for('billing.pricing'))

    try:
        subscription = paypal_request('POST', '/v1/billing/subscriptions', {
            'plan_id': plan_id,
            'custom_id': str(current_user.id),
            'subscriber': {'email_address': current_user.email},
            'application_context': {
                'brand_name': 'CMT',
                'shipping_preference': 'NO_SHIPPING',
                'user_action': 'SUBSCRIBE_NOW',
                'return_url': url_for('billing.success', _external=True),
                'cancel_url': url_for('billing.pricing', _external=True),
            },
        })
        approve = _approve_url(subscription)
        if not approve or not subscription.get('id'):
            raise PayPalError('PayPal did not return an approval link.')
        current_user.paypal_subscription_id = subscription['id']
        db.session.commit()
    except PayPalError:
        current_app.logger.exception('PayPal checkout failed')
        flash('Checkout could not be started. Try again in a moment.', 'danger')
        return redirect(url_for('billing.pricing'))
    return redirect(approve, code=303)


@bp.route('/billing/success')
def success():
    return render_template('billing/success.html')


@bp.route('/billing/portal', methods=['POST'])
@login_required
def portal():
    if not current_user.paypal_subscription_id:
        flash('Subscribe before managing billing.', 'warning')
        return redirect(url_for('billing.pricing'))
    return redirect(manage_url(), code=303)


@bp.route('/paypal/webhook', methods=['POST'])
def webhook():
    try:
        event = json.loads(request.data.decode() or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        return '', 400
    if not isinstance(event, dict):
        return '', 400
    try:
        if not verify_webhook(event):
            return '', 400
    except PayPalError:
        current_app.logger.exception('PayPal webhook verification failed')
        return '', 400

    if event.get('event_type') not in _SUBSCRIPTION_EVENTS:
        return '', 200
    resource = event.get('resource') or {}
    if not isinstance(resource, dict):
        return '', 200
    user = _user_for_subscription(resource)
    if user is None:
        return '', 200
    if resource.get('id'):
        user.paypal_subscription_id = resource['id']
    status = _STATUS.get(str(resource.get('status') or '').upper())
    if status:
        user.subscription_status = status
    db.session.commit()
    return '', 200
