"""Persistent dashboard state — small JSON file under HERMES_HOME.

The dashboard treats Hermes' own SQLite databases as read-only. Local UI/control
state that has to survive restarts lives here instead:
  - kanban_archive_watermark: unix ts; Done cards completed before this are hidden
  - dashboard_tasks: task requests created from the LAN UI before/while Hermione
    turns them into real agent work
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .safe_paths import resolve_child

_FILENAME = "dashboard-state.json"
_LOCK = threading.Lock()


def state_path(hermes_home: Path) -> Path:
    """Resolved dashboard state file confined to the configured Hermes home."""
    return resolve_child(hermes_home, _FILENAME)


def _path(hermes_home: Path) -> Path:
    return state_path(hermes_home)


def _default_state() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "revision": 0,
        "kanban_archive_watermark": 0,
        "done_auto_archive_days": 3,
        "dashboard_tasks": [],
    }


def load(hermes_home: Path) -> dict[str, Any]:
    """Read the state file. Missing or corrupt → versioned defaults."""
    p = _path(hermes_home)
    if not p.exists():
        return _default_state()
    try:
        raw = json.loads(p.read_text())
        if not isinstance(raw, dict):
            return _default_state()
    except (OSError, json.JSONDecodeError):
        return _default_state()
    state = _default_state()
    state.update(raw)
    if not isinstance(state.get("dashboard_tasks"), list):
        state["dashboard_tasks"] = []
    return state


def save(hermes_home: Path, state: dict[str, Any]) -> None:
    """Atomic write via tmp + rename so we never end up with partial JSON."""
    p = _path(hermes_home)
    p.parent.mkdir(parents=True, exist_ok=True)
    state.setdefault("schema_version", 2)
    state.setdefault("revision", 0)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(p)


def _bump_revision(state: dict[str, Any]) -> int:
    """Monotonic state revision used by SSE change detection."""
    state["revision"] = int(state.get("revision") or 0) + 1
    return state["revision"]


def get_archive_watermark(hermes_home: Path) -> int:
    """Unix ts. 0 = no watermark set (show everything within freshness window)."""
    return int(load(hermes_home).get("kanban_archive_watermark", 0))


def set_archive_watermark(hermes_home: Path, ts: int | None = None) -> int:
    """Set the watermark to ``ts`` (or now). Returns the value written."""
    ts = int(ts) if ts is not None else int(time.time())
    with _LOCK:
        s = load(hermes_home)
        s["kanban_archive_watermark"] = ts
        _bump_revision(s)
        save(hermes_home, s)
    return ts


def list_dashboard_tasks(hermes_home: Path, include_archived: bool = False) -> list[dict[str, Any]]:
    tasks = list(load(hermes_home).get("dashboard_tasks", []))
    if include_archived:
        return tasks
    return [t for t in tasks if not t.get("archived_at")]


def create_dashboard_task(
    hermes_home: Path,
    *,
    title: str,
    body: str = "",
    priority: int = 2,
    preferred_agent: str | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    task = {
        "id": f"dash-{uuid.uuid4().hex[:12]}",
        "title": title.strip(),
        "body": body.strip(),
        "priority": int(priority),
        "created_by": "dashboard",
        "created_at": now,
        "updated_at": now,
        "status": "assigned",
        "assignee": "Hermione",
        "selected_agent": None,
        "preferred_agent": preferred_agent,
        "hermes_task_id": None,
        "handoff_status": "awaiting_hermione",
        "source": "dashboard",
    }
    with _LOCK:
        s = load(hermes_home)
        tasks = list(s.get("dashboard_tasks", []))
        tasks.append(task)
        s["dashboard_tasks"] = tasks
        _bump_revision(s)
        save(hermes_home, s)
    return task


def latest_dashboard_task_update(hermes_home: Path) -> int:
    """Cheap change detector for dashboard-owned task state."""
    return int(load(hermes_home).get("revision") or 0)


def update_dashboard_task(hermes_home: Path, task_id: str, **updates: Any) -> dict[str, Any] | None:
    allowed = {"status", "selected_agent", "assignee", "handoff_status", "hermes_task_id", "body", "title", "priority"}
    safe_updates = {k: v for k, v in updates.items() if k in allowed}
    if not safe_updates:
        return None
    with _LOCK:
        s = load(hermes_home)
        tasks = list(s.get("dashboard_tasks", []))
        for task in tasks:
            if task.get("id") == task_id:
                task.update(safe_updates)
                task["updated_at"] = int(time.time())
                s["dashboard_tasks"] = tasks
                _bump_revision(s)
                save(hermes_home, s)
                return task
    return None


def archive_done_dashboard_tasks(hermes_home: Path, older_than_days: int = 3) -> int:
    cutoff = int(time.time()) - (int(older_than_days) * 24 * 3600)
    archived = 0
    with _LOCK:
        s = load(hermes_home)
        tasks = list(s.get("dashboard_tasks", []))
        for task in tasks:
            completed_at = int(task.get("completed_at") or task.get("updated_at") or 0)
            if task.get("status") == "done" and not task.get("archived_at") and completed_at <= cutoff:
                task["archived_at"] = int(time.time())
                archived += 1
        if archived:
            _bump_revision(s)
        s["dashboard_tasks"] = tasks
        save(hermes_home, s)
    return archived
