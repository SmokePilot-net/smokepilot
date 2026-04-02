import sqlite3
from config import DATABASE


def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    """Initialize database by running all pending migrations."""
    from migrations import run_migrations
    run_migrations()
    _seed_admin_user()


# --- Group CRUD ---

def get_groups():
    db = get_db()
    groups = db.execute("SELECT * FROM groups ORDER BY sort_order, name").fetchall()
    db.close()
    return groups


def get_group(group_id):
    db = get_db()
    group = db.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    db.close()
    return group


def create_group(name, title=None, parent_id=None):
    db = get_db()
    db.execute(
        "INSERT INTO groups (name, title, parent_id) VALUES (?, ?, ?)",
        (name, title or name, parent_id)
    )
    db.commit()
    db.close()


def update_group(group_id, name, title=None, parent_id=None):
    db = get_db()
    db.execute(
        "UPDATE groups SET name = ?, title = ?, parent_id = ? WHERE id = ?",
        (name, title or name, parent_id, group_id)
    )
    db.commit()
    db.close()


def delete_group(group_id):
    db = get_db()
    db.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    db.commit()
    db.close()


# --- Host CRUD ---

def get_hosts(group_id=None):
    db = get_db()
    if group_id:
        hosts = db.execute(
            "SELECT * FROM hosts WHERE group_id = ? ORDER BY sort_order, name",
            (group_id,)
        ).fetchall()
    else:
        hosts = db.execute("SELECT * FROM hosts ORDER BY sort_order, name").fetchall()
    db.close()
    return hosts


def get_host(host_id):
    db = get_db()
    host = db.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()
    db.close()
    return host


def create_host(name, host, group_id, title=None, probe="FPing"):
    db = get_db()
    db.execute(
        "INSERT INTO hosts (name, host, group_id, title, probe) VALUES (?, ?, ?, ?, ?)",
        (name, host, group_id, title or name, probe)
    )
    db.commit()
    db.close()


def update_host(host_id, name, host, group_id, title=None, probe="FPing", enabled=1):
    db = get_db()
    db.execute(
        "UPDATE hosts SET name = ?, host = ?, group_id = ?, title = ?, probe = ?, enabled = ? WHERE id = ?",
        (name, host, group_id, title or name, probe, enabled, host_id)
    )
    db.commit()
    db.close()


def delete_host(host_id):
    db = get_db()
    db.execute("DELETE FROM hosts WHERE id = ?", (host_id,))
    db.commit()
    db.close()


# --- Tree helpers ---

def get_tree():
    """Build the full group/host tree for display and config generation."""
    db = get_db()
    groups = db.execute("SELECT * FROM groups ORDER BY sort_order, name").fetchall()
    hosts = db.execute("SELECT * FROM hosts WHERE enabled = 1 ORDER BY sort_order, name").fetchall()
    db.close()

    groups_by_parent = {}
    for g in groups:
        parent = g["parent_id"]
        if parent not in groups_by_parent:
            groups_by_parent[parent] = []
        groups_by_parent[parent].append(dict(g))

    hosts_by_group = {}
    for h in hosts:
        gid = h["group_id"]
        if gid not in hosts_by_group:
            hosts_by_group[gid] = []
        hosts_by_group[gid].append(dict(h))

    # Build lookup for parent chain (to construct SmokePing target paths)
    group_by_id = {g["id"]: dict(g) for g in groups}

    def get_group_path(group_id):
        """Build the dotted path for a group, e.g. 'Clients.Pepperstone'."""
        parts = []
        gid = group_id
        while gid is not None:
            g = group_by_id.get(gid)
            if not g:
                break
            parts.append(g["name"])
            gid = g["parent_id"]
        parts.reverse()
        return ".".join(parts)

    def build_subtree(parent_id):
        tree = []
        for g in groups_by_parent.get(parent_id, []):
            group_path = get_group_path(g["id"])
            host_list = []
            for h in hosts_by_group.get(g["id"], []):
                h_copy = dict(h)
                h_copy["target_path"] = f"{group_path}.{h['name']}"
                host_list.append(h_copy)
            node = {
                "type": "group",
                "id": g["id"],
                "name": g["name"],
                "title": g["title"],
                "path": group_path,
                "children": build_subtree(g["id"]),
                "hosts": host_list,
            }
            tree.append(node)
        return tree

    return build_subtree(None)


# --- User CRUD ---

def get_users():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY username").fetchall()
    db.close()
    return users


