import json
from flask import g, request
from database import log_audit


def log_action(action, entity_type, entity_id=None, entity_name=None, details=None):
    """Log an action to the audit trail. Call from any route after authentication."""
    user = getattr(g, "current_user", None)
    user_id = user["id"] if user else None
    username = user["username"] if user else "system"
    ip = request.remote_addr if request else None

    details_json = json.dumps(details) if details else None

    log_audit(
        user_id=user_id,
        username=username,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        details=details_json,
        ip_address=ip,
    )
