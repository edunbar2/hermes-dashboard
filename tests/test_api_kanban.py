"""Tests for the kanban panel API.

Seeds a fake ``kanban.db`` in tmp_path matching the real Hermes schema
and verifies the dashboard buckets tasks into Backlog / In Progress / Done
correctly, exposes per-task detail, filters old Done cards, and 404s on
missing ids.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_dashboard.app import create_app
from hermes_dashboard.config import DashboardConfig


# Mirrors the real Hermes tasks-table schema (hermes_cli/kanban_db.py).
# We don't have to reproduce every index / trigger — just the columns the
# collector reads.
_TASKS_SCHEMA = """
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
"""


def _seed_kanban(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(_TASKS_SCHEMA)
    now = int(time.time())
    conn.executemany(
        "INSERT INTO tasks(id, title, body, status, priority, created_at, "
        "started_at, completed_at, created_by, assignee) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            # Done - recent
            ("t-1", "Set up Discord gateway", "Configure Discord bot token",
             "done", 2, now - 3600, now - 3500, now - 1800, "eric", "hermes"),
            # In progress (running)
            ("t-2", "Build Obsidian memory vault", "Wire SOUL.md + AGENTS.md",
             "running", 1, now - 1800, now - 1700, None, "hermes", "hermes"),
            # In progress (blocked)
            ("t-2b", "Fix flaky import", "Waiting on CI fix",
             "blocked", 1, now - 900, now - 800, None, "hermes", "hermes"),
            # Backlog (todo)
            ("t-3", "Build Hermes dashboard", "Port 2002, system + chat",
             "todo", 1, now - 300, None, None, "eric", "hermes"),
            # Backlog (triage)
            ("t-3b", "Investigate weird ptyrace bug", "no repro yet",
             "triage", 3, now - 200, None, None, "eric", None),
            # Backlog (ready)
            ("t-3c", "Add health check endpoint", "Just needs assigning",
             "ready", 2, now - 100, None, None, "eric", "hermes"),
            # Archived — must NOT show up
            ("t-arch", "Old archived thing", "Was done long ago",
             "archived", 2, now - 86400 * 7, now - 86400 * 7,
             now - 86400 * 7, "eric", "hermes"),
        ],
    )
    # Comments + events on t-2 so the detail endpoint has something to return
    conn.execute(
        "INSERT INTO task_comments(task_id, author, body, created_at) "
        "VALUES (?,?,?,?)",
        ("t-2", "hermes", "started working on this", now - 1700),
    )
    conn.execute(
        "INSERT INTO task_events(task_id, run_id, kind, payload, created_at) "
        "VALUES (?,?,?,?,?)",
        ("t-2", None, "claimed", '{"by":"hermes"}', now - 1700),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def kanban_client(tmp_path) -> TestClient:
    db = tmp_path / "kanban.db"
    _seed_kanban(db)
    cfg = DashboardConfig(
        host="127.0.0.1",
        port=2002,
        hermes_home=tmp_path,
        api_server_url="http://127.0.0.1:8642/v1",
    )
    return TestClient(create_app(cfg))


def test_board_returns_three_columns(kanban_client):
    r = kanban_client.get("/api/kanban/board")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["available"] is True
    cols = {c["name"]: c for c in body["columns"]}
    assert set(cols.keys()) == {"Backlog", "In Progress", "Done"}


def test_board_buckets_each_status_correctly(kanban_client):
    r = kanban_client.get("/api/kanban/board")
    cols = {c["name"]: [t["id"] for t in c["tasks"]]
            for c in r.json()["data"]["columns"]}

    # Backlog: triage + todo + ready
    assert set(cols["Backlog"]) == {"t-3", "t-3b", "t-3c"}
    # In Progress: running + blocked
    assert set(cols["In Progress"]) == {"t-2", "t-2b"}
    # Done: recent done only
    assert set(cols["Done"]) == {"t-1"}


def test_archived_tasks_hidden(kanban_client):
    r = kanban_client.get("/api/kanban/board")
    cols = r.json()["data"]["columns"]
    all_ids = {t["id"] for c in cols for t in c["tasks"]}
    assert "t-arch" not in all_ids


def test_old_done_tasks_filtered(kanban_client, tmp_path):
    """Done cards older than 24h must drop off the board even if not archived."""
    conn = sqlite3.connect(tmp_path / "kanban.db")
    old = int(time.time()) - 86400 * 3
    conn.execute(
        "INSERT INTO tasks(id, title, status, priority, created_at, completed_at) "
        "VALUES (?,?,?,?,?,?)",
        ("t-old", "Ancient task", "done", 2, old, old),
    )
    conn.commit()
    conn.close()
    r = kanban_client.get("/api/kanban/board")
    done_ids = next(
        c["tasks"] for c in r.json()["data"]["columns"] if c["name"] == "Done"
    )
    assert not any(t["id"] == "t-old" for t in done_ids)


def test_task_detail_returns_comments_and_events(kanban_client):
    r = kanban_client.get("/api/kanban/tasks/t-2")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["task"]["id"] == "t-2"
    assert body["task"]["status"] == "running"
    assert len(body["comments"]) == 1
    assert body["comments"][0]["body"] == "started working on this"
    assert len(body["events"]) == 1
    assert body["events"][0]["kind"] == "claimed"


def test_task_detail_strips_internal_columns(kanban_client):
    """claim_lock / idempotency_key / etc. should not leak to clients."""
    r = kanban_client.get("/api/kanban/tasks/t-2")
    task = r.json()["data"]["task"]
    for col in ("claim_lock", "claim_expires", "idempotency_key",
                "spawn_failures", "last_spawn_error"):
        assert col not in task, f"internal column {col!r} leaked"


def test_task_404(kanban_client):
    r = kanban_client.get("/api/kanban/tasks/does-not-exist")
    assert r.status_code == 404


def test_board_empty_when_db_missing(tmp_path):
    """No kanban.db at all → still 200, just available=false."""
    cfg = DashboardConfig(
        host="127.0.0.1",
        port=2002,
        hermes_home=tmp_path,  # tmp_path empty -> no kanban.db
        api_server_url="http://127.0.0.1:8642/v1",
    )
    client = TestClient(create_app(cfg))
    r = client.get("/api/kanban/board")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["available"] is False
    assert body["total"] == 0
    # All three columns still present (empty)
    cols = {c["name"]: c["tasks"] for c in body["columns"]}
    assert cols["Backlog"] == cols["In Progress"] == cols["Done"] == []


def test_archive_endpoint_sets_watermark(kanban_client):
    """POST /api/kanban/archive returns and persists a fresh watermark."""
    r = kanban_client.post("/api/kanban/archive")
    assert r.status_code == 200
    body = r.json()
    assert body["archived_at"] == body["watermark"]
    assert body["archived_at"] > 0


def test_archive_clears_done_column(kanban_client):
    """After archive, recent Done cards should disappear from the board."""
    # Confirm Done has the recent t-1 first
    pre = kanban_client.get("/api/kanban/board").json()["data"]
    done_pre = next(c["tasks"] for c in pre["columns"] if c["name"] == "Done")
    assert any(t["id"] == "t-1" for t in done_pre)

    # Archive
    kanban_client.post("/api/kanban/archive")

    # Now Done should be empty (t-1 completed_at is < watermark = now())
    post = kanban_client.get("/api/kanban/board").json()["data"]
    done_post = next(c["tasks"] for c in post["columns"] if c["name"] == "Done")
    assert done_post == []

    # In-progress and Backlog must NOT be affected by archive.
    inprog_post = next(c["tasks"] for c in post["columns"] if c["name"] == "In Progress")
    assert {t["id"] for t in inprog_post} == {"t-2", "t-2b"}


def test_state_module_roundtrip(tmp_path):
    """Direct unit test for the state module — atomic write, default zero."""
    from hermes_dashboard import state as ds

    assert ds.get_archive_watermark(tmp_path) == 0
    ts = ds.set_archive_watermark(tmp_path)
    assert ds.get_archive_watermark(tmp_path) == ts

    # Corrupt file → falls back to {} silently
    (tmp_path / "dashboard-state.json").write_text("not json")
    assert ds.load(tmp_path) == {}
    assert ds.get_archive_watermark(tmp_path) == 0

