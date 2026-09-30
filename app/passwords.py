"""Password hashing.

Scrypt with N=2^17, r=8, p=1. That is about 128 MiB and a few hundred
milliseconds per check, which is OWASP's current minimum. Older hashes still
verify, then get rewritten with these parameters so nobody has to reset.
"""

from flask import current_app, has_app_context
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from app import db

# N=131072, r=8, p=1. Tests override this with a cheaper method.
DEFAULT_PASSWORD_METHOD = 'scrypt:131072:8:1'


def password_method():
    if has_app_context():
        return current_app.config.get('PASSWORD_HASH_METHOD', DEFAULT_PASSWORD_METHOD)
    return DEFAULT_PASSWORD_METHOD


def hash_secret(secret):
    return generate_password_hash(secret, method=password_method())


def needs_rehash(stored):
    if not stored or '$' not in stored:
        return True
    return stored.split('$', 1)[0] != password_method()


def verify_secret(stored, secret):
    if not stored or secret is None:
        return False
    return check_password_hash(stored, secret)


def upgrade_stored_hash(record, secret, attr='password_hash'):
    """Replace a successful but outdated hash and save it immediately."""
    setattr(record, attr, hash_secret(secret))
    db.session.commit()


def ensure_password_hash_storage():
    """Widen password columns on Postgres. SQLite already stores the full hash."""
    if db.engine.dialect.name != 'postgresql':
        return
    inspector = inspect(db.engine)
    for table in ('users', 'employee'):
        if table not in inspector.get_table_names():
            continue
        for column in inspector.get_columns(table):
            if column['name'] != 'password_hash':
                continue
            length = getattr(column['type'], 'length', None)
            if length is not None and length < 256:
                db.session.execute(text(
                    f'ALTER TABLE {table} ALTER COLUMN password_hash TYPE TEXT'
                ))
                db.session.commit()
