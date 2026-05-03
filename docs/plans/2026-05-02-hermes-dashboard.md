# Hermes Agent Dashboard Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** A LAN-accessible web dashboard on port 2002 showing system + Hermes stats and offering a chat interface to start new agent conversations.

**Architecture:** Single FastAPI service that does four things — (1) serves a static HTML/JS frontend, (2) exposes a small JSON API for system + Hermes metrics, (3) reads Hermes' kanban DB read-only to surface what the agent is working on, (4) proxies chat traffic to the Hermes gateway's existing `api_server` platform adapter (already built in, OpenAI-compatible). Modular design: each metric collector and each "panel" is a self-contained module so we can extend later. Runs as a systemd user service like the gateway. Bound to 0.0.0.0:2002 with no auth (LAN-trusted, per Eric).

**Tech Stack:** Python 3.11+, FastAPI + uvicorn, psutil for system metrics, aiohttp for upstream chat proxy, SSE for live updates, vanilla HTML/JS frontend (no build step — simpler to extend, no node toolchain inside the dashboard repo).

**Layout:** `~/hermes-dashboard/`
```
hermes-dashboard/
├── pyproject.toml
├── README.md
├── src/hermes_dashboard/
│   ├── __init__.py
│   ├── __main__.py            # uvicorn entry point
│   ├── config.py              # env vars, port, hermes paths
│   ├── app.py                 # FastAPI app factory, route registration
│   ├── api/
│   │   ├── __init__.py
│   │   ├── system.py          # /api/system/{metrics,stream}
│   │   ├── hermes.py          # /api/hermes/{status,sessions,cron,gateway}
│   │   ├── kanban.py          # /api/kanban/{board,tasks,events}  (read-only)
│   │   └── chat.py            # /api/chat/{send,stream}  (proxies to api_server)
│   ├── collectors/            # extension point — drop a new file here to add metrics
│   │   ├── __init__.py
│   │   ├── base.py            # Collector protocol
│   │   ├── system_resources.py
│   │   ├── hermes_status.py
│   │   ├── hermes_sessions.py
│   │   ├── hermes_cron.py
│   │   ├── hermes_gateway.py
│   │   └── hermes_kanban.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       ├── style.css
│       └── panels/            # extension point — drop a new JS module to add a panel
│           ├── system.js
│           ├── agents.js
│           ├── kanban.js
│           └── chat.js
├── tests/
│   ├── conftest.py
│   ├── test_collectors.py
│   ├── test_api_system.py
│   ├── test_api_hermes.py
│   ├── test_api_kanban.py
│   ├── test_api_chat.py
│   └── test_app_smoke.py
└── systemd/
    └── hermes-dashboard.service
```

---

## Task 1: Bootstrap project layout and dependencies

**Objective:** Create the directory tree, `pyproject.toml`, and a runnable empty FastAPI app.

**Files:**
- Create: `~/hermes-dashboard/pyproject.toml`
- Create: `~/hermes-dashboard/src/hermes_dashboard/__init__.py`
- Create: `~/hermes-dashboard/src/hermes_dashboard/__main__.py`
- Create: `~/hermes-dashboard/src/hermes_dashboard/app.py`
- Create: `~/hermes-dashboard/src/hermes_dashboard/config.py`
- Create: `~/hermes-dashboard/README.md`
- Create: `~/hermes-dashboard/.gitignore`
- Create: `~/hermes-dashboard/tests/__init__.py`
- Create: `~/hermes-dashboard/tests/conftest.py`

**Step 1: Create directory tree**

```bash
mkdir -p ~/hermes-dashboard/src/hermes_dashboard/{api,collectors,static/panels}
mkdir -p ~/hermes-dashboard/{tests,systemd}
cd ~/hermes-dashboard
git init -b main
```

**Step 2: Write `pyproject.toml`**

```toml
[project]
name = "hermes-dashboard"
version = "0.1.0"
description = "Web dashboard for Hermes Agent — system stats, agent status, chat"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "psutil>=6.0",
    "httpx>=0.27",
    "aiofiles>=24.1",
    "pydantic>=2.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "httpx>=0.27"]

[project.scripts]
hermes-dashboard = "hermes_dashboard.__main__:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
hermes_dashboard = ["static/**/*", "static/panels/*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

**Step 3: Write `src/hermes_dashboard/config.py`**

```python
"""Dashboard configuration — read from env vars with sane defaults."""
from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class DashboardConfig:
    host: str
    port: int
    hermes_home: Path
    api_server_url: str  # base URL of Hermes api_server adapter (e.g. http://127.0.0.1:8642/v1)

    @classmethod
    def from_env(cls) -> "DashboardConfig":
        return cls(
            host=os.getenv("HERMES_DASHBOARD_HOST", "0.0.0.0"),
            port=int(os.getenv("HERMES_DASHBOARD_PORT", "2002")),
            hermes_home=Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))),
            api_server_url=os.getenv("HERMES_API_SERVER_URL", "http://127.0.0.1:8642/v1"),
        )
```

**Step 4: Write minimal `src/hermes_dashboard/app.py`**

```python
"""FastAPI app factory."""
from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .config import DashboardConfig

STATIC_DIR = Path(__file__).parent / "static"


def create_app(config: DashboardConfig | None = None) -> FastAPI:
    config = config or DashboardConfig.from_env()
    app = FastAPI(title="Hermes Dashboard", version="0.1.0")
    app.state.config = config

    # Static assets
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

**Step 5: Write `src/hermes_dashboard/__main__.py`**

```python
"""Entry point: `python -m hermes_dashboard` or `hermes-dashboard`."""
from __future__ import annotations
import uvicorn
from .app import create_app
from .config import DashboardConfig


def main() -> None:
    config = DashboardConfig.from_env()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
```

**Step 6: Stub static index**

Create `src/hermes_dashboard/static/index.html`:
```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Hermes Dashboard</title></head>
<body><h1>Hermes Dashboard — bootstrapping</h1></body></html>
```

**Step 7: Write `tests/conftest.py`**

```python
import pytest
from fastapi.testclient import TestClient
from hermes_dashboard.app import create_app
from hermes_dashboard.config import DashboardConfig


@pytest.fixture
def config(tmp_path):
    return DashboardConfig(
        host="127.0.0.1",
        port=2002,
        hermes_home=tmp_path,
        api_server_url="http://127.0.0.1:8642/v1",
    )


@pytest.fixture
def client(config):
    return TestClient(create_app(config))
```

**Step 8: Write smoke test `tests/test_app_smoke.py`**

```python
def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Hermes Dashboard" in r.text
```

**Step 9: README + .gitignore**

`README.md`:
```markdown
# Hermes Dashboard

LAN-accessible web dashboard for Hermes Agent. System metrics + agent state + chat. Port 2002.

## Run
    pip install -e .
    hermes-dashboard

## Service
    systemctl --user enable --now hermes-dashboard
```

`.gitignore`:
```
__pycache__/
*.egg-info/
.venv/
venv/
.pytest_cache/
*.pyc
```

**Step 10: Install + run tests + commit**

```bash
cd ~/hermes-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Expected: `2 passed`.

```bash
git add .
git commit -m "feat: bootstrap hermes-dashboard skeleton (FastAPI + static)"
```

---

## Task 2: Collector protocol + system resources collector

**Objective:** Define a pluggable Collector protocol and implement the first one — system resources via psutil.

**Files:**
- Create: `src/hermes_dashboard/collectors/base.py`
- Create: `src/hermes_dashboard/collectors/__init__.py`
- Create: `src/hermes_dashboard/collectors/system_resources.py`
- Create: `tests/test_collectors.py`

**Step 1: Write the failing test**

`tests/test_collectors.py`:
```python
import pytest
from hermes_dashboard.collectors.system_resources import SystemResourcesCollector


@pytest.mark.asyncio
async def test_system_collector_returns_required_keys():
    c = SystemResourcesCollector()
    snapshot = await c.collect()
    assert snapshot["name"] == "system"
    data = snapshot["data"]
    assert "cpu_percent" in data
    assert "memory" in data and "percent" in data["memory"]
    assert "disk" in data and isinstance(data["disk"], list) and len(data["disk"]) >= 1
    assert "network" in data and "bytes_sent" in data["network"]
    assert "load" in data and len(data["load"]) == 3
    assert isinstance(data["cpu_percent"], (int, float))


@pytest.mark.asyncio
async def test_system_collector_name():
    c = SystemResourcesCollector()
    assert c.name == "system"
