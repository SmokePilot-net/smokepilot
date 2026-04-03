import os
import re
from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, g
from database import (
    init_db, get_tree, get_groups, get_group, create_group, update_group, delete_group,
    get_host, get_hosts, create_host, update_host, delete_host,
    get_users, get_user, get_user_by_username, create_user, delete_user,
    set_user_permissions,
    create_api_token, delete_api_token,
    get_audit_log,
    get_slaves, get_slave, create_slave as db_create_slave, delete_slave as db_delete_slave,
    get_slave_hosts, assign_host_to_slave, unassign_host_from_slave,
)
from generator import generate_config, write_config, reload_smokeping
from updater import get_current_version, check_for_updates, apply_update, restart_service
from graph_renderer import render_graph
from importer import parse_targets_file, import_to_database
from auth import (
    auth_required, hash_password, check_password, generate_api_token,
    filter_tree_for_user,
)
from audit import log_action
from api import api as api_blueprint, agent_bp as agent_blueprint
from config import SECRET_KEY, HOST, PORT, DEBUG, PUBLIC_URL

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.register_blueprint(api_blueprint)
app.register_blueprint(agent_blueprint)

VALID_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def deploy_and_reload():
    """Write config and reload SmokePing. Called after every change."""
    try:
        write_config()
        success, msg = reload_smokeping()
        if not success:
            flash(f"Config written but reload failed: {msg}", "error")
    except Exception as e:
        flash(f"Auto-deploy failed: {e}", "error")


# --- Auth routes ---

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = get_user_by_username(username)
        if user and check_password(password, user["password_hash"]):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            log_action("login", "user", user["id"], username)
            return redirect(url_for("dashboard"))
        flash("Invalid credentials", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    log_action("logout", "user")
    session.clear()
    return redirect(url_for("login"))


@app.context_processor
def inject_globals():
    return {
        "smokeping_cgi_url": url_for("smokeping_cgi_proxy"),
        "current_user": getattr(g, "current_user", None) or _session_user(),
    }


def _session_user():
    """Get minimal user info from session for template rendering."""
    if session.get("user_id"):
        return {"username": session.get("username"), "role": session.get("role")}
    return None


# --- Dashboard (graphs) ---

@app.route("/")
@auth_required()
def dashboard():
    tree = get_tree()
    tree = filter_tree_for_user(tree, g.current_user)
    return render_template("dashboard.html", tree=tree)


@app.route("/host/<path:target_path>")
@auth_required()
def host_detail(target_path):
    return render_template("host_detail.html", target_path=target_path)


# --- Graph rendering ---

@app.route("/smokeping-cgi")
@auth_required()
def smokeping_cgi_proxy():
    target = request.args.get("target", "")
    display_range = request.args.get("displayrange", "3h")
    start = request.args.get("start")
    end = request.args.get("end")
    style = session.get("graph_style", "classic")
    content_type, body = render_graph(target, display_range, start=start, end=end, style=style)
    return Response(body, content_type=content_type, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    })


# --- Manage (target administration) ---

@app.route("/manage")
@auth_required()
def manage():
    tree = get_tree()
    tree = filter_tree_for_user(tree, g.current_user)
    groups = get_groups()
    return render_template("manage.html", tree=tree, groups=groups)


@app.route("/group/add", methods=["POST"])
@auth_required(roles=["admin", "operator"])
def add_group():
    name = request.form.get("name", "").strip()
    title = request.form.get("title", "").strip()
    parent_id = request.form.get("parent_id") or None

    if not name or not VALID_NAME.match(name):
        flash("Invalid name. Use letters, numbers, underscore. Must start with a letter.", "error")
        return redirect(url_for("manage"))

    if parent_id:
        parent_id = int(parent_id)

    try:
        create_group(name, title or name, parent_id)
        log_action("create", "group", entity_name=name)
        flash(f"Group '{name}' created", "success")
        deploy_and_reload()
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("manage"))


@app.route("/group/<int:group_id>/edit", methods=["POST"])
@auth_required(roles=["admin", "operator"])
def edit_group(group_id):
    name = request.form.get("name", "").strip()
    title = request.form.get("title", "").strip()
    parent_id = request.form.get("parent_id") or None

    if not name or not VALID_NAME.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("manage"))

    if parent_id:
        parent_id = int(parent_id)
        if parent_id == group_id:
            flash("A group cannot be its own parent.", "error")
            return redirect(url_for("manage"))

    try:
        update_group(group_id, name, title or name, parent_id)
        log_action("update", "group", group_id, name)
        flash(f"Group '{name}' updated", "success")
        deploy_and_reload()
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("manage"))


