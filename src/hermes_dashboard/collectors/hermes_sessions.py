"""Recent sessions from ~/.hermes/state.db.

Read-only — uses ``mode=ro`` URI. Schema is documented in
``hermes_cli/hermes_state.py`` upstream; we read the columns most useful
for a humans-skimming-the-dashboard view.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .base import envelope


# Columns we actually surface — keep the API payload small.
_DISPLAY_COLS = (
    "id", "source", "user_id", "model", "title",
    "started_at", "ended_at", "end_reason",
    "message_count", "tool_call_count", "api_call_count",
    "input_tokens", "output_tokens",
)


class HermesSessionsCollector:
    name = "hermes_sessions"

    def __init__(self, hermes_home: Path):
        self.db_path = hermes_home / "state.db"

    async def collect(self, limit: int = 20) -> dict:
        sessions: list[dict] = []
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(
                    f"file:{self.db_path}?mode=ro", uri=True, timeout=2.0
                )
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
                )
                if cur.fetchone():
                    cols = ", ".join(_DISPLAY_COLS)
                    cur.execute(
                        f"SELECT {cols} FROM sessions "
                        "ORDER BY COALESCE(ended_at, started_at) DESC LIMIT ?",
                        (limit,),
                    )
                    sessions = [dict(row) for row in cur.fetchall()]
                conn.close()
            except sqlite3.Error:
                # DB exists but query failed — return empty rather than 500.
                pass

        active = sum(1 for s in sessions if s.get("ended_at") is None)
        return envelope(
            self.name,
            {"sessions": sessions, "count": len(sessions), "active": active},
        )
