import os
import socket
import struct
import subprocess

# Standard Ubuntu/Debian paths for SmokePing CGI
CGI_PATHS = [
    "/usr/lib/cgi-bin/smokeping.cgi",
    "/usr/share/smokeping/smokeping.cgi",
]

# FastCGI socket path (set by install script when fcgiwrap is configured)
FCGI_SOCKET = os.environ.get("SPM_FCGI_SOCKET", "/run/smokeping-fcgi.sock")


def find_cgi():
    """Find the SmokePing CGI script on disk."""
    custom = os.environ.get("SPM_CGI_PATH")
    if custom and os.path.isfile(custom):
        return custom
    for path in CGI_PATHS:
        if os.path.isfile(path):
            return path
    return None


def call_cgi(query_string="", script_name="/smokeping/smokeping.cgi"):
    """Execute the SmokePing CGI. Uses FastCGI if available, falls back to subprocess.

    Returns (content_type, body).
    """
    # Try FastCGI first (persistent, fast)
    if os.path.exists(FCGI_SOCKET):
        try:
            return _call_fcgi(query_string, script_name)
        except Exception:
            pass  # Fall through to subprocess

    # Fallback: direct CGI subprocess (slow, cold start every time)
    return _call_subprocess(query_string, script_name)


def _call_fcgi(query_string, script_name):
    """Call SmokePing via FastCGI socket."""
    cgi_path = find_cgi()
    if not cgi_path:
        return "text/plain", b"SmokePing CGI not found."

    # Build FastCGI request
    params = {
        "REQUEST_METHOD": "GET",
        "QUERY_STRING": query_string,
        "SCRIPT_FILENAME": cgi_path,
        "SCRIPT_NAME": script_name,
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "5000",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "GATEWAY_INTERFACE": "CGI/1.1",
    }

    # Connect to FastCGI socket
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(15)
    sock.connect(FCGI_SOCKET)

    try:
        # Send BEGIN_REQUEST
        request_id = 1
        _fcgi_send_record(sock, 1, request_id, struct.pack(">HBxxxxx", 1, 0))  # FCGI_RESPONDER, keep_conn=0

        # Send PARAMS
        params_data = b""
        for key, val in params.items():
            params_data += _fcgi_encode_pair(key, val)
        _fcgi_send_record(sock, 4, request_id, params_data)  # FCGI_PARAMS
        _fcgi_send_record(sock, 4, request_id, b"")  # Empty PARAMS (end)

        # Send empty STDIN
        _fcgi_send_record(sock, 5, request_id, b"")  # FCGI_STDIN

        # Read response
        stdout_data = b""
        while True:
            rec_type, rec_id, content = _fcgi_read_record(sock)
            if rec_type == 6:  # FCGI_STDOUT
                if content:
                    stdout_data += content
            elif rec_type == 3:  # FCGI_END_REQUEST
                break
            elif rec_type == 7:  # FCGI_STDERR
                pass  # Ignore stderr
    finally:
        sock.close()

    return _parse_cgi_output(stdout_data)


def _fcgi_send_record(sock, rec_type, request_id, content):
    """Send a FastCGI record."""
    content_len = len(content)
    padding_len = (8 - (content_len % 8)) % 8
    header = struct.pack(">BBHHBx", 1, rec_type, request_id, content_len, padding_len)
    sock.sendall(header + content + b"\x00" * padding_len)


def _fcgi_read_record(sock):
    """Read a FastCGI record. Returns (type, request_id, content)."""
    header = _recv_exact(sock, 8)
    version, rec_type, request_id, content_len, padding_len = struct.unpack(">BBHHBx", header)
    content = _recv_exact(sock, content_len) if content_len else b""
    if padding_len:
        _recv_exact(sock, padding_len)  # discard padding
    return rec_type, request_id, content


def _recv_exact(sock, n):
    """Receive exactly n bytes from socket."""
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            break
        data += chunk
    return data


def _fcgi_encode_pair(name, value):
    """Encode a FastCGI name-value pair."""
    name = name.encode() if isinstance(name, str) else name
    value = value.encode() if isinstance(value, str) else value
    nlen = len(name)
    vlen = len(value)

    if nlen < 128:
        header = struct.pack("B", nlen)
    else:
        header = struct.pack(">I", nlen | 0x80000000)

    if vlen < 128:
        header += struct.pack("B", vlen)
    else:
        header += struct.pack(">I", vlen | 0x80000000)

    return header + name + value


def _call_subprocess(query_string, script_name):
    """Fallback: call SmokePing CGI as a subprocess (slow)."""
    cgi_path = find_cgi()
    if not cgi_path:
        return "text/plain", b"SmokePing CGI not found. Set SPM_CGI_PATH in your env file."

    env = os.environ.copy()
    env.update({
        "REQUEST_METHOD": "GET",
        "QUERY_STRING": query_string,
        "SCRIPT_NAME": script_name,
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "5000",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_HOST": "localhost",
        "GATEWAY_INTERFACE": "CGI/1.1",
    })

    try:
        result = subprocess.run(
            [cgi_path],
            env=env,
            capture_output=True,
            timeout=30,
        )
    except FileNotFoundError:
        return "text/plain", b"SmokePing CGI not executable or missing interpreter."
    except subprocess.TimeoutExpired:
        return "text/plain", b"SmokePing CGI timed out."

    if not result.stdout:
        stderr = result.stderr.decode("utf-8", errors="replace")
        return "text/plain", f"CGI returned no output. stderr: {stderr}".encode()

    return _parse_cgi_output(result.stdout)


def _parse_cgi_output(output):
    """Parse CGI output: split headers from body, extract content-type."""
    for sep in [b"\r\n\r\n", b"\n\n"]:
        if sep in output:
            header_block, body = output.split(sep, 1)
            break
    else:
        return "text/html", output

    content_type = "text/html"
    for line in header_block.split(b"\n"):
        line = line.strip()
        if line.lower().startswith(b"content-type:"):
            content_type = line.split(b":", 1)[1].strip().decode("utf-8", errors="replace")
            break

    return content_type, body