@app.route("/group/<int:group_id>/delete", methods=["POST"])
@auth_required(roles=["admin", "operator"])
def remove_group(group_id):
    group = get_group(group_id)
    if group:
        delete_group(group_id)
        log_action("delete", "group", group_id, group["name"])
        flash(f"Group '{group['name']}' deleted (including all hosts and subgroups)", "success")
        deploy_and_reload()
    return redirect(url_for("manage"))


@app.route("/host/add", methods=["POST"])
@auth_required(roles=["admin", "operator"])
def add_host():
    name = request.form.get("name", "").strip()
    title = request.form.get("title", "").strip()
    host = request.form.get("host", "").strip()
    group_id = request.form.get("group_id")
    probe = request.form.get("probe", "FPing").strip()

    if not name or not VALID_NAME.match(name):
        flash("Invalid name. Use letters, numbers, underscore. Must start with a letter.", "error")
        return redirect(url_for("manage"))
    if not host:
        flash("Host (IP or hostname) is required.", "error")
        return redirect(url_for("manage"))
    if not group_id:
        flash("Please select a group.", "error")
        return redirect(url_for("manage"))

    try:
        create_host(name, host, int(group_id), title or name, probe)
        log_action("create", "host", entity_name=name, details={"host": host})
        flash(f"Host '{name}' ({host}) added", "success")
        deploy_and_reload()
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("manage"))


@app.route("/host/<int:host_id>/edit", methods=["POST"])
@auth_required(roles=["admin", "operator"])
def edit_host(host_id):
    name = request.form.get("name", "").strip()
    title = request.form.get("title", "").strip()
    host = request.form.get("host", "").strip()
    group_id = request.form.get("group_id")
    probe = request.form.get("probe", "FPing").strip()
    enabled = 1 if request.form.get("enabled") else 0

    if not name or not VALID_NAME.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("manage"))

    try:
        update_host(host_id, name, host, int(group_id), title or name, probe, enabled)
        log_action("update", "host", host_id, name)
        flash(f"Host '{name}' updated", "success")
        deploy_and_reload()
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("manage"))


@app.route("/host/<int:host_id>/delete", methods=["POST"])
@auth_required(roles=["admin", "operator"])
def remove_host(host_id):
    host = get_host(host_id)
    if host:
        delete_host(host_id)
        log_action("delete", "host", host_id, host["name"])
        flash(f"Host '{host['name']}' deleted", "success")
        deploy_and_reload()
    return redirect(url_for("manage"))


# --- Slaves ---

@app.route("/slaves")
@auth_required(roles=["admin"])
def slaves_page():
    slaves = get_slaves()
    hosts = get_hosts()
    # Build dict of assigned hosts per slave
    slave_hosts = {}
    for s in slaves:
        slave_hosts[s["id"]] = get_slave_hosts(s["id"])
    public_url = PUBLIC_URL or request.host_url.rstrip("/")
    return render_template("slaves.html", slaves=slaves, hosts=hosts,
                           slave_hosts=slave_hosts, public_url=public_url)


@app.route("/slaves/add", methods=["POST"])
@auth_required(roles=["admin"])
def add_slave():
    name = request.form.get("name", "").strip()
    display_name = request.form.get("display_name", "").strip()
    hostname = request.form.get("hostname", "").strip()
    location = request.form.get("location", "").strip()

    if not name or not VALID_NAME.match(name):
        flash("Invalid name. Use letters, numbers, underscore. Must start with a letter.", "error")
        return redirect(url_for("slaves_page"))
    if not hostname:
        flash("Hostname is required.", "error")
        return redirect(url_for("slaves_page"))

    raw_key, key_hash, key_prefix = generate_api_token()
    try:
        slave_id = db_create_slave(name, display_name or name, hostname, key_hash, key_prefix, location)
        log_action("create", "slave", slave_id, name, {"location": location})
        # Store key in session (one-time, not in URL to avoid log/history leaks)
        session["slave_api_key"] = raw_key
        return redirect(url_for("slave_setup", slave_id=slave_id))
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("slaves_page"))


@app.route("/slaves/<int:slave_id>/setup")
@auth_required(roles=["admin"])
def slave_setup(slave_id):
    slave = get_slave(slave_id)
    if not slave:
        flash("Slave not found.", "error")
        return redirect(url_for("slaves_page"))
    api_key = session.pop("slave_api_key", "")
    if not api_key:
        flash("API key is no longer available. Delete and recreate the slave to get a new key.", "error")
        return redirect(url_for("slaves_page"))
    public_url = PUBLIC_URL or request.host_url.rstrip("/")
    resp = render_template("slave_setup.html", slave=slave, api_key=api_key, public_url=public_url)
    return resp, 200, {"Cache-Control": "no-store"}


