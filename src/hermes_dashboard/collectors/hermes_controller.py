"""Read-only view of the Hermes Controller v0 planning DB.

The dashboard never mutates the controller database. It projects planning-only
jobs/tasks/events/artifact refs into the mission board so the UI can poll the
controller state every 5-10 seconds without treating Obsidian as a queue.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from ..safe_paths import resolve_child
from .base import envelope

_BACKLOG_STATUSES = {"queued", "ready"}
_INPROGRESS_STATUSES = {"assigned", "running", "blocked", "waiting_for_agent", "waiting_for_approval", "retry_scheduled"}
_DONE_STATUSES = {"completed"}
_CANCELLED_STATUSES = {"failed", "cancelled", "superseded"}

_INTERNAL_COLUMNS = {
    "prompt_bundle_id",
    "delegation_template_id",
    "context_envelope_id",
    "output_schema_id",
}


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for k in _INTERNAL_COLUMNS:
        d.pop(k, None)
    return d


def _empty_columns() -> list[dict[str, Any]]:
    return [
        {"name": "Assigned / Awaiting Hermione", "tasks": []},
        {"name": "Queued / Assigned", "tasks": []},
        {"name": "In Progress", "tasks": []},
        {"name": "Done", "tasks": []},
    ]


class HermesControllerCollector:
    """Snapshot the Controller v0 board and task detail in read-only mode."""

    name = "hermes_controller"

    def __init__(self, hermes_home: Path):
        override = os.getenv("HERMES_CONTROLLER_DB", "").strip()
        if override:
            self.db_path = Path(override).expanduser()
        else:
            self.db_path = resolve_child(hermes_home, "controller/controller.db")

    def _connect_ro(self) -> Optional[sqlite3.Connection]:
        if not self.db_path.exists():
            return None
        try:
            uri = f"file:{self.db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error:
            return None

    async def collect(self) -> dict[str, Any]:
        conn = self._connect_ro()
        if conn is None:
            return envelope(
                self.name,
                {
                    "columns": _empty_columns(),
                    "available": False,
                    "total": 0,
                    "execution_enabled": False,
                    "planning_only": True,
                    "polling_defaults": {"default_seconds": 10, "active_seconds": 5},
                },
            )
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
            if not cur.fetchone():
                return envelope(self.name, {"columns": _empty_columns(), "available": False, "total": 0})

            cur.execute(
                """
                SELECT t.*, j.title AS job_title
                  FROM tasks t
                  JOIN jobs j ON j.id = t.job_id
                 WHERE t.status NOT IN ('draft')
                 ORDER BY t.priority DESC, t.created_at ASC
                 LIMIT 200
                """
            )
            rows = [_controller_card(_row_to_dict(r)) for r in cur.fetchall()]
            columns = _empty_columns()
            by_name = {c["name"]: c for c in columns}
            for r in rows:
                status = str(r.get("status") or "")
                if status in _DONE_STATUSES or status in _CANCELLED_STATUSES:
                    by_name["Done"]["tasks"].append(r)
                elif status in _INPROGRESS_STATUSES:
                    by_name["In Progress"]["tasks"].append(r)
                elif status in _BACKLOG_STATUSES:
                    by_name["Queued / Assigned"]["tasks"].append(r)
                else:
                    by_name["Assigned / Awaiting Hermione"]["tasks"].append(r)

            return envelope(
                self.name,
                {
                    "available": True,
                    "columns": columns,
                    "total": sum(len(c["tasks"]) for c in columns),
                    "execution_enabled": False,
                    "planning_only": True,
                    "polling_defaults": {"default_seconds": 10, "active_seconds": 5},
                    "db_path": str(self.db_path),
                },
            )
        finally:
            conn.close()

    async def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        conn = self._connect_ro()
        if conn is None:
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT t.*, j.title AS job_title, j.description AS job_description
                  FROM tasks t
                  JOIN jobs j ON j.id = t.job_id
                 WHERE t.id = ?
                """,
                (task_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            task = _controller_card(_row_to_dict(row))
            cur.execute(
                "SELECT id, event_type, actor, details_json, created_at FROM task_events WHERE task_id = ? ORDER BY id DESC LIMIT 50",
                (task_id,),
            )
            events = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT id, path, kind, trust_level, summary, provenance, content_hash, created_at FROM artifacts WHERE task_id = ? ORDER BY created_at ASC LIMIT 50",
                (task_id,),
            )
            artifacts = [dict(r) for r in cur.fetchall()]
            return {"task": task, "events": events, "artifacts": artifacts}
        finally:
            conn.close()

    async def latest_event_id(self) -> int:
        conn = self._connect_ro()
        if conn is None:
            return 0
        try:
            try:
                row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM task_events").fetchone()
                return int(row[0] or 0)
            except sqlite3.OperationalError:
                return 0
        finally:
            conn.close()


def _controller_card(task: dict[str, Any]) -> dict[str, Any]:
    card = dict(task)
    card["source"] = "controller"
    card["assignee"] = card.get("agent_name") or "controller"
    card["selected_agent"] = card.get("agent_name")
    card["handoff_status"] = "planning-only"
    card["body"] = card.get("description") or ""
    card["job_title"] = card.get("job_title")
    return card
