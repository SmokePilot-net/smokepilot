from flask import Blueprint, jsonify, request, g
from database import (
    get_tree, get_groups, get_group,
    get_host, get_hosts,
    get_audit_log,
    get_api_tokens,
)
from auth import (
    filter_tree_for_user, hash_token,
)
from graph_renderer import render_graph, fetch_rrd_data
from updater import get_current_version

api = Blueprint("api", __name__, url_prefix="/api/v1")


# --- Auth middleware ---

@api.before_request
def authenticate():
    """Authenticate every API request via Bearer token or session."""
    from database import get_user_by_token, get_user as db_get_user
    from flask import session

    user = None

    # Check Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer spm_"):
        token = auth_header[7:]
        token_h = hash_token(token)
        user = get_user_by_token(token_h)
        if user:
            g.auth_method = "token"

    # Fall back to session
    if not user and session.get("user_id"):
        user = db_get_user(session["user_id"])
        if user:
            g.auth_method = "session"

    if not user or not user.get("is_active", True):
        return jsonify({"error": {"code": "unauthorized", "message": "Authentication required"}}), 401

    g.current_user = user


def require_role(*roles):
    """Check current user has one of the specified roles."""
    if g.current_user["role"] not in roles:
        return jsonify({"error": {"code": "forbidden", "message": "Insufficient permissions"}}), 403
    return None


# --- System ---

@api.route("/system/status")
def system_status():
    version = get_current_version()
    groups = get_groups()
    hosts = get_hosts()
    return jsonify({"data": {
        "version": version,
        "groups": len(groups),
        "hosts": len(hosts),
    }})


# --- Groups (read-only) ---

@api.route("/groups")
def list_groups():
    fmt = request.args.get("format", "tree")
    if fmt == "tree":
        tree = get_tree()
        tree = filter_tree_for_user(tree, g.current_user)
        return jsonify({"data": tree})
    groups = get_groups()
    return jsonify({"data": [dict(g) for g in groups]})


@api.route("/groups/<int:group_id>")
def get_group_detail(group_id):
    group = get_group(group_id)
    if not group:
        return jsonify({"error": {"code": "not_found", "message": "Group not found"}}), 404
    return jsonify({"data": dict(group)})


# --- Hosts (read-only) ---

@api.route("/hosts")
def list_hosts():
    group_id = request.args.get("group_id", type=int)
    hosts = get_hosts(group_id)
    return jsonify({"data": [dict(h) for h in hosts]})


@api.route("/hosts/<int:host_id>")
def get_host_detail(host_id):
    host = get_host(host_id)
    if not host:
        return jsonify({"error": {"code": "not_found", "message": "Host not found"}}), 404
    return jsonify({"data": dict(host)})


def _build_target_path(host):
    """Build SmokePing target path from host's group hierarchy. Returns path or None."""
    group = get_group(host["group_id"])
    if not group:
        return None
    parts = [group["name"]]
    parent_id = group["parent_id"]
    while parent_id:
        parent = get_group(parent_id)
        if not parent:
            break
        parts.insert(0, parent["name"])
        parent_id = parent["parent_id"]
    return ".".join(parts) + "." + host["name"]


@api.route("/hosts/<int:host_id>/graph")
def host_graph(host_id):
    """Render a graph for a specific host. Returns PNG image."""
    from flask import Response
    host = get_host(host_id)
    if not host:
        return jsonify({"error": {"code": "not_found", "message": "Host not found"}}), 404

    target_path = _build_target_path(host)
    if not target_path:
        return jsonify({"error": {"code": "not_found", "message": "Host group not found"}}), 404

    display_range = request.args.get("range", "3h")
    style = request.args.get("style", "light")
    content_type, body = render_graph(target_path, display_range, style=style)
    return Response(body, content_type=content_type, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    })


@api.route("/hosts/<int:host_id>/data")
def host_data(host_id):
    """Return RRD time series data as JSON."""
    host = get_host(host_id)
    if not host:
        return jsonify({"error": {"code": "not_found", "message": "Host not found"}}), 404

    target_path = _build_target_path(host)
    if not target_path:
        return jsonify({"error": {"code": "not_found", "message": "Host group not found"}}), 404

    display_range = request.args.get("range", "3h")
    data = fetch_rrd_data(target_path, display_range)
    return jsonify({"data": data})


# --- Tokens (read + create/delete own, limited to 1 in community) ---

@api.route("/tokens")
def list_tokens():
    tokens = get_api_tokens(g.current_user["id"])
    return jsonify({"data": [dict(t) for t in tokens]})


# --- Audit Log (admin, last 50) ---

@api.route("/audit-log")
def list_audit():
    err = require_role("admin")
    if err:
        return err
    entries = get_audit_log(limit=50)
    return jsonify({"data": [dict(e) for e in entries]})