@app.route("/slaves/<int:slave_id>/delete", methods=["POST"])
@auth_required(roles=["admin"])
def remove_slave(slave_id):
    slave = get_slave(slave_id)
    if slave:
        db_delete_slave(slave_id)
        log_action("delete", "slave", slave_id, slave["name"])
        flash(f"Slave '{slave['name']}' deleted", "success")
    return redirect(url_for("slaves_page"))


@app.route("/slaves/<int:slave_id>/assign", methods=["POST"])
@auth_required(roles=["admin"])
def assign_slave_hosts(slave_id):
    host_ids = request.form.getlist("host_ids")
    # Clear existing and set new
    # Invert: set which slaves this host has -> set which hosts this slave has
    # First clear all assignments for this slave
    current_hosts = get_slave_hosts(slave_id)
    for h in current_hosts:
        unassign_host_from_slave(h["id"], slave_id)
    # Then assign selected
    for hid in host_ids:
        assign_host_to_slave(int(hid), slave_id)

    slave = get_slave(slave_id)
    log_action("assign_hosts", "slave", slave_id, slave["name"] if slave else None,
               {"host_ids": [int(h) for h in host_ids]})
    flash("Updated host assignments for slave", "success")
    return redirect(url_for("slaves_page"))


@app.route("/slaves/install/<int:slave_id>")
def serve_agent_installer(slave_id):
    """Serve a self-contained install script for a slave. No auth required — the API key is embedded."""
    slave = get_slave(slave_id)
    if not slave:
        return "Slave not found", 404

    public_url = PUBLIC_URL or request.host_url.rstrip("/")

    # Read the agent script
    agent_path = os.path.join(os.path.dirname(__file__), "agent", "smokeping_agent.py")
    with open(agent_path, "r") as f:
        agent_code = f.read()

    api_key = request.args.get("key", "")

    # Sanitize values for safe shell embedding
    import shlex
    safe_name = shlex.quote(slave['display_name'] or slave['name'])
    safe_key = shlex.quote(api_key)
    safe_url = shlex.quote(public_url)

    script = f"""#!/bin/bash
set -e
# SmokePilot Agent — auto-installer
# Generated by SmokePilot

SLAVE_KEY={safe_key}
MASTER_URL={safe_url}

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

if [ -z "$SLAVE_KEY" ]; then
    echo "ERROR: No API key provided. Use the install command from the SmokePilot UI."
    exit 1
fi

INSTALL_DIR="/opt/smokepilot-agent"
echo "=== Installing SmokePilot Agent ==="
echo "  Slave: {safe_name}"
echo "  Master: $MASTER_URL"

# Check SmokePing
if ! dpkg -l smokeping >/dev/null 2>&1; then
    echo "  Installing SmokePing..."
    apt-get update -qq && apt-get install -y -qq smokeping fping >/dev/null 2>&1
fi

# Install agent
mkdir -p "$INSTALL_DIR"
cat > "$INSTALL_DIR/smokeping_agent.py" << 'AGENT_EOF'
{agent_code}
AGENT_EOF
chmod +x "$INSTALL_DIR/smokeping_agent.py"

# Config (unquoted heredoc so $SLAVE_KEY and $MASTER_URL expand)
cat > /etc/smokepilot-agent.env << ENV_EOF
SPM_MASTER_URL=$MASTER_URL
SPM_SLAVE_KEY=$SLAVE_KEY
SPM_CONFIG_PATH=/etc/smokeping/config.d/Targets
SPM_PID_FILE=/var/run/smokeping/smokeping.pid
SPM_POLL_INTERVAL=60
ENV_EOF

# Systemd service
if command -v systemctl >/dev/null 2>&1; then
    cat > /etc/systemd/system/smokeping-agent.service << 'SVC_EOF'
[Unit]
Description=SmokePilot Agent
After=network.target smokeping.service

[Service]
Type=simple
User=root
EnvironmentFile=/etc/smokepilot-agent.env
ExecStart=/usr/bin/python3 /opt/smokepilot-agent/smokeping_agent.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SVC_EOF

    systemctl daemon-reload
    systemctl enable smokeping-agent
    systemctl start smokeping-agent
fi

echo ""
echo "=== Done ==="
echo "  SmokePilot agent is installed and running."
echo "  Status: sudo systemctl status smokeping-agent"
echo "  Logs:   sudo journalctl -u smokeping-agent -f"
"""
    return Response(script, content_type="text/plain")


