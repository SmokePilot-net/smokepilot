import os
import subprocess

# SmokePing's default data directory
DATA_DIR = os.environ.get("SPM_DATA_DIR", "/var/lib/smokeping")

# Display range presets
RANGE_PRESETS = {
    "3h": 10800,
    "30h": 108000,
    "10d": 864000,
    "400d": 34560000,
}

# SmokePing's loss color scheme: maps loss bucket to (line_color, smoke_color)
# Loss is stored as fraction (0.0 = no loss, 1.0 = 100% loss)
# With 20 pings: 0/20=green, 1/20=blue, 2-3/20=blue, 4-10/20=magenta, 11+/20=red
LOSS_COLORS = [
    (0, "#00ff00", "#00ff0040"),       # 0 loss - green
    (1, "#0000ff", "#0000ff40"),       # 1/20 loss - blue
    (2, "#0000cc", "#0000cc40"),       # 2/20
    (3, "#0000aa", "#0000aa40"),       # 3/20
    (4, "#ff00ff", "#ff00ff40"),       # 4/20 - magenta
    (10, "#ff0088", "#ff008840"),      # 10/20
    (19, "#ff0000", "#ff000040"),      # 19/20 - red
]

# Smoke percentile colors - graduated opacity for the cloud effect
# Outermost (ping1, ping20) = lightest, innermost (ping10, ping11) = darkest
SMOKE_PAIRS = [
    # (low_ping, high_ping, color) - symmetrical pairs from outside in
    ("ping1", "ping20", "#aaffaa18"),
    ("ping2", "ping19", "#88ee8820"),
    ("ping3", "ping18", "#66dd6628"),
    ("ping4", "ping17", "#44cc4430"),
    ("ping5", "ping16", "#22bb2238"),
    ("ping6", "ping15", "#11aa1140"),
    ("ping7", "ping14", "#00990048"),
    ("ping8", "ping13", "#00880050"),
    ("ping9", "ping12", "#007700580"),
    ("ping10", "ping11", "#00660060"),
]


def find_rrd(target_path):
    """Find the RRD file for a given target path like 'Servers.proxmox'."""
    parts = target_path.split(".")
    rrd_path = os.path.join(DATA_DIR, *parts) + ".rrd"
    if os.path.isfile(rrd_path):
        return rrd_path
    return None


