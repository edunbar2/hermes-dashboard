# Hermes Dashboard

LAN-accessible web dashboard for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Live system metrics, agent state, kanban board, and chat — all on one screen at port 2002.

## What it does

- **System** — CPU, RAM, disk, network, load (live, ~1Hz via SSE)
- **Agents** — gateway status, active sessions, cron job state
- **Kanban** — read-only view of `~/.hermes/kanban.db`. See what the agent is working on right now, with live status and event updates. Auto-archives Done cards at end of day.
- **Chat** — talk to Hermes through the dashboard, proxied through Hermes' built-in OpenAI-compatible API server

Modular: drop a new file in `collectors/` or `static/panels/` and you've got a new metric source or panel.

## Status

**v0.1.0** — running as a systemd user service on port 2002. System metrics, agent state, kanban board, and chat all live. See [`docs/plans/`](docs/plans/) for the original plan and the changelog for what shipped.

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

## Extending

### New metric collector

A collector is anything with a `name` attribute and an async `collect()`
that returns a JSON-serializable dict. The `envelope()` helper wraps the
payload with `{name, ts, data}` so collectors stay consistent on the wire.

```python
# src/hermes_dashboard/collectors/my_collector.py
from .base import envelope

class MyCollector:
    name = "my_metric"

    async def collect(self) -> dict:
        return envelope(self.name, {"value": 42})
```

Register it in `collectors/__init__.py`:

```python
from .my_collector import MyCollector
# ... in build_registry():
MyCollector.name: MyCollector(),
```

Then expose it via a route under `api/` (or attach it to an existing
aggregate like `/api/hermes/status`).

### New UI panel

Each panel is a vanilla ES module under `static/panels/`. No build step.

1. Add `<section class="panel" data-panel="myname"><h2>…</h2><div class="panel-body"></div></section>` to `index.html`.
2. Create `static/panels/myname.js` exporting `async function mountMyPanel(root)`.
3. Register it in `static/app.js`:

```js
import { mountMyPanel } from "/static/panels/myname.js";
const PANELS = {
  // ... existing panels
  myname: mountMyPanel,
};
```

Panels can fetch with `fetch('/api/...')` or stream via `EventSource`.
The system + kanban panels are good references for SSE.

### Read-only state access

If you need to read a Hermes state DB, open it `mode=ro` so you can't
accidentally mutate agent state:

```python
sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
```

Writes belong in the dashboard's own `~/.hermes/dashboard-state.json`
via `src/hermes_dashboard/state.py`.

## License

MIT
