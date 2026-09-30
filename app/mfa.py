"""Authenticator-app MFA for super admin accounts."""

import base64
import io
import json
import re
import secrets

import pyotp
import qrcode
from sqlalchemy import inspect, text
from app import db
from app.models.user import User
from app.passwords import hash_secret, verify_secret

_RECOVERY_COUNT = 8


def ensure_mfa_columns():
    """Add authenticator columns on databases created before MFA."""
    inspector = inspect(db.engine)
    if 'users' not in inspector.get_table_names():
        return
    columns = {column['name'] for column in inspector.get_columns('users')}
    statements = []
    if 'totp_secret' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN totp_secret VARCHAR(64)')
    if 'mfa_enabled' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN DEFAULT 0')
    if 'mfa_recovery_hashes' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN mfa_recovery_hashes TEXT')
    for statement in statements:
        db.session.execute(text(statement))
    if statements:
        db.session.commit()


def new_secret():
    return pyotp.random_base32()


def provisioning_uri(user, secret):
    return pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name='CMT')


def qr_data_uri(uri):
    image = qrcode.make(uri)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return 'data:image/png;base64,' + encoded


def verify_totp(secret, code):
    digits = re.sub(r'\s', '', code or '')
    if not secret or not digits.isdigit() or len(digits) != 6:
        return False
    return bool(pyotp.TOTP(secret).verify(digits, valid_window=1))


def _normalize_recovery(code):
    return re.sub(r'[\s-]', '', code or '').upper()


def new_recovery_codes():
    """Eight codes, 80 bits each, shown in groups of four."""
    codes = []
    for _ in range(_RECOVERY_COUNT):
        raw = secrets.token_hex(10).upper()
        codes.append('-'.join(raw[i:i + 4] for i in range(0, len(raw), 4)))
    return codes


def store_recovery_codes(user, codes):
    hashes = [hash_secret(_normalize_recovery(code)) for code in codes]
    user.mfa_recovery_hashes = json.dumps(hashes)


def consume_recovery_code(user, code):
    normalized = _normalize_recovery(code)
    if len(normalized) < 8:
        return False
    try:
        hashes = json.loads(user.mfa_recovery_hashes or '[]')
    except (TypeError, ValueError):
        return False
    kept = []
    matched = False
    for hashed in hashes:
        if not matched and verify_secret(hashed, normalized):
            matched = True
            continue
        kept.append(hashed)
    if matched:
        user.mfa_recovery_hashes = json.dumps(kept)
    return matched


def pending_admin():
    """The super admin who still has to finish authenticator setup or a code."""
    from flask import session
    from flask_login import current_user

    if current_user.is_authenticated and current_user.is_super_admin and not current_user.mfa_enabled:
        return current_user
    user_id = session.get('mfa_user_id')
    if not user_id:
        return None
    user = db.session.get(User, int(user_id))
    if user and user.is_super_admin and user.active:
        return user
    return None
