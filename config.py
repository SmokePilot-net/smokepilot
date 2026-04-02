import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Database
DATABASE = os.environ.get("SPM_DATABASE", os.path.join(BASE_DIR, "smokepilot.db"))

# SmokePing integration
SMOKEPING_CONFIG_DIR = os.environ.get("SPM_CONFIG_DIR", "/etc/smokeping/config.d")
SMOKEPING_INCLUDE_FILE = os.environ.get("SPM_INCLUDE_FILE", "managed-targets")
SMOKEPING_PID_FILE = os.environ.get("SPM_PID_FILE", "/var/run/smokeping/smokeping.pid")
SMOKEPING_CGI_URL = os.environ.get("SPM_CGI_URL", "/smokeping/smokeping.cgi")

# Server
HOST = os.environ.get("SPM_HOST", "0.0.0.0")
PORT = int(os.environ.get("SPM_PORT", "5000"))
DEBUG = os.environ.get("SPM_DEBUG", "false").lower() in ("true", "1", "yes")

# Public URL (for agent install scripts)
PUBLIC_URL = os.environ.get("SPM_PUBLIC_URL", "")

# Auth
SECRET_KEY = os.environ.get("SPM_SECRET_KEY", "change-me-in-production")
ADMIN_USER = os.environ.get("SPM_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("SPM_ADMIN_PASSWORD", "admin")
