import functools
import hashlib
import secrets
import fnmatch
from flask import request, session, redirect, url_for, abort, g

# Try bcrypt, fall back to hashlib-based hashing
try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False


def hash_password(password):
    """Hash a password for storage."""
    if HAS_BCRYPT:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # Fallback: SHA-256 with salt (not as strong as bcrypt but works without pip install)
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"sha256:{salt}:{h}"


def check_password(password, password_hash):
    """Verify a password against its hash."""
    if password_hash.startswith("sha256:"):
        _, salt, h = password_hash.split(":", 2)
        return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest() == h
    if HAS_BCRYPT:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    return False


def generate_api_token():
    """Generate a new API token. Returns (raw_token, token_hash, token_prefix)."""
    raw_token = "spm_" + secrets.token_hex(20)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_prefix = raw_token[:12]
    return raw_token, token_hash, token_prefix


def hash_token(raw_token):
    """Hash an API token for lookup."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def get_current_user():
    """Get the current authenticated user from session or API token.

    Returns user dict or None.
    """
    from database import get_user, get_user_by_token

    # Check API token first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer spm_"):
        token = auth_header[7:]  # strip "Bearer "
        token_h = hash_token(token)
        user = get_user_by_token(token_h)
        if user and user["is_active"]:
            g.auth_method = "token"
            return user
        return None

    # Fall back to session
    user_id = session.get("user_id")
    if user_id:
        user = get_user(user_id)
        if user and user["is_active"]:
            g.auth_method = "session"
            return user

    # Legacy: check old session format (pre-multiuser)
    if session.get("logged_in"):
        from database import get_users
        users = get_users()
        if users:
            # Use first admin user
            for u in users:
                if u["role"] == "admin":
                    g.auth_method = "session"
                    session["user_id"] = u["id"]
                    return dict(u)

    return None


def auth_required(roles=None):
    """Decorator requiring authentication and optionally specific roles."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                if request.is_json or request.headers.get("Authorization"):
                    abort(401)
                return redirect(url_for("login"))

            if roles and user["role"] not in roles:
                abort(403)

            g.current_user = user
            return f(*args, **kwargs)
        return wrapper
    return decorator


def user_can_access_group(user, group_name, group_path=None):
    """Check if a user has access to a group.

    Args:
        user: user dict with 'role' and 'id'
        group_name: the group's name (e.g., 'Pepperstone')
        group_path: full dotted path (e.g., 'Clients.Pepperstone')
    """
    if user["role"] == "admin":
        return True

    from database import get_user_permissions
    permissions = get_user_permissions(user["id"])

    if not permissions:
        return False

    for perm in permissions:
        pattern = perm["group_pattern"]

        # Match against group name
        if fnmatch.fnmatch(group_name, pattern):
            return True

        # Match against full path if provided
        if group_path and fnmatch.fnmatch(group_path, pattern):
            return True

        # Match against top-level component
        if group_path:
            top_level = group_path.split(".")[0]
            if fnmatch.fnmatch(top_level, pattern):
                return True

        # Wildcard matches everything
        if pattern == "*":
            return True

    return False


def filter_tree_for_user(tree, user):
    """Filter a group/host tree to only include groups the user can access."""
    if user["role"] == "admin":
        return tree

    filtered = []
    for node in tree:
        path = node.get("path", node["name"])
        if user_can_access_group(user, node["name"], path):
            filtered.append(node)
        else:
            # Check children — user might have access to a subgroup
            if node.get("children"):
                child_tree = filter_tree_for_user(node["children"], user)
                if child_tree:
                    node_copy = dict(node)
                    node_copy["children"] = child_tree
                    node_copy["hosts"] = []  # hide parent's hosts if no direct access
                    filtered.append(node_copy)
    return filtered