```

**Step 2: Run test → expect fail (module missing)**

```bash
pytest tests/test_collectors.py -v
```

Expected: ImportError or collection failure.

**Step 3: Write `collectors/base.py`**

```python
"""Collector protocol — extension point for dashboard data sources.

Every collector implements:
  - .name (str): stable identifier for routing/UI
  - .collect() -> dict: returns {"name": str, "ts": float, "data": dict}

Drop a new file in this package, register it in collectors/__init__.py,
and the API layer will expose it automatically.
"""
from __future__ import annotations
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Collector(Protocol):
    name: str

    async def collect(self) -> dict: ...


def envelope(name: str, data: dict) -> dict:
    return {"name": name, "ts": time.time(), "data": data}
```

**Step 4: Write `collectors/system_resources.py`**

```python
"""System resources via psutil. Cheap to call ~once a second."""
from __future__ import annotations
import asyncio
import os
import psutil
from .base import Collector, envelope


class SystemResourcesCollector:
    name = "system"

    def __init__(self) -> None:
        # First call to cpu_percent() returns 0.0 — prime it.
        psutil.cpu_percent(interval=None)

    async def collect(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        net = psutil.net_io_counters()
        try:
            load = os.getloadavg()
        except (OSError, AttributeError):
            load = (0.0, 0.0, 0.0)

        disks = []
        for part in psutil.disk_partitions(all=False):
            if not part.mountpoint or "snap" in part.mountpoint or "/proc" in part.mountpoint:
                continue
            try:
                u = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            disks.append({
                "mount": part.mountpoint,
                "device": part.device,
                "fstype": part.fstype,
                "total": u.total,
                "used": u.used,
                "free": u.free,
                "percent": u.percent,
            })

        return envelope(self.name, {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count_logical": psutil.cpu_count(logical=True),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "memory": {
                "total": vm.total, "used": vm.used, "available": vm.available,
                "percent": vm.percent,
            },
            "swap": {"total": sm.total, "used": sm.used, "percent": sm.percent},
            "disk": disks,
            "network": {
                "bytes_sent": net.bytes_sent,
                "bytes_recv": net.bytes_recv,
                "packets_sent": net.packets_sent,
                "packets_recv": net.packets_recv,
            },
            "load": list(load),
            "boot_time": psutil.boot_time(),
        })["data"] | {"name": self.name, "ts": envelope(self.name, {})["ts"]}
```

Note: the helper above mixes envelope + extras. Cleaner version — replace last return with:

```python
        data = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count_logical": psutil.cpu_count(logical=True),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "memory": {"total": vm.total, "used": vm.used, "available": vm.available, "percent": vm.percent},
            "swap": {"total": sm.total, "used": sm.used, "percent": sm.percent},
            "disk": disks,
            "network": {
                "bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv,
                "packets_sent": net.packets_sent, "packets_recv": net.packets_recv,
            },
            "load": list(load),
            "boot_time": psutil.boot_time(),
        }
        return envelope(self.name, data)
```

**Step 5: Write `collectors/__init__.py`**

```python
"""Collector registry — add new collectors here to expose them via the API."""
from .system_resources import SystemResourcesCollector
from .base import Collector

REGISTRY: dict[str, Collector] = {
    SystemResourcesCollector.name: SystemResourcesCollector(),
}

