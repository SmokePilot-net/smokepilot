# SmokePilot

Web-based monitoring manager for SmokePing. Add, edit and remove targets via a web UI, view smoke graphs, manage probe slaves — instead of editing config files manually.

## Features

- **Group/host tree** — organize targets in nested groups (e.g. Clients > Pepperstone > web01)
- **Smoke graphs** — SmokePing-style graphs with jitter visualization (classic, dark, and classic dark modes)
- **Click-drag zoom** — select a time range on any graph to zoom in
- **Multi-user RBAC** — admin, operator, viewer roles with wildcard group permissions
- **Slave management** — register remote probes, auto-distribute config via agent
- **REST API** — full API with Bearer token auth
- **Audit log** — track all changes (who, what, when)
- **Self-update** — update from the web UI with one click
- **Auto-deploy** — every change writes config and reloads SmokePing automatically
- **IPv6 supported** — SmokePing + FPing handle IPv4 and IPv6 natively

## Quick Install (Ubuntu/Debian)

Requires an existing SmokePing installation (`apt install smokeping`).

```bash
git clone https://github.com/SmokePilot-net/smokepilot.git /opt/smokepilot
cd /opt/smokepilot
sudo bash install.sh
```

Then:
1. Edit `/etc/smokepilot.env` and change the admin password
2. `sudo systemctl start smokepilot`
3. Open `http://your-server:5000`

## How It Works

SmokePilot does **not** modify your existing SmokePing config. It manages a separate `managed-targets` file that SmokePing loads via `@include`. Your existing targets are untouched.

## License

ISC
