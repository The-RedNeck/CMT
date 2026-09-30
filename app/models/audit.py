"""Sign-in and recovery events. Passwords and codes are never stored here."""

from datetime import datetime, timezone

from app import db


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuditEvent(db.Model):
    __tablename__ = 'audit_event'
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False, index=True)
    event = db.Column(db.String(40), nullable=False)
    username = db.Column(db.String(64))
    user_id = db.Column(db.Integer)
    ip_address = db.Column(db.String(64))
    detail = db.Column(db.String(200))
