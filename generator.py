import os
import signal
from database import get_tree
from config import SMOKEPING_CONFIG_DIR, SMOKEPING_INCLUDE_FILE, SMOKEPING_PID_FILE


def generate_config():
    """Generate SmokePing Targets @include file from the database tree."""
    tree = get_tree()
    lines = [
        "# ==========================================",
        "# Managed by smokeping-manager — do not edit",
        "# ==========================================",
        "",
    ]
    _render_tree(tree, lines, depth=1)
    return "\n".join(lines) + "\n"


def _render_tree(nodes, lines, depth):
    """Recursively render tree nodes as SmokePing config."""
    prefix = "+" * depth
    for node in nodes:
        if node["type"] == "group":
            lines.append(f"{prefix} {node['name']}")
            lines.append(f"menu = {node['title']}")
            lines.append(f"title = {node['title']}")
            lines.append("")

            # Hosts in this group
            host_prefix = "+" * (depth + 1)
            for host in node.get("hosts", []):
                lines.append(f"{host_prefix} {host['name']}")
                lines.append(f"menu = {host['title']}")
                lines.append(f"title = {host['title']}")
                lines.append(f"host = {host['host']}")
                if host.get("probe") and host["probe"] != "FPing":
                    lines.append(f"probe = {host['probe']}")
                lines.append("")

            # Subgroups
            _render_tree(node.get("children", []), lines, depth + 1)


def write_config():
    """Write the generated config to the SmokePing include file."""
    config = generate_config()
    filepath = os.path.join(SMOKEPING_CONFIG_DIR, SMOKEPING_INCLUDE_FILE)
    os.makedirs(SMOKEPING_CONFIG_DIR, exist_ok=True)
    with open(filepath, "w") as f:
        f.write(config)
    return filepath


def reload_smokeping():
    """Send HUP to SmokePing to reload config. Returns (success, message)."""
    try:
        with open(SMOKEPING_PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGHUP)
        return True, f"SmokePing (pid {pid}) reloaded"
    except FileNotFoundError:
        return False, f"PID file not found: {SMOKEPING_PID_FILE}"
    except ProcessLookupError:
        return False, "SmokePing process not running (stale PID file)"
    except PermissionError:
        return False, "Permission denied — run as root or add to smokeping group"
    except Exception as e:
        return False, str(e)
