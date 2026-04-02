import os
import functools
from flask import abort

EDITION = os.environ.get("SPM_EDITION", "community")


def require_edition(*editions):
    """Decorator to gate routes by edition (community, pro, saas)."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if EDITION not in editions:
                abort(403, description="This feature requires SmokePilot Pro")
            return f(*args, **kwargs)
        return wrapper
    return decorator


def is_pro():
    return EDITION in ("pro", "saas")


def is_saas():
    return EDITION == "saas"