# --- Settings ---

@app.route("/settings")
@auth_required(roles=["admin"])
def settings():
    current = get_current_version()
    has_updates, info = check_for_updates()
    config = generate_config()
    tree, parse_error = parse_targets_file()
    users = get_users()
    audit = get_audit_log(limit=50)
    return render_template("settings.html", current=current, has_updates=has_updates,
                           info=info, config=config, import_tree=tree, parse_error=parse_error,
                           users=users, audit=audit)


@app.route("/settings/import", methods=["POST"])
@auth_required(roles=["admin"])
def import_targets():
    tree, error = parse_targets_file()
    if error:
        flash(f"Import failed: {error}", "error")
        return redirect(url_for("settings"))

    groups_added, hosts_added, skipped = import_to_database(tree)
    log_action("import", "system", details={"groups": groups_added, "hosts": hosts_added, "skipped": skipped})
    flash(f"Imported {groups_added} groups and {hosts_added} hosts ({skipped} skipped/duplicates)", "success")
    if groups_added > 0 or hosts_added > 0:
        deploy_and_reload()
    return redirect(url_for("settings"))


@app.route("/settings/style", methods=["POST"])
@auth_required()
def set_style():
    style = request.form.get("style", "classic")
    if style in ("classic", "dark", "classic_dark"):
        session["graph_style"] = style
        flash(f"Graph style set to {style.replace('_', ' ').title()}", "success")
    return redirect(url_for("settings"))


@app.route("/settings/update", methods=["POST"])
@auth_required(roles=["admin"])
def do_update():
    success, message = apply_update()
    if success:
        log_action("update_system", "system", details={"message": message})
        flash(f"Updated successfully. Restarting in a few seconds... {message}", "success")
        restart_service()
    else:
        flash(f"Update failed: {message}", "error")
    return redirect(url_for("settings"))


@app.route("/settings/deploy", methods=["POST"])
@auth_required(roles=["admin"])
def deploy_config():
    try:
        filepath = write_config()
        flash(f"Config written to {filepath}", "success")

        if request.form.get("reload"):
            success, msg = reload_smokeping()
            if success:
                flash(msg, "success")
            else:
                flash(msg, "error")
    except Exception as e:
        flash(f"Deploy failed: {e}", "error")
    return redirect(url_for("settings"))


# --- User Management ---

@app.route("/settings/users/add", methods=["POST"])
@auth_required(roles=["admin"])
def add_user():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip() or None
    password = request.form.get("password", "")
    role = request.form.get("role", "viewer")

    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect(url_for("settings"))

    if role not in ("admin", "operator", "viewer"):
        role = "viewer"

    try:
        pw_hash = hash_password(password)
        user_id = create_user(username, pw_hash, email, role)

        # Set permissions if provided
        patterns = request.form.get("permissions", "").strip()
        if patterns and role != "admin":
            perm_list = [(p.strip(), "view") for p in patterns.split(",") if p.strip()]
            set_user_permissions(user_id, perm_list)

        log_action("create", "user", user_id, username, {"role": role})
        flash(f"User '{username}' created with role '{role}'", "success")
    except Exception as e:
        flash(f"Error creating user: {e}", "error")
    return redirect(url_for("settings"))


@app.route("/settings/users/<int:user_id>/delete", methods=["POST"])
@auth_required(roles=["admin"])
def remove_user(user_id):
    user = get_user(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("settings"))

    if user["id"] == g.current_user["id"]:
        flash("You cannot delete yourself.", "error")
        return redirect(url_for("settings"))

    delete_user(user_id)
    log_action("delete", "user", user_id, user["username"])
    flash(f"User '{user['username']}' deleted", "success")
    return redirect(url_for("settings"))


# --- API Token Management ---

@app.route("/settings/tokens/create", methods=["POST"])
@auth_required()
def create_token():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Token name is required.", "error")
        return redirect(url_for("settings"))

    raw_token, token_hash, token_prefix = generate_api_token()
    create_api_token(g.current_user["id"], name, token_hash, token_prefix)
    log_action("create", "api_token", entity_name=name)

    flash(f"API token created. Copy it now — it won't be shown again: {raw_token}", "success")
    return redirect(url_for("settings"))


@app.route("/settings/tokens/<int:token_id>/delete", methods=["POST"])
@auth_required()
def remove_token(token_id):
    delete_api_token(token_id, g.current_user["id"])
    flash("Token revoked", "success")
    return redirect(url_for("settings"))


if __name__ == "__main__":
    init_db()
    app.run(host=HOST, port=PORT, debug=DEBUG)
