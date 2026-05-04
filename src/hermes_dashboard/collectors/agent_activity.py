"""Agent activity collector derived from kanban state.

This is a read-only projection. It never mutates Hermes' kanban DB; it only
infers each specialist's current visible work for the control deck.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from ..agents import all_agents, normalize_agent
from .base import envelope

_ACTIVE_STATUSES = {"running", "blocked"}
_ASSIGNED_STATUSES = {"triage", "todo", "ready"}
_DONE_STATUSES = {"done"}


def _connect_ro(db_path: Path) -> Optional[sqlite3.Connection]:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _progress_for_task(task: dict[str, Any]) -> tuple[int, str]:
    status = str(task.get("status") or "").lower()
    if status == "done":
        return 100, "complete"
    if status == "blocked":
        return 35, "blocked"
    if status == "running":
        step = task.get("current_step_key")
        if step:
            return 60, f"step: {step}"
        if task.get("last_heartbeat_at"):
            return 55, "heartbeat active"
        return 50, "running"
    if status in _ASSIGNED_STATUSES:
        return 10, "queued"
    return 0, "idle"


def _pick_current(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not tasks:
        return None
    status_rank = {"running": 0, "blocked": 1, "ready": 2, "todo": 3, "triage": 4, "done": 5}
    return sorted(
        tasks,
        key=lambda t: (
            status_rank.get(str(t.get("status") or ""), 9),
            int(t.get("priority") or 99),
            -(int(t.get("last_heartbeat_at") or t.get("started_at") or t.get("created_at") or 0)),
        ),
    )[0]


class AgentActivityCollector:
    name = "agent_activity"

    def __init__(self, hermes_home: Path):
        self.db_path = Path(hermes_home) / "kanban.db"

    def _tasks_by_agent(self) -> tuple[bool, dict[str, list[dict[str, Any]]]]:
        conn = _connect_ro(self.db_path)
        if conn is None:
            return False, {}
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
            if not cur.fetchone():
                return False, {}
            cur.execute(
                """
                SELECT id, title, body, assignee, status, priority, created_at,
                       started_at, completed_at, worker_pid, last_heartbeat_at,
                       current_run_id, current_step_key, skills
                  FROM tasks
                 WHERE status IN ('triage','todo','ready','running','blocked','done')
                   AND status != 'archived'
                 ORDER BY priority ASC, created_at DESC
                 LIMIT 500
                """
            )
            grouped: dict[str, list[dict[str, Any]]] = {}
            now = int(time.time())
            for row in cur.fetchall():
                task = dict(row)
                agent_id = normalize_agent(task.get("assignee"))
                if agent_id is None:
                    continue
                # Recent done contributes to the deck for 3 days; older done is not active context.
                if task.get("status") == "done":
                    completed = int(task.get("completed_at") or task.get("created_at") or 0)
                    if completed < now - (3 * 24 * 3600):
                        continue
                grouped.setdefault(agent_id, []).append(task)
            return True, grouped
        except sqlite3.Error:
            return False, {}
        finally:
            conn.close()

    async def collect(self) -> dict[str, Any]:
        available, grouped = self._tasks_by_agent()
        now = int(time.time())
        agents: list[dict[str, Any]] = []
        for profile in all_agents():
            tasks = grouped.get(profile.id, [])
            current = _pick_current(tasks)
            active_count = sum(1 for t in tasks if t.get("status") in _ACTIVE_STATUSES)
            assigned_count = sum(1 for t in tasks if t.get("status") in _ASSIGNED_STATUSES)
            done_recent_count = sum(1 for t in tasks if t.get("status") in _DONE_STATUSES)
            if current:
                progress, label = _progress_for_task(current)
                status = str(current.get("status") or "unknown")
                last_update = int(
                    current.get("last_heartbeat_at")
                    or current.get("started_at")
                    or current.get("completed_at")
                    or current.get("created_at")
                    or now
                )
            else:
                progress, label, status, last_update = 0, "idle", "idle", None
            agents.append(
                {
                    "id": profile.id,
                    "name": profile.name,
                    "role": profile.role,
                    "avatar_url": profile.avatar_url,
                    "active": bool(active_count),
                    "status": status,
                    "current_task": current.get("title") if current else None,
                    "current_task_id": current.get("id") if current else None,
                    "progress_percent": progress,
                    "progress_label": label,
                    "last_update": last_update,
                    "active_count": active_count,
                    "assigned_count": assigned_count,
                    "done_recent_count": done_recent_count,
                    "stale": bool(last_update and (now - last_update > 30 * 60) and status in _ACTIVE_STATUSES),
                }
            )
        return envelope(
            self.name,
            {"available": available, "agents": agents, "updated_at": now},
        )

    async def latest_event_id(self) -> int:
        conn = _connect_ro(self.db_path)
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
