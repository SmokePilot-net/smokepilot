import re
import functools
from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from database import (
    init_db, get_tree, get_groups, get_group, create_group, update_group, delete_group,
    get_host, create_host, update_host, delete_host
)
from generator import generate_config, write_config, reload_smokeping
from importer import parse_targets_file, import_to_database
from updater import get_current_version, check_for_updates, apply_update, restart_service
from graph_renderer import render_graph
from config import SECRET_KEY, ADMIN_USER, ADMIN_PASSWORD, HOST, PORT, DEBUG

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Sanitize names for SmokePing (alphanumeric + underscore only)
VALID_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def deploy_and_reload():
    """Write config and reload SmokePing. Called after every change."""
    try:
        write_config()
        success, msg = reload_smokeping()
        if not success:
            flash(f"Config written but reload failed: {msg}", "error")
    except Exception as e:
        flash(f"Auto-deploy failed: {e}", "error")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USER and request.form["password"] == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("Invalid credentials", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


@app.context_processor
def inject_globals():
    return {"smokeping_cgi_url": url_for("smokeping_cgi_proxy")}


# --- Dashboard (graphs) ---

@app.route("/")
@login_required
def dashboard():
    tree = get_tree()
    return render_template("dashboard.html", tree=tree)


@app.route("/host/<path:target_path>")
@login_required
def host_detail(target_path):
    return render_template("host_detail.html", target_path=target_path)


# --- Graph rendering ---

@app.route("/smokeping-cgi")
@login_required
def smokeping_cgi_proxy():
    target = request.args.get("target", "")
    display_range = request.args.get("displayrange", "3h")
    start = request.args.get("start")
    end = request.args.get("end")
    content_type, body = render_graph(target, display_range, start=start, end=end)
    return Response(body, content_type=content_type, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    })


# --- Manage (target administration) ---

@app.route("/manage")
@login_required
def manage():
    tree = get_tree()
    groups = get_groups()
    return render_template("manage.html", tree=tree, groups=groups)


@app.route("/group/add", methods=["POST"])
@login_required
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
        flash(f"Group '{name}' created", "success")
        deploy_and_reload()
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("manage"))


@app.route("/group/<int:group_id>/edit", methods=["POST"])
@login_required
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
        flash(f"Group '{name}' updated", "success")
        deploy_and_reload()
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("manage"))


@app.route("/group/<int:group_id>/delete", methods=["POST"])
@login_required
def remove_group(group_id):
    group = get_group(group_id)
    if group:
        delete_group(group_id)
        flash(f"Group '{group['name']}' deleted (including all hosts and subgroups)", "success")
        deploy_and_reload()
    return redirect(url_for("manage"))


@app.route("/host/add", methods=["POST"])
@login_required
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
        flash(f"Host '{name}' ({host}) added", "success")
        deploy_and_reload()
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("manage"))


@app.route("/host/<int:host_id>/edit", methods=["POST"])
@login_required
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
        flash(f"Host '{name}' updated", "success")
        deploy_and_reload()
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("manage"))


@app.route("/host/<int:host_id>/delete", methods=["POST"])
@login_required
def remove_host(host_id):
    host = get_host(host_id)
    if host:
        delete_host(host_id)
        flash(f"Host '{host['name']}' deleted", "success")
        deploy_and_reload()
    return redirect(url_for("manage"))


# --- Settings ---

@app.route("/settings")
@login_required
def settings():
    current = get_current_version()
    has_updates, info = check_for_updates()
    config = generate_config()
    # Preview what would be imported
    tree, parse_error = parse_targets_file()
    return render_template("settings.html", current=current, has_updates=has_updates,
                           info=info, config=config, import_tree=tree, parse_error=parse_error)


@app.route("/settings/import", methods=["POST"])
@login_required
def import_targets():
    tree, error = parse_targets_file()
    if error:
        flash(f"Import failed: {error}", "error")
        return redirect(url_for("settings"))

    groups_added, hosts_added, skipped = import_to_database(tree)
    flash(f"Imported {groups_added} groups and {hosts_added} hosts ({skipped} skipped/duplicates)", "success")
    if groups_added > 0 or hosts_added > 0:
        deploy_and_reload()
    return redirect(url_for("settings"))


@app.route("/settings/update", methods=["POST"])
@login_required
def do_update():
    success, message = apply_update()
    if success:
        flash(f"Updated successfully. Restarting in a few seconds... {message}", "success")
        restart_service()
    else:
        flash(f"Update failed: {message}", "error")
    return redirect(url_for("settings"))


@app.route("/settings/deploy", methods=["POST"])
@login_required
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


if __name__ == "__main__":
    init_db()
    app.run(host=HOST, port=PORT, debug=DEBUG)