__all__ = ["REGISTRY", "Collector"]
```

**Step 6: Run tests**

```bash
pytest tests/test_collectors.py -v
```

Expected: 2 passed.

**Step 7: Commit**

```bash
git add src/hermes_dashboard/collectors tests/test_collectors.py
git commit -m "feat: collector protocol + system resources collector"
```

---

## Task 3: System metrics API (poll + SSE stream)

**Objective:** Expose `/api/system/metrics` (one-shot JSON) and `/api/system/stream` (SSE, ~1Hz).

**Files:**
- Create: `src/hermes_dashboard/api/__init__.py`
- Create: `src/hermes_dashboard/api/system.py`
- Modify: `src/hermes_dashboard/app.py` (mount the router)
- Create: `tests/test_api_system.py`

**Step 1: Write failing tests**

`tests/test_api_system.py`:
```python
def test_metrics_returns_envelope(client):
    r = client.get("/api/system/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "system"
    assert "data" in body and "cpu_percent" in body["data"]


def test_metrics_disk_list(client):
    r = client.get("/api/system/metrics")
    assert isinstance(r.json()["data"]["disk"], list)


def test_stream_endpoint_exists(client):
    # Just confirm 200 + correct content-type without consuming the whole stream.
    with client.stream("GET", "/api/system/stream") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
```

**Step 2: Run tests → fail (404)**

```bash
pytest tests/test_api_system.py -v
```

**Step 3: Write `api/__init__.py`**

```python
"""HTTP API routers."""
```

**Step 4: Write `api/system.py`**

```python
from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from ..collectors import REGISTRY

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/metrics")
async def metrics() -> dict:
    return await REGISTRY["system"].collect()


@router.get("/stream")
async def stream() -> StreamingResponse:
    async def generator():
        try:
            while True:
                snap = await REGISTRY["system"].collect()
                yield f"data: {json.dumps(snap)}\n\n"
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    return StreamingResponse(generator(), media_type="text/event-stream")
```

**Step 5: Mount in `app.py`**

Add after `app.mount("/static", ...)`:
```python
from .api import system as api_system
app.include_router(api_system.router)
```

**Step 6: Run tests**

```bash
pytest tests/test_api_system.py -v
```

Expected: 3 passed.

**Step 7: Commit**

```bash
git add src/hermes_dashboard/api tests/test_api_system.py src/hermes_dashboard/app.py
git commit -m "feat: /api/system/metrics + /api/system/stream"
```

---

## Task 4: Hermes status collectors (gateway, sessions, cron)

**Objective:** Read Hermes state from disk (sessions DB, cron DB, gateway PID/log) and expose via `/api/hermes/*`. Read-only — never mutate Hermes state.

**Files:**
- Create: `src/hermes_dashboard/collectors/hermes_status.py`
- Create: `src/hermes_dashboard/collectors/hermes_sessions.py`
- Create: `src/hermes_dashboard/collectors/hermes_cron.py`
- Create: `src/hermes_dashboard/collectors/hermes_gateway.py`
- Modify: `src/hermes_dashboard/collectors/__init__.py`
- Create: `src/hermes_dashboard/api/hermes.py`
- Modify: `src/hermes_dashboard/app.py`
- Create: `tests/test_api_hermes.py`

**Step 1: Inspect what Hermes exposes**

Before coding, the implementer must read:
```bash
ls ~/.hermes/                # state.db, kanban.db, sessions/, gateway.pid, gateway_state.json, logs/
sqlite3 ~/.hermes/state.db ".tables"
```

Document the actual schemas discovered into the collector files as docstrings.

**Step 2: Write failing test**

`tests/test_api_hermes.py`:
```python
import json
from pathlib import Path

def test_gateway_status_no_pidfile(client):
    r = client.get("/api/hermes/gateway")
    assert r.status_code == 200
    assert r.json()["data"]["running"] is False


def test_gateway_status_with_pidfile(client, config, tmp_path):
    # Drop a fake pidfile pointing at our own process so it looks "running"
    import os
    pidfile = config.hermes_home / "gateway.pid"
    pidfile.write_text(str(os.getpid()))
    r = client.get("/api/hermes/gateway")
    assert r.json()["data"]["running"] is True
    pidfile.unlink()


def test_sessions_endpoint_empty(client):
    r = client.get("/api/hermes/sessions?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body and "sessions" in body["data"]


def test_cron_endpoint_empty(client):
    r = client.get("/api/hermes/cron")
    assert r.status_code == 200
    assert "jobs" in r.json()["data"]


def test_status_aggregate(client):
    r = client.get("/api/hermes/status")
    assert r.status_code == 200
    body = r.json()["data"]
    assert "gateway" in body and "sessions_count" in body and "cron_active" in body
```

**Step 3: Run → fail**

**Step 4: Write `collectors/hermes_gateway.py`**

```python
from __future__ import annotations
import os
from pathlib import Path
import psutil
from .base import envelope


class HermesGatewayCollector:
    name = "hermes_gateway"

    def __init__(self, hermes_home: Path):
        self.hermes_home = hermes_home

    async def collect(self) -> dict:
        pidfile = self.hermes_home / "gateway.pid"
        running = False
        pid = None
        cmdline = None
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text().strip())
                if psutil.pid_exists(pid):
                    p = psutil.Process(pid)
                    cmdline = " ".join(p.cmdline())
                    running = "gateway" in cmdline
            except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        state = {}
        state_file = self.hermes_home / "gateway_state.json"
        if state_file.exists():
            import json
            try:
                state = json.loads(state_file.read_text())
            except (OSError, json.JSONDecodeError):
                pass

        return envelope(self.name, {
            "running": running,
            "pid": pid,
            "cmdline": cmdline,
            "state": state,
        })
```

**Step 5: Write `collectors/hermes_sessions.py`**

```python
from __future__ import annotations
import sqlite3
from pathlib import Path
from .base import envelope


class HermesSessionsCollector:
    """Read recent sessions from ~/.hermes/state.db.

    Schema is discovered at runtime — the dashboard never writes to this DB.
    Implementer: confirm column names with `.schema sessions` before relying.
    """
    name = "hermes_sessions"

    def __init__(self, hermes_home: Path):
        self.db_path = hermes_home / "state.db"

    async def collect(self, limit: int = 20) -> dict:
        sessions = []
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=2.0)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                # Adjust query after reading actual schema. Common columns:
                #   session_id, title, source, last_updated, message_count
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
                )
                if cur.fetchone():
                    cur.execute(
                        "SELECT * FROM sessions ORDER BY rowid DESC LIMIT ?",
                        (limit,),
                    )
                    sessions = [dict(row) for row in cur.fetchall()]
                conn.close()
            except sqlite3.Error:
                pass
        return envelope(self.name, {"sessions": sessions, "count": len(sessions)})
```

**Step 6: Write `collectors/hermes_cron.py`**

```python
from __future__ import annotations
import sqlite3
from pathlib import Path
from .base import envelope


class HermesCronCollector:
    """Read cron jobs from ~/.hermes/state.db (cron schema lives there).

    Read-only. Implementer: confirm table name (`cron_jobs` or similar) before relying.
    """
    name = "hermes_cron"

    def __init__(self, hermes_home: Path):
        self.db_path = hermes_home / "state.db"

    async def collect(self) -> dict:
        jobs = []
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=2.0)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%cron%'"
                )
                tables = [r[0] for r in cur.fetchall()]
                if tables:
                    cur.execute(f"SELECT * FROM {tables[0]} LIMIT 100")
                    jobs = [dict(row) for row in cur.fetchall()]
                conn.close()
            except sqlite3.Error:
                pass
        return envelope(self.name, {"jobs": jobs, "count": len(jobs)})
```

**Step 7: Write `collectors/hermes_status.py` (aggregate)**

```python
from __future__ import annotations
from pathlib import Path
from .base import envelope
from .hermes_gateway import HermesGatewayCollector
from .hermes_sessions import HermesSessionsCollector
from .hermes_cron import HermesCronCollector


class HermesStatusCollector:
    name = "hermes_status"

    def __init__(self, hermes_home: Path):
        self.gateway = HermesGatewayCollector(hermes_home)
        self.sessions = HermesSessionsCollector(hermes_home)
        self.cron = HermesCronCollector(hermes_home)

    async def collect(self) -> dict:
        gw = await self.gateway.collect()
        sess = await self.sessions.collect(limit=5)
        cron = await self.cron.collect()
        return envelope(self.name, {
            "gateway": gw["data"],
            "recent_sessions": sess["data"]["sessions"],
            "sessions_count": sess["data"]["count"],
            "cron_jobs": cron["data"]["jobs"],
            "cron_active": sum(1 for j in cron["data"]["jobs"] if j.get("enabled", 1)),
        })
```

**Step 8: Update `collectors/__init__.py`**

```python
from pathlib import Path
import os
from .system_resources import SystemResourcesCollector
from .hermes_gateway import HermesGatewayCollector
from .hermes_sessions import HermesSessionsCollector
from .hermes_cron import HermesCronCollector
from .hermes_status import HermesStatusCollector
from .base import Collector

_HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))

REGISTRY: dict[str, Collector] = {
    SystemResourcesCollector.name: SystemResourcesCollector(),
    HermesGatewayCollector.name: HermesGatewayCollector(_HERMES_HOME),
    HermesSessionsCollector.name: HermesSessionsCollector(_HERMES_HOME),
    HermesCronCollector.name: HermesCronCollector(_HERMES_HOME),
    HermesStatusCollector.name: HermesStatusCollector(_HERMES_HOME),
}

__all__ = ["REGISTRY", "Collector"]
```

Note: this hard-codes hermes_home at import time. For tests we need a way to inject. Refactor to a factory:

```python
def build_registry(hermes_home: Path) -> dict[str, Collector]:
    return {
        SystemResourcesCollector.name: SystemResourcesCollector(),
        HermesGatewayCollector.name: HermesGatewayCollector(hermes_home),
        HermesSessionsCollector.name: HermesSessionsCollector(hermes_home),
        HermesCronCollector.name: HermesCronCollector(hermes_home),
        HermesStatusCollector.name: HermesStatusCollector(hermes_home),
    }


REGISTRY = build_registry(_HERMES_HOME)
```

Then in `app.py` after creating config:
```python
from .collectors import build_registry
app.state.collectors = build_registry(config.hermes_home)
```

And in routes, pull from `request.app.state.collectors[name]` instead of the module-level REGISTRY. **The tests in step 2 require this — they pass a tmp_path config.**

**Step 9: Refactor system.py to use app.state**

```python
@router.get("/metrics")
async def metrics(request: Request) -> dict:
    return await request.app.state.collectors["system"].collect()
```

Same for stream. Update test imports as needed.

**Step 10: Write `api/hermes.py`**

```python
from __future__ import annotations
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/hermes", tags=["hermes"])


@router.get("/status")
async def status(request: Request) -> dict:
    return await request.app.state.collectors["hermes_status"].collect()


@router.get("/gateway")
async def gateway(request: Request) -> dict:
    return await request.app.state.collectors["hermes_gateway"].collect()


@router.get("/sessions")
async def sessions(request: Request, limit: int = 20) -> dict:
    return await request.app.state.collectors["hermes_sessions"].collect(limit=limit)


@router.get("/cron")
async def cron(request: Request) -> dict:
    return await request.app.state.collectors["hermes_cron"].collect()
```

**Step 11: Mount and run tests**

```python
# app.py
from .api import system as api_system, hermes as api_hermes
app.include_router(api_system.router)
app.include_router(api_hermes.router)
```

```bash
pytest tests/test_api_hermes.py -v
```

Expected: 5 passed.

**Step 12: Commit**

```bash
git add src/hermes_dashboard tests/test_api_hermes.py
git commit -m "feat: hermes status/sessions/cron/gateway collectors and routes"
```

---

## Task 5: Configure and verify Hermes api_server platform adapter

**Objective:** Turn on Hermes' built-in OpenAI-compatible API server so the dashboard chat can proxy through it. This is configuration, not code in our repo.

**Files (Hermes config):**
- Modify: `~/.hermes/.env` — add `API_SERVER_ENABLED=true`, `API_SERVER_PORT=8642`, `API_SERVER_HOST=127.0.0.1`
- Optional: `API_SERVER_KEY=<random-token>` (skip; LAN-trusted)

**Step 1: Read Hermes api_server docs**

```bash
sed -n '1,40p' ~/.hermes/hermes-agent/gateway/platforms/api_server.py
```

**Step 2: Add env vars**

```bash
grep -q "^API_SERVER_ENABLED=" ~/.hermes/.env || cat >> ~/.hermes/.env <<'EOF'
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
EOF
```

**Step 3: Restart gateway**

```bash
systemctl --user restart hermes-gateway
sleep 5
curl -s http://127.0.0.1:8642/health
```

Expected: `{"status":"ok"}` or similar.

**Step 4: Smoke test the chat endpoint**

```bash
curl -s -N http://127.0.0.1:8642/v1/capabilities | python3 -m json.tool
```

Expected: a JSON capabilities document.

**Step 5: Commit (the dashboard side has nothing to commit yet for this task — note in README)**

Update `~/hermes-dashboard/README.md`:
```markdown
## Prerequisites
The dashboard relies on Hermes' built-in api_server platform adapter.
Set in `~/.hermes/.env`:
    API_SERVER_ENABLED=true
    API_SERVER_HOST=127.0.0.1
    API_SERVER_PORT=8642
Then `systemctl --user restart hermes-gateway`.
```

```bash
git add README.md
git commit -m "docs: document Hermes api_server prerequisite"
```

---

## Task 6: Chat proxy API

**Objective:** Add `/api/chat/send` (POST, returns full response) and `/api/chat/stream` (SSE, token stream) that forward to the Hermes api_server.

**Files:**
- Create: `src/hermes_dashboard/api/chat.py`
- Modify: `src/hermes_dashboard/app.py`
- Create: `tests/test_api_chat.py`

**Step 1: Write failing test (using respx or httpx mock)**

`tests/test_api_chat.py`:
```python
import pytest
import httpx
from unittest.mock import AsyncMock, patch


def test_chat_send_proxies_to_api_server(client, monkeypatch):
    fake_response = {
        "id": "resp_1",
        "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
    }

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        req = httpx.Request("POST", url)
        return httpx.Response(200, json=fake_response, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    r = client.post("/api/chat/send", json={"message": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "Hello!"


def test_chat_send_requires_message(client):
    r = client.post("/api/chat/send", json={})
    assert r.status_code == 422
```

**Step 2: Run → fail (404)**

**Step 3: Write `api/chat.py`**

```python
from __future__ import annotations
import json
import logging
from typing import Optional
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: Optional[str] = None  # opt-in continuity via X-Hermes-Session-Id


@router.post("/send")
async def send(req: ChatRequest, request: Request) -> dict:
    cfg = request.app.state.config
    headers = {"Content-Type": "application/json"}
    if req.session_id:
        headers["X-Hermes-Session-Id"] = req.session_id

    payload = {
        "model": "hermes-agent",
        "messages": [{"role": "user", "content": req.message}],
        "stream": False,
    }
    url = f"{cfg.api_server_url}/chat/completions"

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            r = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            logger.warning("chat proxy failed: %s", e)
            raise HTTPException(status_code=502, detail=f"upstream unreachable: {e}")

    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    body = r.json()
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        content = ""
    return {"content": content, "session_id": r.headers.get("X-Hermes-Session-Id"), "raw": body}


@router.post("/stream")
async def stream(req: ChatRequest, request: Request) -> StreamingResponse:
    cfg = request.app.state.config
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if req.session_id:
        headers["X-Hermes-Session-Id"] = req.session_id

    payload = {
        "model": "hermes-agent",
        "messages": [{"role": "user", "content": req.message}],
        "stream": True,
    }
    url = f"{cfg.api_server_url}/chat/completions"

    async def generator():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as r:
                async for chunk in r.aiter_bytes():
                    if chunk:
                        yield chunk

    return StreamingResponse(generator(), media_type="text/event-stream")
```

**Step 4: Mount + run tests**

```python
from .api import system as api_system, hermes as api_hermes, chat as api_chat
app.include_router(api_chat.router)
```

```bash
pytest tests/test_api_chat.py -v
```

Expected: 2 passed.

**Step 5: Manual smoke (after Task 5 is done)**

```bash
hermes-dashboard &
sleep 2
curl -s -X POST http://127.0.0.1:2002/api/chat/send \
  -H 'Content-Type: application/json' \
  -d '{"message":"say hi in 5 words"}' | python3 -m json.tool
```

Expected: a JSON object with `content` containing a Hermes reply.

**Step 6: Commit**

```bash
git add src/hermes_dashboard/api/chat.py tests/test_api_chat.py src/hermes_dashboard/app.py
git commit -m "feat: chat proxy endpoints (send + stream)"
```

---

## Task 7: Frontend — clean modern UI with three panels

**Objective:** Vanilla HTML/CSS/JS dashboard with three modular panel components: System, Agents, Chat. No build step; panels are loaded as ES modules. Dark, minimal, modern aesthetic.

**Files:**
- Replace: `src/hermes_dashboard/static/index.html`
- Create: `src/hermes_dashboard/static/style.css`
- Create: `src/hermes_dashboard/static/app.js`
- Create: `src/hermes_dashboard/static/panels/system.js`
- Create: `src/hermes_dashboard/static/panels/agents.js`
- Create: `src/hermes_dashboard/static/panels/chat.js`

**Step 1: Write `index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Hermes Dashboard</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="topbar">
    <div class="brand">⌘ Hermes</div>
    <div class="status" id="connection-status">connecting…</div>
  </header>

  <main class="grid">
    <section class="panel" data-panel="system" id="panel-system">
      <h2>System</h2>
      <div class="panel-body" id="panel-system-body"></div>
    </section>

    <section class="panel" data-panel="agents" id="panel-agents">
      <h2>Agents</h2>
      <div class="panel-body" id="panel-agents-body"></div>
    </section>

    <section class="panel panel-wide" data-panel="chat" id="panel-chat">
      <h2>Chat</h2>
      <div class="panel-body" id="panel-chat-body"></div>
    </section>
  </main>

  <script type="module" src="/static/app.js"></script>
</body>
</html>
```

**Step 2: Write `style.css` (modern dark, OKLCH-friendly palette)**

```css
:root {
  --bg: #0e0f12;
  --panel: #161922;
  --panel-2: #1d212c;
  --border: #262b38;
  --text: #e6e9ef;
  --text-dim: #9aa3b2;
  --accent: #7c8cff;
  --good: #5acf91;
  --warn: #ffb86b;
  --bad: #ff6b6b;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
}
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body {
  font-family: var(--sans);
  background: var(--bg); color: var(--text);
  display: grid; grid-template-rows: auto 1fr;
}
.topbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, #14171f, #0e0f12);
}
.brand { font-weight: 600; letter-spacing: 0.02em; }
.status { font-family: var(--mono); font-size: 0.85rem; color: var(--text-dim); }
.grid {
  padding: 1.25rem;
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-auto-rows: minmax(220px, auto);
  gap: 1.25rem;
}
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1rem 1.25rem;
  overflow: hidden;
}
.panel-wide { grid-column: span 2; min-height: 360px; display: flex; flex-direction: column; }
.panel h2 { margin: 0 0 0.75rem 0; font-size: 1rem; font-weight: 500; color: var(--text-dim); letter-spacing: 0.04em; text-transform: uppercase; }
.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.75rem; }
.metric { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem; }
.metric-label { font-size: 0.75rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; }
.metric-value { font-family: var(--mono); font-size: 1.4rem; margin-top: 0.25rem; }
.bar { height: 6px; background: var(--border); border-radius: 3px; margin-top: 0.5rem; overflow: hidden; }
.bar > .fill { height: 100%; background: var(--accent); transition: width 0.3s ease; }
.bar.warn .fill { background: var(--warn); }
.bar.bad .fill { background: var(--bad); }

.kv { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1rem; font-size: 0.9rem; }
.kv dt { color: var(--text-dim); }
.kv dd { margin: 0; font-family: var(--mono); }

.chat-log { flex: 1; overflow-y: auto; padding: 0.5rem 0; display: flex; flex-direction: column; gap: 0.75rem; }
.bubble { max-width: 85%; padding: 0.6rem 0.85rem; border-radius: 10px; line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }
.bubble.user { align-self: flex-end; background: var(--accent); color: #0c0e16; }
.bubble.bot  { align-self: flex-start; background: var(--panel-2); border: 1px solid var(--border); }
.chat-input-row { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
.chat-input { flex: 1; background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 0.6rem 0.75rem; font-family: var(--sans); font-size: 0.95rem; }
.chat-input:focus { outline: none; border-color: var(--accent); }
.chat-send { background: var(--accent); color: #0c0e16; border: none; padding: 0 1rem; border-radius: 8px; font-weight: 500; cursor: pointer; }
.chat-send:disabled { opacity: 0.5; cursor: progress; }
```

**Step 3: Write `app.js` (panel registry — extension point)**

```javascript
import { mountSystemPanel } from "/static/panels/system.js";
import { mountAgentsPanel } from "/static/panels/agents.js";
import { mountChatPanel } from "/static/panels/chat.js";

const PANELS = {
  system: mountSystemPanel,
  agents: mountAgentsPanel,
  chat: mountChatPanel,
};

const status = document.getElementById("connection-status");

function setStatus(text, color) {
  status.textContent = text;
  status.style.color = color || "";
}

document.querySelectorAll(".panel[data-panel]").forEach((el) => {
  const name = el.dataset.panel;
  const mount = PANELS[name];
  if (mount) {
    mount(el.querySelector(".panel-body")).catch((err) => {
      console.error(`panel ${name} failed`, err);
    });
  } else {
    console.warn(`no mount fn for panel: ${name}`);
  }
});

setStatus("ready", "var(--good)");
```

**Step 4: Write `panels/system.js`**

```javascript
function fmtBytes(n) {
  if (!n && n !== 0) return "—";
  const u = ["B","KB","MB","GB","TB","PB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${u[i]}`;
}
function pct(v) { return `${v.toFixed(1)}%`; }
function bar(percent) {
  const cls = percent > 90 ? "bad" : percent > 75 ? "warn" : "";
  return `<div class="bar ${cls}"><div class="fill" style="width:${percent}%"></div></div>`;
}

export async function mountSystemPanel(root) {
  root.innerHTML = `<div class="metric-grid" id="sys-grid"></div><div id="sys-disks" style="margin-top:0.75rem"></div>`;
  const grid = root.querySelector("#sys-grid");
  const disks = root.querySelector("#sys-disks");

  function render(snap) {
    const d = snap.data;
    const cells = [
      { label: "CPU",     value: pct(d.cpu_percent),                   bar: d.cpu_percent },
      { label: "Memory",  value: `${fmtBytes(d.memory.used)} / ${fmtBytes(d.memory.total)}`, bar: d.memory.percent },
      { label: "Swap",    value: pct(d.swap.percent),                  bar: d.swap.percent },
      { label: "Load",    value: d.load.map(x => x.toFixed(2)).join(" "), bar: null },
      { label: "Net up",  value: fmtBytes(d.network.bytes_sent) },
      { label: "Net down",value: fmtBytes(d.network.bytes_recv) },
    ];
    grid.innerHTML = cells.map(c => `
      <div class="metric">
        <div class="metric-label">${c.label}</div>
        <div class="metric-value">${c.value}</div>
        ${c.bar != null ? bar(c.bar) : ""}
      </div>`).join("");

    disks.innerHTML = `<dl class="kv">${
      d.disk.map(p => `
        <dt>${p.mount}</dt>
        <dd>${fmtBytes(p.used)} / ${fmtBytes(p.total)} (${pct(p.percent)})</dd>
      `).join("")
    }</dl>`;
  }

  // Live SSE stream
  const es = new EventSource("/api/system/stream");
  es.onmessage = (e) => {
    try { render(JSON.parse(e.data)); } catch (err) { console.warn("system parse", err); }
  };
  es.onerror = () => { /* let browser auto-reconnect */ };
}
```

**Step 5: Write `panels/agents.js`**

```javascript
function fmtTime(unix) {
  if (!unix) return "—";
  const d = new Date(unix * 1000);
  return d.toLocaleString();
}

