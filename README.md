# Hermes Dashboard

LAN-accessible web dashboard for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Live system metrics, agent state, kanban board, and chat — all on one screen at port 2002.

## What it does

- **System** — CPU, RAM, disk, network, load (live, ~1Hz via SSE)
- **Agents** — gateway status, active sessions, cron job state
- **Kanban** — read-only view of `~/.hermes/kanban.db`. See what the agent is working on right now, with live status and event updates. Auto-archives Done cards at end of day.
- **Chat** — talk to Hermes through the dashboard, proxied through Hermes' built-in OpenAI-compatible API server

Modular: drop a new file in `collectors/` or `static/panels/` and you've got a new metric source or panel.

## Status

Implementation in progress. See [`docs/plans/`](docs/plans/) for the full plan.

## Prerequisites

The chat panel relies on Hermes' built-in `api_server` platform adapter. Set in `~/.hermes/.env`:

```
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
```

Then restart the gateway: `systemctl --user restart hermes-gateway`.

Verify it's up: `curl -s http://127.0.0.1:8642/health` should return JSON with status info.

## Run

```bash
pip install -e .
hermes-dashboard
```

## Install as a systemd user service

A unit file ships in `systemd/hermes-dashboard.service`. To install:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/hermes-dashboard.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hermes-dashboard
```

Verify it's running:

```bash
systemctl --user status hermes-dashboard
curl -s http://127.0.0.1:2002/healthz
```

The service binds `0.0.0.0:2002` so it's reachable from the LAN. If your
firewall blocks the port:

```bash
sudo firewall-cmd --add-port=2002/tcp --permanent && sudo firewall-cmd --reload
```

Make sure user services persist across logout / reboot:

```bash
loginctl show-user $USER | grep Linger    # expect Linger=yes
sudo loginctl enable-linger $USER          # if not
```

Logs go to the user journal:

```bash
journalctl --user -u hermes-dashboard -f
```

## Configuration

All config is via env vars (defaults in parens):

| Var | Default | What |
|---|---|---|
| `HERMES_DASHBOARD_HOST` | `0.0.0.0` | bind address |
| `HERMES_DASHBOARD_PORT` | `2002` | bind port |
| `HERMES_HOME` | `~/.hermes` | where Hermes state DBs live |
| `HERMES_API_SERVER_URL` | `http://127.0.0.1:8642/v1` | upstream chat endpoint |

## License

MIT
