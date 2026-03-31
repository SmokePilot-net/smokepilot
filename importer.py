import re
import os
from config import SMOKEPING_CONFIG_DIR


def parse_targets_file(filepath=None):
    """Parse a SmokePing Targets config file and return a tree structure.

    SmokePing format:
        + GroupName          (depth 1)
        menu = Display Name
        title = Title
        host = 1.2.3.4       (only on leaf nodes)

        ++ SubGroup          (depth 2)
        +++ Host             (depth 3)

    Returns a list of nodes, each being:
        {"name": str, "title": str, "menu": str, "host": str|None,
         "probe": str|None, "children": [...]}
    """
    if filepath is None:
        filepath = os.path.join(SMOKEPING_CONFIG_DIR, "Targets")

    if not os.path.isfile(filepath):
        return [], f"File not found: {filepath}"

    with open(filepath, "r") as f:
        lines = f.readlines()

    # Parse into a flat list of entries with their depth
    entries = []
    current = None
    current_depth = 0

    for line in lines:
        line = line.rstrip("\n\r")
        stripped = line.strip()

        # Skip empty lines, comments, and @include directives
        if not stripped or stripped.startswith("#") or stripped.startswith("@include"):
            continue

        # Skip the *** Targets *** header
        if stripped.startswith("***"):
            continue

        # Check for a node definition (+ Name, ++ Name, etc.)
        match = re.match(r"^(\++)\s+(\S+)", stripped)
        if match:
            # Save previous entry
            if current:
                entries.append((current_depth, current))

            depth = len(match.group(1))
            name = match.group(2)
            current = {"name": name, "title": name, "menu": name, "host": None, "probe": None}
            current_depth = depth
            continue

        # Parse key = value properties for the current node
        if current and "=" in stripped:
            key, _, value = stripped.partition("=")
            key = key.strip().lower()
            value = value.strip()

            if key == "title":
                current["title"] = value
            elif key == "menu":
                current["menu"] = value
            elif key == "host":
                current["host"] = value
            elif key == "probe":
                current["probe"] = value

        # Top-level properties (before any + node) like "probe = FPing"
        if not current and "=" in stripped:
            # Skip top-level config (probe, menu, title, remark)
            continue

    # Don't forget the last entry
    if current:
        entries.append((current_depth, current))

    # Build tree from flat list
    tree = _build_tree(entries)
    return tree, None


def _build_tree(entries):
    """Convert a flat list of (depth, node) into a nested tree."""
    root = []
    stack = [(0, root)]  # (depth, children_list)

    for depth, node in entries:
        node["children"] = []

        # Pop stack until we find the right parent level
        while len(stack) > 1 and stack[-1][0] >= depth:
            stack.pop()

        parent_list = stack[-1][1]
        parent_list.append(node)
        stack.append((depth, node["children"]))

    return root


def import_to_database(tree, parent_id=None):
    """Import parsed targets tree into the database.

    Returns (groups_added, hosts_added, skipped).
    """
    from database import create_group, create_host, get_groups, get_hosts

    groups_added = 0
    hosts_added = 0
    skipped = 0

    # Get existing names to avoid duplicates
    existing_groups = {g["name"] for g in get_groups()}
    existing_hosts = set()
    for h in get_hosts():
        existing_hosts.add((h["name"], h["group_id"]))

    for node in tree:
        if node["host"]:
            # It's a host (leaf node) — needs a parent group
            if parent_id is None:
                # Host at top level without a group — skip or create a default group
                skipped += 1
                continue
            try:
                create_host(
                    name=node["name"],
                    host=node["host"],
                    group_id=parent_id,
                    title=node["title"] or node["menu"] or node["name"],
                    probe=node["probe"] or "FPing",
                )
                hosts_added += 1
            except Exception:
                skipped += 1
        else:
            # It's a group
            if node["name"] in existing_groups and parent_id is None:
                # Top-level group already exists — skip but process children
                from database import get_groups as _gg
                group_id = None
                for g in _gg():
                    if g["name"] == node["name"] and g["parent_id"] == parent_id:
                        group_id = g["id"]
                        break
                if group_id:
                    sub_g, sub_h, sub_s = import_to_database(node["children"], group_id)
                    groups_added += sub_g
                    hosts_added += sub_h
                    skipped += sub_s + 1
                    continue

            try:
                create_group(
                    name=node["name"],
                    title=node["title"] or node["menu"] or node["name"],
                    parent_id=parent_id,
                )
                groups_added += 1

                # Find the group we just created to get its ID
                from database import get_groups as _gg2
                group_id = None
                for g in _gg2():
                    if g["name"] == node["name"] and g["parent_id"] == parent_id:
                        group_id = g["id"]
                        break

                if group_id and node["children"]:
                    sub_g, sub_h, sub_s = import_to_database(node["children"], group_id)
                    groups_added += sub_g
                    hosts_added += sub_h
                    skipped += sub_s

            except Exception:
                skipped += 1

    return groups_added, hosts_added, skipped