def render_graph(target_path, display_range="3h", width=800, height=250,
                 start=None, end=None, dark_mode=True):
    """Render a SmokePing-style graph with smoke effect using rrdtool."""
    rrd_path = find_rrd(target_path)
    if not rrd_path:
        return _error_image(f"No data found for {target_path}")

    # Time range
    if start and end:
        time_start = str(start)
        time_end = str(end)
    else:
        seconds = RANGE_PRESETS.get(display_range, 10800)
        time_start = f"-{seconds}"
        time_end = "now"

    label = target_path.split(".")[-1]

    # Color scheme based on mode
    if dark_mode:
        colors = {
            "back": "#1a1a2e",
            "canvas": "#16213e",
            "grid": "#0f346066",
            "mgrid": "#0f346099",
            "font": "#e0e0e0",
            "arrow": "#e0e0e0",
            "axis": "#0f3460",
            "frame": "#0f3460",
            "median": "#00ee00",
            "smoke_base": "00cc00",
        }
    else:
        colors = {
            "back": "#ffffff",
            "canvas": "#ffffff",
            "grid": "#e0e0e0",
            "mgrid": "#c0c0c0",
            "font": "#333333",
            "arrow": "#333333",
            "axis": "#cccccc",
            "frame": "#cccccc",
            "median": "#00aa00",
            "smoke_base": "009900",
        }

    cmd = [
        "rrdtool", "graph", "-",
        "--start", time_start,
        "--end", time_end,
        "--width", str(width),
        "--height", str(height),
        "--title", label,
        "--vertical-label", "Seconds",
        "--lower-limit", "0",
        "--alt-autoscale-max",
        "--imgformat", "PNG",
        "--font", "DEFAULT:10:",
        "--font", "TITLE:12:",
        "--border", "0",
        "--color", f"BACK{colors['back']}",
        "--color", f"CANVAS{colors['canvas']}",
        "--color", f"GRID{colors['grid']}",
        "--color", f"MGRID{colors['mgrid']}",
        "--color", f"FONT{colors['font']}",
        "--color", f"ARROW{colors['arrow']}",
        "--color", f"AXIS{colors['axis']}",
        "--color", f"FRAME{colors['frame']}",
    ]

    # Define all data sources
    for i in range(1, 21):
        cmd.append(f"DEF:ping{i}={rrd_path}:ping{i}:AVERAGE")
    cmd.append(f"DEF:median={rrd_path}:median:AVERAGE")
    cmd.append(f"DEF:loss={rrd_path}:loss:AVERAGE")

    # Build the smoke effect using overlapping areas
    # Draw from highest percentile (lightest) to lowest (darkest).
    # Each successive AREA overwrites the center, creating the layered
    # smoke look where the core (near median) is darkest.
    sb = colors["smoke_base"]

    # Outermost percentiles (lightest) drawn first, then overwritten by inner ones
    smoke_layers = [
        ("ping20", "18"), ("ping19", "20"), ("ping18", "28"), ("ping17", "30"),
        ("ping16", "38"), ("ping15", "40"), ("ping14", "48"), ("ping13", "50"),
        ("ping12", "58"), ("ping11", "60"),
        ("ping10", "60"), ("ping9", "58"), ("ping8", "50"), ("ping7", "48"),
        ("ping6", "40"), ("ping5", "38"), ("ping4", "30"), ("ping3", "28"),
        ("ping2", "20"), ("ping1", "18"),
    ]

    for ds, opacity in smoke_layers:
        cmd.append(f"AREA:{ds}#{sb}{opacity}:")

    # Median line on top - the sharp line through the smoke
    cmd.append(f"LINE1:median{colors['median']}:median rtt")

    # Loss color overlay using CDEFs
    # When loss > 0, draw the median line in the appropriate loss color
    cmd.append("CDEF:loss1=loss,0,GT,loss,0.1,LE,*,median,UNKN,IF")
    cmd.append("CDEF:loss2=loss,0.1,GT,loss,0.2,LE,*,median,UNKN,IF")
    cmd.append("CDEF:loss3=loss,0.2,GT,loss,0.5,LE,*,median,UNKN,IF")
    cmd.append("CDEF:loss4=loss,0.5,GT,median,UNKN,IF")

    cmd.append("LINE2:loss1#0000ff:")
    cmd.append("LINE2:loss2#ff00ff:")
    cmd.append("LINE2:loss3#ff0000:")
    cmd.append("LINE2:loss4#ff0000:")

    # Stats legend
    cmd.append("COMMENT: \\n")
    cmd.append("GPRINT:median:LAST:  now\\: %6.2lf %ss")
    cmd.append("GPRINT:median:AVERAGE:  avg\\: %6.2lf %ss")
    cmd.append("GPRINT:median:MAX:  max\\: %6.2lf %ss")
    cmd.append("GPRINT:median:MIN:  min\\: %6.2lf %ss\\n")
    cmd.append("GPRINT:loss:LAST:  packet loss\\: %5.1lf %%\\n")
    cmd.append("COMMENT:  probe\\: 20 ICMP pings every 300s\\n")

    # Loss color legend
    cmd.append("COMMENT: \\n")
    cmd.append("COMMENT:  loss\\:")
    cmd.append(f"AREA:ping1#{sb}5c:  0/{_get_pings(rrd_path)}")
    cmd.append("LINE1:loss1#0000ff:  1+")
    cmd.append("COMMENT:  ")

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


def _get_pings(rrd_path):
    """Get the number of pings from the RRD (count of pingN data sources)."""
    try:
        result = subprocess.run(
            ["rrdtool", "info", rrd_path],
            capture_output=True, text=True, timeout=5
        )
        count = 0
        for line in result.stdout.split("\n"):
            if line.startswith("ds[ping") and ".index" in line:
                count += 1
        return str(count) if count else "20"
    except Exception:
        return "20"


def _error_image(message):
    """Return error as plain text fallback."""
    return "text/plain", message.encode("utf-8")
