from __future__ import annotations

import sqlite3
import time

from fastapi.testclient import TestClient

from hermes_dashboard.app import create_app
from hermes_dashboard.config import DashboardConfig
from tests.test_api_kanban import _TASKS_SCHEMA


def _client(tmp_path, profiles_dir=None) -> TestClient:
    cfg = DashboardConfig(
        host="127.0.0.1",
        port=2002,
        hermes_home=tmp_path,
        api_server_url="http://127.0.0.1:8642/v1",
        profiles_dir=profiles_dir or (tmp_path / "profiles"),
    )
    return TestClient(create_app(cfg))


def test_agent_roster_contains_expected_agents(tmp_path):
    client = _client(tmp_path)
    r = client.get("/api/agents/roster")
    assert r.status_code == 200
    agents = r.json()["data"]["agents"]
    assert [a["id"] for a in agents] == [
        "hermione", "hephaestus", "argus", "athena", "aegis", "daedalus", "vox"
    ]
    assert all(a["avatar_url"].startswith("/api/agents/") for a in agents)


def test_unknown_avatar_is_404(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/agents/not-real/avatar").status_code == 404


def test_known_avatar_served_from_allowlisted_profile_file(tmp_path):
    profiles = tmp_path / "Hermes Profiles"
    profiles.mkdir()
    (profiles / "Hermione.png").write_bytes(b"fake-png")
    client = _client(tmp_path, profiles)
    r = client.get("/api/agents/hermione/avatar")
    assert r.status_code == 200
    assert r.content == b"fake-png"


def test_agent_status_idle_when_kanban_missing(tmp_path):
    client = _client(tmp_path)
    r = client.get("/api/agents/status")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["available"] is False
    assert len(data["agents"]) == 7
    assert all(a["status"] == "idle" for a in data["agents"])


def test_agent_status_uses_assigned_kanban_tasks(tmp_path):
    db = tmp_path / "kanban.db"
    conn = sqlite3.connect(db)
    conn.executescript(_TASKS_SCHEMA)
    now = int(time.time())
    conn.execute(
        "INSERT INTO tasks(id, title, assignee, status, priority, created_at, started_at, last_heartbeat_at, current_step_key) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("t-code", "Implement dashboard", "Hephaestus", "running", 1, now - 100, now - 90, now - 10, "ui"),
    )
    conn.execute(
        "INSERT INTO task_events(task_id, kind, payload, created_at) VALUES (?,?,?,?)",
        ("t-code", "started", "{}", now - 90),
    )
    conn.commit()
    conn.close()

    client = _client(tmp_path)
    agents = client.get("/api/agents/status").json()["data"]["agents"]
    heph = next(a for a in agents if a["id"] == "hephaestus")
    assert heph["active"] is True
    assert heph["status"] == "running"
    assert heph["current_task"] == "Implement dashboard"
    assert heph["progress_percent"] >= 50
