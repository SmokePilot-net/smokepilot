# SmokePilot

Web-based monitoring manager for SmokePing. Add, edit and remove targets via a web UI, view smoke graphs — instead of editing config files manually.

## Features

- **Group/host tree** — organize targets in nested groups (e.g. Clients > Cities > web01)
- **Smoke graphs** — SmokePing-style graphs with jitter visualization (Light, Dark, Classic Dark, SmokePing Classic)
- **Click-drag zoom** — select a time range on any graph to zoom in
- **Host status** — live DOWN / packet loss / stale indicators on the dashboard
- **Multi-user** — admin and viewer roles with group-level permissions
- **Read-only REST API** — with Bearer token auth (1 token per user)
- **Audit log** — track all changes (who, what, when)
- **Self-update** — update from the web UI with one click
- **Auto-deploy** — every change writes config and reloads SmokePing automatically
- **Import** — import existing targets from SmokePing's config file
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

SmokePilot manages a separate `managed-targets` file that SmokePing loads via `@include`. You can import your existing targets from SmokePing's config, and from then on manage everything through the web UI.

## SmokePilot Pro

For slave probe management, write API, wildcard permissions, operator role, and advanced graph styles — see [SmokePilot Pro](https://smokepilot.net).

## License

ISC