export async function mountAgentsPanel(root) {
  root.innerHTML = `<div id="ag-summary"></div><div id="ag-sessions" style="margin-top:0.75rem"></div>`;
  const summary = root.querySelector("#ag-summary");
  const sessions = root.querySelector("#ag-sessions");

  async function tick() {
    try {
      const r = await fetch("/api/hermes/status");
      const body = await r.json();
      const d = body.data;
      summary.innerHTML = `
        <dl class="kv">
          <dt>Gateway</dt><dd>${d.gateway.running ? "✓ running (pid " + d.gateway.pid + ")" : "✗ stopped"}</dd>
          <dt>Active sessions</dt><dd>${d.sessions_count}</dd>
          <dt>Cron jobs (active)</dt><dd>${d.cron_active}</dd>
        </dl>`;

      if (d.recent_sessions?.length) {
        sessions.innerHTML = `<h3 style="margin:0.75rem 0 0.5rem 0; font-size:0.85rem; color:var(--text-dim); text-transform:uppercase;">Recent sessions</h3>` +
          d.recent_sessions.slice(0, 5).map(s => `
            <div class="metric" style="margin-bottom:0.5rem;">
              <div class="metric-label">${s.source || s.platform || "session"}</div>
              <div style="font-size:0.95rem; margin-top:0.25rem;">${s.title || s.session_id || "—"}</div>
              <div style="font-size:0.8rem; color:var(--text-dim); margin-top:0.25rem;">${fmtTime(s.last_updated || s.updated_at)}</div>
            </div>`).join("");
      }
    } catch (e) {
      summary.textContent = "failed to fetch /api/hermes/status";
    }
  }
  await tick();
  setInterval(tick, 5000);
}
```

**Step 6: Write `panels/chat.js`**

```javascript
export async function mountChatPanel(root) {
  root.innerHTML = `
    <div class="chat-log" id="chat-log"></div>
    <form class="chat-input-row" id="chat-form">
      <input class="chat-input" id="chat-input" type="text" placeholder="Message Hermes…" autocomplete="off">
      <button class="chat-send" type="submit" id="chat-send">Send</button>
    </form>`;

  const log = root.querySelector("#chat-log");
  const form = root.querySelector("#chat-form");
  const input = root.querySelector("#chat-input");
  const send = root.querySelector("#chat-send");

  let sessionId = sessionStorage.getItem("hermes_dash_sid") || null;

  function append(role, text) {
    const div = document.createElement("div");
    div.className = `bubble ${role}`;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = input.value.trim();
    if (!msg) return;
    append("user", msg);
    input.value = "";
    send.disabled = true;
    const placeholder = append("bot", "…");
    try {
      const r = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, session_id: sessionId }),
      });
      const body = await r.json();
      placeholder.textContent = body.content || "(no content)";
      if (body.session_id) {
        sessionId = body.session_id;
        sessionStorage.setItem("hermes_dash_sid", sessionId);
      }
    } catch (err) {
      placeholder.textContent = `error: ${err.message}`;
    } finally {
      send.disabled = false;
      input.focus();
    }
  });
}
```

**Step 7: Manual visual check**

```bash
hermes-dashboard &
sleep 2
xdg-open http://127.0.0.1:2002/ || echo "open http://127.0.0.1:2002/ in a browser"
```

Verify visually: dark UI, system metrics ticking, agents panel showing gateway + sessions, chat sends and receives a real Hermes response.

**Step 8: Commit**

```bash
git add src/hermes_dashboard/static
git commit -m "feat: dark modern UI with system/agents/chat panels"
```

---

## Task 7.5: Kanban panel — read-only view of Hermes' kanban board

**Objective:** Surface the agent's work-in-progress as kanban cards, by reading Hermes' existing `~/.hermes/kanban.db` directly. Read-only — the dashboard never writes to this DB. The agent (me) creates/updates cards using the built-in `kanban_*` tools as part of normal work. Cards reflect what I'm actually doing in real time.

**Files:**
- Create: `src/hermes_dashboard/collectors/hermes_kanban.py`
- Modify: `src/hermes_dashboard/collectors/__init__.py` (add to registry)
- Create: `src/hermes_dashboard/api/kanban.py`
- Modify: `src/hermes_dashboard/app.py` (mount router)
- Create: `src/hermes_dashboard/static/panels/kanban.js`
- Modify: `src/hermes_dashboard/static/index.html` (add kanban section)
- Modify: `src/hermes_dashboard/static/app.js` (register panel)
- Modify: `src/hermes_dashboard/static/style.css` (kanban styles)
- Create: `tests/test_api_kanban.py`

**Step 1: Inspect Hermes kanban schema (do this first, before writing code)**

```bash
read_file ~/.hermes/hermes-agent/hermes_cli/kanban_db.py  # confirm column names
```

Confirmed schema (from inspection):
- `tasks(id, title, body, assignee, status, priority, created_by, created_at, started_at, completed_at, workspace_kind, workspace_path, claim_lock, claim_expires, tenant, result, idempotency_key, spawn_failures, worker_pid, last_spawn_error, max_runtime_seconds, last_heartbeat_at, current_run_id, workflow_template_id, current_step_key, skills)`
- `task_events(id, task_id, run_id, kind, payload, created_at)` — append-only event log
- `task_comments(id, task_id, author, body, created_at)`
- `task_runs(id, task_id, profile, step_key, status, ..., started_at, ended_at, outcome, summary, ...)`

Status values used by Hermes: `pending` / `claimed` / `running` / `completed` / `blocked` / `cancelled`. We map these into three columns:
- **Backlog** ← `pending`
- **In Progress** ← `claimed`, `running`, `blocked`
- **Done** ← `completed`, `cancelled`

**Step 2: Write failing test**

`tests/test_api_kanban.py`:
```python
import sqlite3
import time
import pytest
from pathlib import Path


