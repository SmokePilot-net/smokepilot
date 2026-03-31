import os
import subprocess

# SmokePing's default data directory
DATA_DIR = os.environ.get("SPM_DATA_DIR", "/var/lib/smokeping")

# Colors matching SmokePing's smoke style
SMOKE_COLORS = [
    "#26ff00",  # 0/20 loss - bright green
    "#0000ff",  # 1/20 loss - blue
    "#0000ff",  # 2/20 loss
    "#0000ff",  # 3/20 loss
    "#ff00ff",  # 4/20 loss - magenta
    "#ff00ff",  # 10/20 loss
    "#ff0000",  # 19/20 loss - red
]

# Percentile shading for the "smoke" effect
SMOKE_ALPHAS = [
    ("ping20", "#00000020"),
    ("ping19", "#00000020"),
    ("ping18", "#00000020"),
    ("ping17", "#00000020"),
    ("ping16", "#00000020"),
    ("ping15", "#00000020"),
    ("ping14", "#00000020"),
    ("ping13", "#00000020"),
    ("ping12", "#00000020"),
    ("ping11", "#00000020"),
    ("ping10", "#00000020"),
    ("ping9", "#00000020"),
    ("ping8", "#00000020"),
    ("ping7", "#00000020"),
    ("ping6", "#00000020"),
    ("ping5", "#00000020"),
    ("ping4", "#00000020"),
    ("ping3", "#00000020"),
    ("ping2", "#00000020"),
    ("ping1", "#00000020"),
]

# Display range to seconds mapping
RANGE_MAP = {
    "3h": 10800,
    "30h": 108000,
    "10d": 864000,
    "400d": 34560000,
}


def find_rrd(target_path):
    """Find the RRD file for a given target path like 'Servers.proxmox'."""
    parts = target_path.split(".")
    rrd_path = os.path.join(DATA_DIR, *parts) + ".rrd"
    if os.path.isfile(rrd_path):
        return rrd_path
    return None


def render_graph(target_path, display_range="3h", width=800, height=250):
    """Render a SmokePing-style graph using rrdtool. Returns (content_type, png_data)."""
    rrd_path = find_rrd(target_path)
    if not rrd_path:
        return _error_image(f"No data found for {target_path}")

    seconds = RANGE_MAP.get(display_range, 10800)
    label = target_path.split(".")[-1]

    cmd = [
        "rrdtool", "graph", "-",  # output to stdout
        "--start", f"-{seconds}",
        "--end", "now",
        "--width", str(width),
        "--height", str(height),
        "--title", label,
        "--vertical-label", "Seconds",
        "--lower-limit", "0",
        "--imgformat", "PNG",
        "--font", "DEFAULT:10:",
        "--color", "BACK#ffffff",
        "--color", "CANVAS#ffffff",
        "--color", "GRID#e0e0e0",
        "--color", "MGRID#c0c0c0",
        "--color", "FONT#333333",
        "--color", "ARROW#333333",
    ]

    # Define all ping data sources and the smoke area fills
    for i in range(1, 21):
        ds_name = f"ping{i}"
        cmd.append(f"DEF:{ds_name}={rrd_path}:{ds_name}:AVERAGE")

    # Draw smoke (area fills from highest to lowest percentile)
    for i in range(20, 0, -1):
        ds_name = f"ping{i}"
        color = "#c8e6c8" if i <= 10 else "#e6c8c8"
        if i == 20:
            cmd.append(f"AREA:{ds_name}{color}:")
        else:
            cmd.append(f"AREA:{ds_name}{color}:")

    # Median line on top
    cmd.append(f"DEF:median={rrd_path}:median:AVERAGE")
    cmd.append("LINE2:median#00aa00:median rtt")

    # Loss data
    cmd.append(f"DEF:loss={rrd_path}:loss:AVERAGE")

    # Stats in legend
    cmd.append("GPRINT:median:LAST:  now\\: %6.2lf %ss")
    cmd.append("GPRINT:median:AVERAGE:avg\\: %6.2lf %ss")
    cmd.append("GPRINT:median:MAX:max\\: %6.2lf %ss")
    cmd.append("GPRINT:median:MIN:min\\: %6.2lf %ss\\n")
    cmd.append("GPRINT:loss:LAST:packet loss\\: %5.1lf %%")
    cmd.append("COMMENT:   probe\\: 20 ICMP pings every 300s\\n")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout:
            return "image/png", result.stdout
        stderr = result.stderr.decode("utf-8", errors="replace")
        return _error_image(f"rrdtool error: {stderr}")
    except FileNotFoundError:
        return _error_image("rrdtool not found — install rrdtool")
    except subprocess.TimeoutExpired:
        return _error_image("Graph rendering timed out")


def _error_image(message):
    """Return a simple error message as plain text (fallback)."""
    return "text/plain", message.encode("utf-8")
