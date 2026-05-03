"""Persistent dashboard state — small JSON file under HERMES_HOME.

Used for things the dashboard needs to remember across restarts but that
have no business living in Hermes' own state DBs (which we treat as read-only).

Currently stores:
  - kanban_archive_watermark: unix ts. Done cards completed before this
    are hidden from the kanban panel. Bumped by the EOD archive cron.

No schema migrations — if the file is missing or malformed, defaults apply.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_FILENAME = "dashboard-state.json"


def _path(hermes_home: Path) -> Path:
    return Path(hermes_home) / _FILENAME


def load(hermes_home: Path) -> dict[str, Any]:
    """Read the state file. Missing or corrupt → empty dict."""
    p = _path(hermes_home)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save(hermes_home: Path, state: dict[str, Any]) -> None:
    """Atomic write via tmp + rename so we never end up with partial JSON."""
    p = _path(hermes_home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(p)


def get_archive_watermark(hermes_home: Path) -> int:
    """Unix ts. 0 = no watermark set (show everything within freshness window)."""
    return int(load(hermes_home).get("kanban_archive_watermark", 0))


def set_archive_watermark(hermes_home: Path, ts: int | None = None) -> int:
    """Set the watermark to ``ts`` (or now). Returns the value written."""
    ts = int(ts) if ts is not None else int(time.time())
    s = load(hermes_home)
    s["kanban_archive_watermark"] = ts
    save(hermes_home, s)
    return ts
