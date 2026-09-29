"""App-managed 90-day trial. Stripe collects payment only after the trial ends."""

import os
from functools import wraps

import stripe
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text

from app import db
from app.models.user import User, trial_end_from_now

bp = Blueprint('billing', __name__)

_SUBSCRIPTION_EVENTS = (
    'customer.subscription.created',
    'customer.subscription.updated',
    'customer.subscription.deleted',
)


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


def _billing_ready():
    return bool(os.environ.get('STRIPE_SECRET_KEY') and os.environ.get('STRIPE_PRICE_ID'))


@bp.route('/billing/pricing')
def pricing():
    return render_template(
        'billing/pricing.html',
        billing_ready=_billing_ready(),
        price_label=os.environ.get('STRIPE_PRICE_LABEL', ''),
    )


@bp.route('/billing/checkout', methods=['POST'])
@login_required
def checkout():
    secret = os.environ.get('STRIPE_SECRET_KEY')
    price_id = os.environ.get('STRIPE_PRICE_ID')
    if not secret or not price_id:
        flash('Billing is not configured yet. Set STRIPE_SECRET_KEY and STRIPE_PRICE_ID.', 'warning')
        return redirect(url_for('billing.pricing'))

    stripe.api_key = secret
    try:
        if not current_user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                metadata={'user_id': str(current_user.id)},
            )
            current_user.stripe_customer_id = customer.id
            db.session.commit()
        session = stripe.checkout.Session.create(
            mode='subscription',
            customer=current_user.stripe_customer_id,
            line_items=[{'price': price_id, 'quantity': 1}],
            success_url=url_for('billing.success', _external=True),
            cancel_url=url_for('billing.pricing', _external=True),
        )
    except stripe.StripeError:
        current_app.logger.exception('Stripe checkout failed')
        flash('Checkout could not be started. Try again in a moment.', 'danger')
        return redirect(url_for('billing.pricing'))
    return redirect(session.url, code=303)


@bp.route('/billing/success')
def success():
    return render_template('billing/success.html')


@bp.route('/billing/portal', methods=['POST'])
@login_required
def portal():
    secret = os.environ.get('STRIPE_SECRET_KEY')
    if not secret or not current_user.stripe_customer_id:
        flash('Subscribe before managing billing.', 'warning')
        return redirect(url_for('billing.pricing'))

    stripe.api_key = secret
    try:
        session = stripe.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=url_for('home', _external=True),
        )
    except stripe.StripeError:
        current_app.logger.exception('Stripe billing portal failed')
        flash('Billing portal could not be opened. Try again in a moment.', 'danger')
        return redirect(url_for('billing.pricing'))
    return redirect(session.url, code=303)


@bp.route('/stripe/webhook', methods=['POST'])
def webhook():
    secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
    if not secret:
        return '', 400
    try:
        event = stripe.Webhook.construct_event(
            request.data,
            request.headers.get('Stripe-Signature'),
            secret,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return '', 400

    if event['type'] in _SUBSCRIPTION_EVENTS:
        subscription = event['data']['object']
        user = User.query.filter_by(stripe_customer_id=subscription['customer']).first()
        if user:
            user.subscription_status = subscription['status']
            db.session.commit()
    return '', 200
