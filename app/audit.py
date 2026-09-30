"""Write audit rows for sign-in, lockout, and recovery-code use."""

from app import db
from app.models.audit import AuditEvent
from app.utils.history import get_client_ip


def record_audit(event, username=None, user=None, detail=None):
    """Add an audit row. The caller commits it with the rest of the change."""
    name = username
    user_id = None
    if user is not None:
        name = name or getattr(user, 'username', None)
        user_id = getattr(user, 'id', None)
    db.session.add(AuditEvent(
        event=(event or '')[:40],
        username=(name or '')[:64] or None,
        user_id=user_id,
        ip_address=(get_client_ip() or '')[:64] or None,
        detail=(detail or '')[:200] or None,
    ))