def _seed_kanban(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            assignee TEXT,
            status TEXT,
            priority INTEGER,
            created_by TEXT,
            created_at INTEGER,
            started_at INTEGER,
            completed_at INTEGER,
            workspace_kind TEXT,
            workspace_path TEXT,
            claim_lock TEXT,
            claim_expires INTEGER,
            tenant TEXT,
            result TEXT,
            idempotency_key TEXT,
            spawn_failures INTEGER DEFAULT 0,
            worker_pid INTEGER,
            last_spawn_error TEXT,
            max_runtime_seconds INTEGER,
            last_heartbeat_at INTEGER,
            current_run_id TEXT,
            workflow_template_id TEXT,
            current_step_key TEXT,
            skills TEXT
        );
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            run_id TEXT,
            kind TEXT,
            payload TEXT,
            created_at INTEGER
        );
        CREATE TABLE task_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            author TEXT,
            body TEXT,
            created_at INTEGER
        );
    """)
    now = int(time.time())
    conn.executemany(
        "INSERT INTO tasks(id, title, body, status, priority, created_at, created_by, assignee) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("t-1", "Set up Discord gateway", "Configure Discord bot token", "completed", 2, now-3600, "eric", "hermes"),
            ("t-2", "Build Obsidian memory vault", "Wire SOUL.md + AGENTS.md", "running", 1, now-1800, "hermes", "hermes"),
            ("t-3", "Build Hermes dashboard",   "Port 2002, system + chat",   "pending", 1, now-300,  "eric", "hermes"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def kanban_client(tmp_path, config):
    # Override hermes_home to a temp dir with our seeded kanban.db
    db = tmp_path / "kanban.db"
    _seed_kanban(db)
    from hermes_dashboard.app import create_app
    from hermes_dashboard.config import DashboardConfig
    cfg = DashboardConfig(
        host="127.0.0.1", port=2002,
        hermes_home=tmp_path,
        api_server_url="http://127.0.0.1:8642/v1",
    )
    from fastapi.testclient import TestClient
    return TestClient(create_app(cfg))


def test_board_returns_three_columns(kanban_client):
    r = kanban_client.get("/api/kanban/board")
    assert r.status_code == 200
    body = r.json()["data"]
    assert "columns" in body
    cols = {c["name"]: c for c in body["columns"]}
    assert set(cols.keys()) == {"Backlog", "In Progress", "Done"}


def test_board_groups_tasks_correctly(kanban_client):
    r = kanban_client.get("/api/kanban/board")
    body = r.json()["data"]
    cols = {c["name"]: c["tasks"] for c in body["columns"]}
    assert any(t["id"] == "t-1" for t in cols["Done"])
    assert any(t["id"] == "t-2" for t in cols["In Progress"])
    assert any(t["id"] == "t-3" for t in cols["Backlog"])


def test_task_detail_includes_comments(kanban_client):
    r = kanban_client.get("/api/kanban/tasks/t-2")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["task"]["id"] == "t-2"
    assert "comments" in body
    assert "events" in body


def test_task_404(kanban_client):
    r = kanban_client.get("/api/kanban/tasks/does-not-exist")
    assert r.status_code == 404


def test_board_omits_old_done_tasks(kanban_client, tmp_path):
    # Insert an old completed task and verify it's filtered out.
    import sqlite3, time
    conn = sqlite3.connect(tmp_path / "kanban.db")
    old = int(time.time()) - 86400 * 3
    conn.execute(
        "INSERT INTO tasks(id, title, status, priority, created_at, completed_at) VALUES (?,?,?,?,?,?)",
        ("t-old", "Ancient task", "completed", 2, old, old),
    )
    conn.commit()
    conn.close()
    r = kanban_client.get("/api/kanban/board")
    cols = {c["name"]: c["tasks"] for c in r.json()["data"]["columns"]}
    assert not any(t["id"] == "t-old" for t in cols["Done"]), "completed >24h ago must be hidden"
```

**Step 3: Run → fail (404 / collector missing)**

**Step 4: Write `collectors/hermes_kanban.py`**

```python
"""Read-only view of ~/.hermes/kanban.db.

