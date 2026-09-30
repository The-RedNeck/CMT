from datetime import datetime, timedelta, timezone

from flask_login import UserMixin

from app import db
from app.passwords import hash_secret, needs_rehash, upgrade_stored_hash, verify_secret

TRIAL_DAYS = 90


def _utcnow():
    """Naive UTC, matching the rest of the stored timestamps."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def trial_end_from_now():
    return _utcnow() + timedelta(days=TRIAL_DAYS)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    active = db.Column(db.Boolean, default=True)
    failed_logins = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    lockout_count = db.Column(db.Integer, default=0)  # Track number of lockouts for progressive lockout
    is_super_admin = db.Column(db.Boolean, default=False)
    totp_secret = db.Column(db.String(64))
    mfa_enabled = db.Column(db.Boolean, default=False)
    mfa_recovery_hashes = db.Column(db.Text)
    trial_ends_at = db.Column(db.DateTime, default=trial_end_from_now)
    stripe_customer_id = db.Column(db.String(64))
    subscription_status = db.Column(db.String(32))

    @property
    def in_trial(self):
        if self.trial_ends_at is None:
            return False
        return _utcnow() < self.trial_ends_at

    @property
    def has_access(self):
        return self.in_trial or self.subscription_status == 'active'

    @property
    def trial_ending_soon(self):
        if self.subscription_status == 'active' or not self.in_trial:
            return False
        return self.trial_ends_at - _utcnow() < timedelta(days=7)

    def set_password(self, password):
        self.password_hash = hash_secret(password)

    def check_password(self, password):
        if not verify_secret(self.password_hash, password):
            return False
        if needs_rehash(self.password_hash):
            upgrade_stored_hash(self, password)
        return True 