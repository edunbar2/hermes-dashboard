"""Read-only view of ``~/.hermes/kanban.db``.

The dashboard never writes to this database. Cards are created and updated
through the agent's ``kanban_*`` tools and the kanban dispatcher; we just
project the current state for humans to look at.

Schema reference: ``hermes_cli/kanban_db.py`` in the hermes-agent repo.

Hermes uses these task statuses (verified against the live DB):
  triage    — newly created, awaiting refinement
  todo      — refined, queued for someone to pick up
  ready     — assigned but not yet claimed
  running   — claimed and being worked
  blocked   — running but stuck on something
  done      — completed successfully
  archived  — soft-deleted / EOD-archived

We bucket those into three on-screen columns:
  Backlog     ← triage, todo, ready
  In Progress ← running, blocked
  Done        ← done (archived hidden — they've been moved out of the board)
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from .base import envelope

_BACKLOG_STATUSES = {"triage", "todo", "ready"}
_INPROGRESS_STATUSES = {"running", "blocked"}
_DONE_STATUSES = {"done"}

# Hide Done cards older than 24h — Task 7.6's EOD cron will eventually move
# them to ``archived``, but we filter defensively in case the cron is paused.
_DONE_VISIBILITY_SECONDS = 24 * 3600

# Internal columns we strip from the wire payload (humans don't care, and
# some of them — like claim_lock — would leak agent-internal details).
_INTERNAL_COLUMNS = {
    "claim_lock",
    "claim_expires",
    "idempotency_key",
    "spawn_failures",
    "last_spawn_error",
    "tenant",
    "workflow_template_id",
}


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for k in _INTERNAL_COLUMNS:
        d.pop(k, None)
    return d


def _empty_columns() -> list[dict[str, Any]]:
    return [
        {"name": "Backlog", "tasks": []},
        {"name": "In Progress", "tasks": []},
        {"name": "Done", "tasks": []},
    ]


class HermesKanbanCollector:
    """Snapshot the kanban board and pull individual task detail."""

    name = "hermes_kanban"

    def __init__(self, hermes_home: Path):
        self.db_path = Path(hermes_home) / "kanban.db"

    def _connect_ro(self) -> Optional[sqlite3.Connection]:
        """Open the DB in read-only URI mode. Returns None if missing."""
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
                {"columns": _empty_columns(), "available": False, "total": 0},
            )

        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
            )
            if not cur.fetchone():
                return envelope(
                    self.name,
                    {"columns": _empty_columns(), "available": False, "total": 0},
                )

            now = int(time.time())
            cutoff = now - _DONE_VISIBILITY_SECONDS

            # Pull active rows (any non-archived status that isn't an old "done")
            # plus recent dones. The DB uses INTEGER timestamps for created_at
            # and completed_at, so the comparison is straightforward.
            active_statuses = sorted(
                _BACKLOG_STATUSES | _INPROGRESS_STATUSES | _DONE_STATUSES
            )
            placeholders = ",".join("?" for _ in active_statuses)
            cur.execute(
                f"""
                SELECT * FROM tasks
                 WHERE status IN ({placeholders})
                   AND (
                       status != 'done'
                       OR COALESCE(completed_at, created_at) >= ?
                   )
                 ORDER BY priority ASC, created_at DESC
                 LIMIT 200
                """,
                (*active_statuses, cutoff),
            )
            rows = [_row_to_dict(r) for r in cur.fetchall()]

            backlog: list[dict[str, Any]] = []
            inprog: list[dict[str, Any]] = []
            done: list[dict[str, Any]] = []
            for r in rows:
                s = r.get("status", "")
                if s in _BACKLOG_STATUSES:
                    backlog.append(r)
                elif s in _INPROGRESS_STATUSES:
                    inprog.append(r)
                elif s in _DONE_STATUSES:
                    done.append(r)

            columns = [
                {"name": "Backlog", "tasks": backlog},
                {"name": "In Progress", "tasks": inprog},
                {"name": "Done", "tasks": done},
            ]
            return envelope(
                self.name,
                {
                    "columns": columns,
                    "available": True,
                    "total": sum(len(c["tasks"]) for c in columns),
                },
            )
        finally:
            conn.close()

    async def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        """Return ``{task, comments, events}`` or None if not found."""
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

            # task_comments may not exist on very old DBs — guard.
            try:
                cur.execute(
                    "SELECT id, author, body, created_at FROM task_comments "
                    "WHERE task_id = ? ORDER BY created_at ASC LIMIT 200",
                    (task_id,),
                )
                comments = [dict(r) for r in cur.fetchall()]
            except sqlite3.OperationalError:
                comments = []

            try:
                cur.execute(
                    "SELECT id, run_id, kind, payload, created_at "
                    "FROM task_events WHERE task_id = ? "
                    "ORDER BY id DESC LIMIT 50",
                    (task_id,),
                )
                events = [dict(r) for r in cur.fetchall()]
            except sqlite3.OperationalError:
                events = []

            return {"task": task, "comments": comments, "events": events}
        finally:
            conn.close()

    async def latest_event_id(self) -> int:
        """Highest task_events.id — used as a cheap change-detector for SSE."""
        conn = self._connect_ro()
        if conn is None:
            return 0
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM task_events")
                return int(cur.fetchone()[0])
            except sqlite3.OperationalError:
                return 0
        finally:
            conn.close()