def get_user(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    return dict(user) if user else None


def get_user_by_username(username):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    db.close()
    return dict(user) if user else None


def get_user_by_token(token_hash):
    db = get_db()
    row = db.execute("""
        SELECT u.*, t.scopes as token_scopes, t.id as token_id
        FROM api_tokens t JOIN users u ON t.user_id = u.id
        WHERE t.token_hash = ? AND (t.expires_at IS NULL OR t.expires_at > datetime('now'))
    """, (token_hash,)).fetchone()
    if row:
        db.execute("UPDATE api_tokens SET last_used_at = datetime('now') WHERE id = ?", (row["token_id"],))
        db.commit()
    db.close()
    return dict(row) if row else None


def create_user(username, password_hash, email=None, role="viewer"):
    db = get_db()
    db.execute(
        "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (username, email, password_hash, role)
    )
    db.commit()
    user_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return user_id


def update_user(user_id, username=None, email=None, role=None, password_hash=None, is_active=None):
    db = get_db()
    fields = []
    values = []
    if username is not None:
        fields.append("username = ?")
        values.append(username)
    if email is not None:
        fields.append("email = ?")
        values.append(email)
    if role is not None:
        fields.append("role = ?")
        values.append(role)
    if password_hash is not None:
        fields.append("password_hash = ?")
        values.append(password_hash)
    if is_active is not None:
        fields.append("is_active = ?")
        values.append(is_active)
    if fields:
        fields.append("updated_at = datetime('now')")
        values.append(user_id)
        db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
        db.commit()
    db.close()


def delete_user(user_id):
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    db.close()


# --- User Permissions ---

def get_user_permissions(user_id):
    db = get_db()
    perms = db.execute(
        "SELECT * FROM user_permissions WHERE user_id = ? ORDER BY group_pattern",
        (user_id,)
    ).fetchall()
    db.close()
    return perms


def set_user_permissions(user_id, patterns):
    """Replace all permissions for a user. patterns is a list of (group_pattern, permission) tuples."""
    db = get_db()
    db.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
    for pattern, perm in patterns:
        db.execute(
            "INSERT INTO user_permissions (user_id, group_pattern, permission) VALUES (?, ?, ?)",
            (user_id, pattern, perm)
        )
    db.commit()
    db.close()


# --- API Tokens ---

def create_api_token(user_id, name, token_hash, token_prefix, scopes="*", expires_at=None):
    db = get_db()
    db.execute(
        "INSERT INTO api_tokens (user_id, name, token_hash, token_prefix, scopes, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, name, token_hash, token_prefix, scopes, expires_at)
    )
    db.commit()
    db.close()


def get_api_tokens(user_id):
    db = get_db()
    tokens = db.execute(
        "SELECT id, name, token_prefix, scopes, expires_at, last_used_at, created_at FROM api_tokens WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    db.close()
    return tokens


def delete_api_token(token_id, user_id):
    db = get_db()
    db.execute("DELETE FROM api_tokens WHERE id = ? AND user_id = ?", (token_id, user_id))
    db.commit()
    db.close()


# --- Audit Log ---

def log_audit(user_id, username, action, entity_type, entity_id=None, entity_name=None, details=None, ip_address=None):
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (user_id, username, action, entity_type, entity_id, entity_name, details, ip_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, username, action, entity_type, entity_id, entity_name, details, ip_address)
    )
    db.commit()
    db.close()


def get_audit_log(limit=100, entity_type=None, user_id=None):
    db = get_db()
    query = "SELECT * FROM audit_log"
    conditions = []
    values = []
    if entity_type:
        conditions.append("entity_type = ?")
        values.append(entity_type)
    if user_id:
        conditions.append("user_id = ?")
        values.append(user_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT ?"
    values.append(limit)
    rows = db.execute(query, values).fetchall()
    db.close()
    return rows


# --- Seed admin user ---

def _seed_admin_user():
    """Create initial admin user from env vars if no users exist."""
    from config import ADMIN_USER, ADMIN_PASSWORD
    from auth import hash_password

    db = get_db()
    try:
        count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    except Exception:
        db.close()
        return

    if count == 0 and ADMIN_USER and ADMIN_PASSWORD:
        pw_hash = hash_password(ADMIN_PASSWORD)
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
            (ADMIN_USER, pw_hash)
        )
        db.commit()
        print(f"  Created initial admin user: {ADMIN_USER}")
    db.close()