The dashboard never writes to this database. Card creation/updates happen
through the agent's normal kanban tools and the kanban dispatcher; we just
project the current state for humans to look at.

Schema reference: hermes_cli/kanban_db.py.
"""
from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from typing import Optional
from .base import envelope


# Buckets for the three on-screen columns
_BACKLOG_STATUSES = {"pending"}
_INPROGRESS_STATUSES = {"claimed", "running", "blocked"}
_DONE_STATUSES = {"completed", "cancelled"}

# Hide Done cards older than this many seconds — auto-archive at end of day
# is enforced by a separate cron, but the UI also filters defensively.
_DONE_VISIBILITY_SECONDS = 24 * 3600


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # Trim noisy/internal columns from the wire payload — keep what humans care about
    for k in ("claim_lock", "claim_expires", "idempotency_key",
              "spawn_failures", "last_spawn_error", "tenant",
              "workflow_template_id"):
        d.pop(k, None)
    return d


class HermesKanbanCollector:
    name = "hermes_kanban"

    def __init__(self, hermes_home: Path):
        self.db_path = hermes_home / "kanban.db"

    def _connect_ro(self) -> Optional[sqlite3.Connection]:
        if not self.db_path.exists():
            return None
        # Open read-only; WAL mode in Hermes' DB allows concurrent reads
        # while the dispatcher writes. mode=ro guarantees we can't accidentally write.
        try:
            uri = f"file:{self.db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error:
            return None

    async def collect(self) -> dict:
        conn = self._connect_ro()
        if conn is None:
            return envelope(self.name, {"columns": _empty_columns(), "available": False})

        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
            )
            if not cur.fetchone():
                return envelope(self.name, {"columns": _empty_columns(), "available": False})

            now = int(time.time())
            cutoff = now - _DONE_VISIBILITY_SECONDS

            # Backlog + in-progress: no time filter
            # Done: only those completed within the visibility window
            cur.execute("""
                SELECT * FROM tasks
                 WHERE status IN ('pending','claimed','running','blocked')
                    OR (status IN ('completed','cancelled')
                        AND COALESCE(completed_at, created_at) >= ?)
                 ORDER BY priority ASC, created_at DESC
                 LIMIT 200
            """, (cutoff,))
            rows = [_row_to_dict(r) for r in cur.fetchall()]

            backlog, inprog, done = [], [], []
            for r in rows:
                s = r.get("status", "")
                if s in _BACKLOG_STATUSES: backlog.append(r)
                elif s in _INPROGRESS_STATUSES: inprog.append(r)
                elif s in _DONE_STATUSES: done.append(r)

            columns = [
                {"name": "Backlog",     "tasks": backlog},
                {"name": "In Progress", "tasks": inprog},
                {"name": "Done",        "tasks": done},
            ]
            return envelope(self.name, {
                "columns": columns,
                "available": True,
                "total": sum(len(c["tasks"]) for c in columns),
            })
        finally:
            conn.close()

    async def get_task(self, task_id: str) -> Optional[dict]:
        conn = self._connect_ro()
        if conn is None:
            return None
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                return None
            task = _row_to_dict(row)

            cur.execute(
                "SELECT id, author, body, created_at FROM task_comments "
                "WHERE task_id = ? ORDER BY created_at ASC LIMIT 200",
                (task_id,),
            )
            comments = [dict(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT id, run_id, kind, payload, created_at FROM task_events "
                "WHERE task_id = ? ORDER BY id DESC LIMIT 50",
                (task_id,),
            )
            events = [dict(r) for r in cur.fetchall()]

            return {"task": task, "comments": comments, "events": events}
        finally:
            conn.close()

    async def latest_event_id(self) -> int:
        conn = self._connect_ro()
        if conn is None:
            return 0
        try:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(id), 0) FROM task_events")
            return int(cur.fetchone()[0])
        finally:
            conn.close()


def _empty_columns() -> list[dict]:
    return [
        {"name": "Backlog", "tasks": []},
        {"name": "In Progress", "tasks": []},
        {"name": "Done", "tasks": []},
    ]
```

**Step 5: Update `collectors/__init__.py`**

```python
from .hermes_kanban import HermesKanbanCollector
# ... add to build_registry():
HermesKanbanCollector.name: HermesKanbanCollector(hermes_home),
```

**Step 6: Write `api/kanban.py`**

```python
from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/kanban", tags=["kanban"])


@router.get("/board")
async def board(request: Request) -> dict:
    return await request.app.state.collectors["hermes_kanban"].collect()


@router.get("/tasks/{task_id}")
async def task_detail(task_id: str, request: Request) -> dict:
    coll = request.app.state.collectors["hermes_kanban"]
    detail = await coll.get_task(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="task not found")
    from hermes_dashboard.collectors.base import envelope
    return envelope("hermes_kanban_task", detail)


@router.get("/events")
async def events_stream(request: Request) -> StreamingResponse:
    """SSE: emit a 'board' event whenever the highest task_event id changes.
    Polls every 1.5s — cheap, keeps a SQLite read connection only momentarily."""
    coll = request.app.state.collectors["hermes_kanban"]

    async def gen():
        last = await coll.latest_event_id()
        # Always send an initial snapshot so reconnects refresh immediately.
        snap = await coll.collect()
        yield f"event: board\ndata: {json.dumps(snap)}\n\n"
        try:
            while True:
                await asyncio.sleep(1.5)
                cur = await coll.latest_event_id()
                if cur != last:
                    last = cur
                    snap = await coll.collect()
                    yield f"event: board\ndata: {json.dumps(snap)}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")
```

**Step 7: Mount router in `app.py`**

```python
from .api import kanban as api_kanban
app.include_router(api_kanban.router)
```

**Step 8: Run API tests → expect pass**

```bash
pytest tests/test_api_kanban.py -v
```

Expected: 5 passed.

**Step 9: Add kanban styles to `style.css`**

Append:
```css
.kanban {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
  height: 100%;
}
.kanban-column { background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px; padding: 0.6rem; display: flex; flex-direction: column; min-height: 280px; }
.kanban-column h3 { margin: 0 0 0.5rem 0; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); display: flex; justify-content: space-between; }
.kanban-column h3 .count { font-family: var(--mono); background: var(--panel); border-radius: 999px; padding: 0 0.5rem; font-size: 0.7rem; }
.kanban-cards { display: flex; flex-direction: column; gap: 0.5rem; overflow-y: auto; }
.kanban-card {
  background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  padding: 0.6rem 0.75rem; cursor: pointer; transition: border-color 0.15s;
}
.kanban-card:hover { border-color: var(--accent); }
.kanban-card .title { font-size: 0.95rem; font-weight: 500; line-height: 1.3; }
.kanban-card .meta { font-size: 0.75rem; color: var(--text-dim); margin-top: 0.4rem; display: flex; justify-content: space-between; gap: 0.5rem; }
.kanban-card .pri-1 { color: var(--bad); }
.kanban-card .pri-2 { color: var(--warn); }
.kanban-card .pri-3 { color: var(--text-dim); }

/* Modal for card detail */
.kb-modal-bg { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: none; align-items: center; justify-content: center; z-index: 100; }
.kb-modal-bg.open { display: flex; }
.kb-modal { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem 1.5rem; max-width: 720px; width: 90vw; max-height: 80vh; overflow-y: auto; }
.kb-modal h3 { margin-top: 0; }
.kb-modal-section { margin-top: 1rem; }
.kb-comment, .kb-event { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 0.5rem 0.75rem; margin-top: 0.4rem; font-size: 0.88rem; }
.kb-event .kind { color: var(--accent); font-family: var(--mono); font-size: 0.78rem; }
.kb-modal-close { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 0.4rem 0.75rem; cursor: pointer; }
```

**Step 10: Add kanban panel to `index.html`**

Insert before the chat panel:
```html
<section class="panel panel-wide" data-panel="kanban" id="panel-kanban">
  <h2>Kanban — agent work</h2>
  <div class="panel-body" id="panel-kanban-body"></div>
</section>

<div class="kb-modal-bg" id="kb-modal-bg">
  <div class="kb-modal" id="kb-modal">
    <button class="kb-modal-close" id="kb-modal-close" type="button">close</button>
    <div id="kb-modal-content"></div>
  </div>
</div>
```

Also widen the panel grid: in `style.css`, change `.grid grid-template-columns` to `repeat(2, 1fr)` and let `.panel-wide` span both columns. Each of system/agents stays in one cell; kanban + chat each get a wide row.

**Step 11: Write `panels/kanban.js`**

```javascript
function fmtRelTime(unix) {
  if (!unix) return "—";
  const d = Date.now() / 1000 - unix;
  if (d < 60) return `${Math.floor(d)}s ago`;
  if (d < 3600) return `${Math.floor(d/60)}m ago`;
  if (d < 86400) return `${Math.floor(d/3600)}h ago`;
  return `${Math.floor(d/86400)}d ago`;
}

function priClass(p) {
  if (p == null) return "pri-3";
  if (p <= 1) return "pri-1";
  if (p <= 2) return "pri-2";
  return "pri-3";
}

export async function mountKanbanPanel(root) {
  root.innerHTML = `<div class="kanban" id="kanban-grid"></div>`;
  const grid = root.querySelector("#kanban-grid");
  const modalBg = document.getElementById("kb-modal-bg");
  const modalContent = document.getElementById("kb-modal-content");
  const modalClose = document.getElementById("kb-modal-close");

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);
  }

  function render(snap) {
    const data = snap.data;
    if (!data.available) {
      grid.innerHTML = `<div style="color:var(--text-dim); padding:1rem;">Kanban DB not found at <code>~/.hermes/kanban.db</code>. Create a task with the agent to initialize it.</div>`;
      return;
    }
    grid.innerHTML = data.columns.map(col => `
      <div class="kanban-column">
        <h3>${escapeHtml(col.name)} <span class="count">${col.tasks.length}</span></h3>
        <div class="kanban-cards">
          ${col.tasks.map(t => `
            <div class="kanban-card" data-task-id="${escapeHtml(t.id)}">
              <div class="title">${escapeHtml(t.title)}</div>
              <div class="meta">
                <span class="${priClass(t.priority)}">P${t.priority ?? "—"}</span>
                <span>${escapeHtml(t.assignee || "—")}</span>
                <span>${fmtRelTime(t.completed_at || t.started_at || t.created_at)}</span>
              </div>
            </div>
          `).join("")}
        </div>
      </div>`).join("");

    grid.querySelectorAll(".kanban-card").forEach(el => {
      el.addEventListener("click", () => openTask(el.dataset.taskId));
    });
  }

  async function openTask(id) {
    try {
      const r = await fetch(`/api/kanban/tasks/${encodeURIComponent(id)}`);
      if (!r.ok) {
        modalContent.innerHTML = `<p style="color:var(--bad)">Failed to load task ${escapeHtml(id)}</p>`;
        modalBg.classList.add("open");
        return;
      }
      const body = await r.json();
      const t = body.data.task;
      const comments = body.data.comments || [];
      const events = body.data.events || [];
      modalContent.innerHTML = `
        <h3>${escapeHtml(t.title)}</h3>
        <dl class="kv">
          <dt>Status</dt><dd>${escapeHtml(t.status)}</dd>
          <dt>Priority</dt><dd>P${t.priority ?? "—"}</dd>
          <dt>Assignee</dt><dd>${escapeHtml(t.assignee || "—")}</dd>
          <dt>Created</dt><dd>${fmtRelTime(t.created_at)}</dd>
          ${t.completed_at ? `<dt>Completed</dt><dd>${fmtRelTime(t.completed_at)}</dd>` : ""}
        </dl>
        ${t.body ? `<div class="kb-modal-section"><strong>Body</strong><div class="kb-comment">${escapeHtml(t.body)}</div></div>` : ""}
        ${t.result ? `<div class="kb-modal-section"><strong>Result</strong><div class="kb-comment">${escapeHtml(t.result)}</div></div>` : ""}
        <div class="kb-modal-section">
          <strong>Comments (${comments.length})</strong>
          ${comments.length ? comments.map(c => `
            <div class="kb-comment">
              <div style="font-size:0.75rem; color:var(--text-dim);">${escapeHtml(c.author)} · ${fmtRelTime(c.created_at)}</div>
              <div>${escapeHtml(c.body)}</div>
            </div>`).join("") : `<div style="color:var(--text-dim); margin-top:0.4rem;">No comments yet.</div>`}
        </div>
        <div class="kb-modal-section">
          <strong>Recent events</strong>
          ${events.length ? events.slice(0, 10).map(e => `
            <div class="kb-event">
              <div><span class="kind">${escapeHtml(e.kind)}</span> · ${fmtRelTime(e.created_at)}</div>
              ${e.payload ? `<div style="font-family:var(--mono); font-size:0.8rem; color:var(--text-dim); margin-top:0.25rem;">${escapeHtml(e.payload)}</div>` : ""}
            </div>`).join("") : `<div style="color:var(--text-dim); margin-top:0.4rem;">No events yet.</div>`}
        </div>`;
      modalBg.classList.add("open");
    } catch (err) {
      console.error("kanban detail fetch", err);
    }
  }

  modalClose.addEventListener("click", () => modalBg.classList.remove("open"));
  modalBg.addEventListener("click", (e) => {
    if (e.target === modalBg) modalBg.classList.remove("open");
  });

  // Live updates via SSE — board emits a fresh snapshot when task_events table changes
  const es = new EventSource("/api/kanban/events");
  es.addEventListener("board", (e) => {
    try { render(JSON.parse(e.data)); } catch (err) { console.warn("kanban parse", err); }
  });
  es.onerror = () => { /* browser auto-reconnects */ };
}
```

**Step 12: Register panel in `app.js`**

```javascript
import { mountKanbanPanel } from "/static/panels/kanban.js";
const PANELS = {
  system: mountSystemPanel,
  agents: mountAgentsPanel,
  kanban: mountKanbanPanel,
  chat:   mountChatPanel,
};
```

**Step 13: Manual visual check**

```bash
# Create a test task using the agent's kanban tool, then:
hermes-dashboard &
sleep 2
curl -s http://127.0.0.1:2002/api/kanban/board | python3 -m json.tool
```

Open the dashboard in a browser, click a card, see the modal populate with body/comments/events. Status changes to a task should show up within ~1.5s without refreshing the page.

**Step 14: Commit**

```bash
git add src/hermes_dashboard tests/test_api_kanban.py
git commit -m "feat: read-only kanban panel with live SSE updates"
```

---

## Task 7.6: Auto-archive completed kanban cards at end of day

**Objective:** Cron job that runs at 23:59 local time daily, marking any `completed`/`cancelled` task with `completed_at` older than 24 hours as archived (so the dashboard's Done column stays empty next morning).

We don't add an `archived` column to Hermes' schema — that'd be a write to their DB. Instead, the dashboard's collector already filters Done cards older than 24h. The "auto-archive" is implicit: at midnight, anything completed >24h ago disappears from the UI without us touching the underlying DB.

**However**, you also want the Done column to clear at end of day even if the task completed at 23:50 the same day. So we add a separate concept: a UI-side `last_archive_ts` watermark stored in the dashboard's own state, defaulting to "show Done cards completed after this watermark."

**Files:**
- Create: `src/hermes_dashboard/state.py`  (tiny JSON state file in `~/.hermes/dashboard-state.json`)
- Modify: `src/hermes_dashboard/collectors/hermes_kanban.py` (apply watermark to Done filter)
- Create: cron job via `cronjob create`

**Step 1: Write `state.py`**

```python
"""Tiny persistent state for the dashboard. JSON file. No schema migrations.
Stored under HERMES_HOME so it survives restarts."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any


