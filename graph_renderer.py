import os
import subprocess
import time

# SmokePing's default data directory
DATA_DIR = os.environ.get("SPM_DATA_DIR", "/var/lib/smokeping")

# Display range presets
RANGE_PRESETS = {
    "3h": 10800,
    "30h": 108000,
    "10d": 864000,
    "400d": 34560000,
}

# Graph style definitions
STYLES = {
    "light": {
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
        "smoke_type": "tight",
    },
    "dark": {
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
        "smoke_type": "filled",
    },
    "classic_dark": {
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
        "smoke_type": "tight",
    },
}

# Default style
DEFAULT_STYLE = os.environ.get("SPM_GRAPH_STYLE", "light")


def find_rrd(target_path):
    """Find the RRD file for a given target path like 'Servers.proxmox'."""
    parts = target_path.split(".")
    rrd_path = os.path.join(DATA_DIR, *parts) + ".rrd"
    if os.path.isfile(rrd_path):
        return rrd_path
    return None


def render_graph(target_path, display_range="3h", width=800, height=250,
                 start=None, end=None, style=None):
    """Render a SmokePing-style graph using rrdtool, or pass through CGI for classic mode."""
    if style is None:
        style = DEFAULT_STYLE

    # SmokePing Classic: use the original CGI renderer
    if style == "smokeping_classic":
        return _render_via_cgi(target_path, display_range)

    rrd_path = find_rrd(target_path)
    if not rrd_path:
        return _error_image(f"No data found for {target_path}")

    colors = STYLES.get(style, STYLES["light"])

    # Time range
    if start and end:
        time_start = str(start)
        time_end = str(end)
    else:
        seconds = RANGE_PRESETS.get(display_range, 10800)
        time_start = f"-{seconds}"
        time_end = "now"

    label = target_path.split(".")[-1]

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

    sb = colors["smoke_base"]

    if colors["smoke_type"] == "tight":
        _add_tight_smoke(cmd, sb, colors)
    else:
        _add_filled_smoke(cmd, sb, colors)

    # Median line on top
    cmd.append(f"LINE1:median{colors['median']}:median rtt")

    # Loss color overlay
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

    # Loss color legend
    pings = _get_pings(rrd_path)
    cmd.append("COMMENT:  loss color\\:")
    cmd.append(f"AREA:ping1#{sb}80:  0/{pings}")
    cmd.append(f"LINE1:loss1#0000ff:  1/{pings}")
    cmd.append(f"LINE1:loss2#ff00ff:  4/{pings}")
    cmd.append(f"LINE1:loss3#ff0000:  10/{pings}")
    cmd.append(f"LINE1:loss4#ff0000:  19/{pings}\\n")

    # Probe info + end timestamp
    end_time = time.strftime("%a %b %d %H\\:%M\\:%S %Y")
    cmd.append("COMMENT:  probe\\: 20 ICMP pings every 300s")
    cmd.append(f"COMMENT:                          end\\: {end_time}\\n")

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


def _add_tight_smoke(cmd, sb, colors):
    """SmokePing classic style: smoke wraps tightly around the median.

    Uses CDEF+STACK to only draw the area between each successive percentile,
    creating a narrow cloud that shows jitter distribution around the median.
    """
    is_dark = colors["back"] != "#ffffff"

    # Base: draw ping1 (fastest) as invisible area to set the baseline
    cmd.append("AREA:ping1#00000000:")

    # Stack the differences between successive percentiles
    # Opacity peaks at the median (ping10-11) and fades toward the edges
    if is_dark:
        opacities = [
            "30", "38", "40", "48", "50",   # ping2-6
            "60", "70", "80", "90", "a0",   # ping7-11 (dense core)
            "90", "80", "70", "60", "50",   # ping12-16
            "48", "40", "38", "30",          # ping17-20
        ]
    else:
        opacities = [
            "10", "15", "1a", "20", "28",   # ping2-6
            "30", "40", "50", "60", "70",   # ping7-11 (dense core)
            "60", "50", "40", "30", "28",   # ping12-16
            "20", "1a", "15", "10",          # ping17-20
        ]

    for i in range(2, 21):
        opacity = opacities[i - 2]
        # Difference between this percentile and the previous, clamped to 0
        cmd.append(f"CDEF:smoke{i}=ping{i},ping{i - 1},-,0,MAX")
        cmd.append(f"AREA:smoke{i}#{sb}{opacity}::STACK")


def _add_filled_smoke(cmd, sb, colors):
    """Filled style: overlapping areas from baseline, denser at center."""
    smoke_layers = [
        ("ping20", "40"), ("ping19", "48"), ("ping18", "50"), ("ping17", "58"),
        ("ping16", "60"), ("ping15", "68"), ("ping14", "70"), ("ping13", "78"),
        ("ping12", "80"), ("ping11", "88"),
        ("ping10", "88"), ("ping9", "80"), ("ping8", "78"), ("ping7", "70"),
        ("ping6", "68"), ("ping5", "60"), ("ping4", "58"), ("ping3", "50"),
        ("ping2", "48"), ("ping1", "40"),
    ]

    for ds, opacity in smoke_layers:
        cmd.append(f"AREA:{ds}#{sb}{opacity}:")


def _get_pings(rrd_path):
    """Get the number of pings from the RRD."""
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


def _render_via_cgi(target_path, display_range):
    """Render using SmokePing's original CGI script."""
    from smokeping_proxy import call_cgi
    query = f"target={target_path}&displaymode=a"
    if display_range:
        query += f"&displayrange={display_range}"
    return call_cgi(query)


def _error_image(message):
    """Return error as plain text fallback."""
    return "text/plain", message.encode("utf-8")