def _path(hermes_home: Path) -> Path:
    return hermes_home / "dashboard-state.json"


def load(hermes_home: Path) -> dict:
    p = _path(hermes_home)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save(hermes_home: Path, state: dict) -> None:
    p = _path(hermes_home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(p)


def get_archive_watermark(hermes_home: Path) -> int:
    return int(load(hermes_home).get("kanban_archive_watermark", 0))


def set_archive_watermark(hermes_home: Path, ts: int | None = None) -> int:
    ts = ts if ts is not None else int(time.time())
    s = load(hermes_home)
    s["kanban_archive_watermark"] = ts
    save(hermes_home, s)
    return ts
```

**Step 2: Update kanban collector to use watermark**

In `hermes_kanban.py` collect():
```python
from .. import state as dash_state
# ...
watermark = dash_state.get_archive_watermark(self.db_path.parent)  # hermes_home
# ...
# In the WHERE clause, the Done branch uses MAX(watermark, cutoff):
done_floor = max(watermark, cutoff)
cur.execute("""
    SELECT * FROM tasks
     WHERE status IN ('pending','claimed','running','blocked')
        OR (status IN ('completed','cancelled')
            AND COALESCE(completed_at, created_at) >= ?)
     ORDER BY priority ASC, created_at DESC
     LIMIT 200
""", (done_floor,))
```

**Step 3: Add `/api/kanban/archive` POST endpoint** for the cron to hit

In `api/kanban.py`:
```python
@router.post("/archive")
async def archive_done(request: Request) -> dict:
    cfg = request.app.state.config
    from hermes_dashboard import state as dash_state
    ts = dash_state.set_archive_watermark(cfg.hermes_home)
    return {"archived_at": ts}
```

**Step 4: Create cron job**

Use the Hermes `cronjob` tool (not crontab):
```python
cronjob(
    action="create",
    schedule="59 23 * * *",
    name="dashboard-kanban-archive",
    prompt="Hit POST http://127.0.0.1:2002/api/kanban/archive to bump the dashboard kanban archive watermark.",
    deliver="local",
)
```

This is intentionally a Hermes cron job rather than a system cron — it'll show up in the agents panel's cron list and Eric can pause/resume it from the dashboard.

**Step 5: Add a test**

`tests/test_api_kanban.py` (append):
```python
def test_archive_endpoint_advances_watermark(kanban_client, tmp_path):
    r = kanban_client.post("/api/kanban/archive")
    assert r.status_code == 200
    ts1 = r.json()["archived_at"]
    # Subsequent call advances further
    import time; time.sleep(1)
    r2 = kanban_client.post("/api/kanban/archive")
    assert r2.json()["archived_at"] >= ts1
```

**Step 6: Commit**

```bash
git add src/hermes_dashboard/state.py src/hermes_dashboard/collectors/hermes_kanban.py \
        src/hermes_dashboard/api/kanban.py tests/test_api_kanban.py
git commit -m "feat: end-of-day kanban auto-archive via watermark + cron"
```

---

## Task 8: systemd user service

**Objective:** Run as `systemctl --user` service with auto-restart and journal logging.

**Files:**
- Create: `systemd/hermes-dashboard.service`
- Add to README install steps.

**Step 1: Write the unit file**

`systemd/hermes-dashboard.service`:
```ini
[Unit]
Description=Hermes Dashboard
After=network-online.target hermes-gateway.service
Wants=network-online.target
PartOf=default.target

[Service]
Type=simple
WorkingDirectory=%h/hermes-dashboard
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-%h/.hermes/.env
ExecStart=%h/hermes-dashboard/.venv/bin/hermes-dashboard
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

**Step 2: Install + enable**

```bash
mkdir -p ~/.config/systemd/user
cp ~/hermes-dashboard/systemd/hermes-dashboard.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hermes-dashboard
sleep 3
systemctl --user status hermes-dashboard --no-pager
```

Expected: `active (running)`.

**Step 3: Verify from another machine on the LAN**

```bash
curl -s http://<this-host>:2002/healthz
```

Expected: `{"status":"ok"}`.

**Step 4: Confirm linger is on (gateway likely already enabled it)**

```bash
loginctl show-user $USER | grep Linger
```

Expected: `Linger=yes`. If `no`: `sudo loginctl enable-linger $USER`.

**Step 5: Commit**

```bash
cd ~/hermes-dashboard
git add systemd/hermes-dashboard.service README.md
git commit -m "feat: systemd user service unit"
```

---

## Task 9: Documentation, extension hooks doc, vault update

**Objective:** Document how to add a new collector and a new panel, then log the project in the vault.

**Files:**
- Modify: `~/hermes-dashboard/README.md`
- Modify: `/opt/obsidian_vault/Agent-Shared/project-state.md` (mark dashboard as done)
- Append: `/opt/obsidian_vault/Agent-Shared/decisions-log.md`
- Append: today's `/opt/obsidian_vault/Agent-Hermes/daily/<date>.md`

**Step 1: README extension docs**

Append to README:
```markdown
## Extending

### New metric collector
1. Create `src/hermes_dashboard/collectors/my_collector.py`:
   ```python
   from .base import envelope
   class MyCollector:
       name = "my_metric"
       async def collect(self):
           return envelope(self.name, {"value": 42})
   ```
2. Register in `collectors/__init__.py` build_registry.
3. Expose via a route in `api/` or piggyback on `/api/hermes/status`.

### New UI panel
1. Add a `<section class="panel" data-panel="myname">…</section>` to `index.html`.
2. Create `static/panels/myname.js` exporting `mountMyPanel(root)`.
3. Register in `app.js`'s `PANELS` map.
```

**Step 2: Update vault**

```python
# project-state.md — mark dashboard active → done
# decisions-log.md — append entry: chose vanilla JS + FastAPI, why
# daily/<today>.md — log full session
```

**Step 3: Final commit + tag**

```bash
cd ~/hermes-dashboard
git add README.md
git commit -m "docs: extension guide for collectors and panels"
git tag v0.1.0
```

---

## Verification checklist (run before declaring done)

- [ ] `pytest -q` → all tests pass
- [ ] `systemctl --user status hermes-dashboard` → active
- [ ] `curl http://localhost:2002/healthz` → 200
- [ ] `curl http://localhost:2002/api/system/metrics | jq` → real values
- [ ] `curl http://localhost:2002/api/hermes/status | jq` → gateway running, sessions, cron
- [ ] Browser at `http://<lan-ip>:2002/` from another LAN device → renders, metrics live, chat works
- [ ] Send a message via dashboard chat → response arrives, session_id persists across reloads
- [ ] Restart gateway → dashboard recovers automatically (auto-restart on chat 502 will retry)
- [ ] Vault updated with completion entry

## Open risks / called-out unknowns

1. **Hermes state.db schema** — the sessions/cron collectors assume column names that the implementer must confirm with `.schema`. Plan tells them to do this in Task 4 step 1.
2. **api_server X-Hermes-Session-Id header** — listed in the api_server.py docstring; implementer must verify the actual response header name during Task 6 manual smoke.
3. **psutil disk_partitions on this RHEL box** — may include weird FUSE mounts; the collector skips snap/proc but other oddities might appear. Visual check during Task 7 step 7 catches this.
4. **Port 2002 firewall** — RHEL ships firewalld. If LAN access fails, run `sudo firewall-cmd --add-port=2002/tcp --permanent && sudo firewall-cmd --reload`. Add this as a troubleshooting note in README only after we hit it.
