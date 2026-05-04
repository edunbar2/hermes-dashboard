from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from hermes_dashboard.app import create_app
from hermes_dashboard.config import DashboardConfig


_CONTROLLER_SCHEMA = """
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 0,
    risk_level TEXT NOT NULL DEFAULT 'planning',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    completed_at INTEGER
);
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 0,
    risk_level TEXT NOT NULL DEFAULT 'planning',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    scheduled_at INTEGER,
    assigned_at INTEGER,
    started_at INTEGER,
    completed_at INTEGER,
    summary TEXT,
    prompt_bundle_id TEXT,
    delegation_template_id TEXT,
    context_envelope_id TEXT,
    output_schema_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    job_id TEXT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'controller',
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    job_id TEXT,
    path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'obsidian_ref',
    trust_level TEXT NOT NULL DEFAULT 'untrusted',
    summary TEXT,
    provenance TEXT NOT NULL DEFAULT 'controller_cli',
    content_hash TEXT,
    created_at INTEGER NOT NULL
);
"""


def _seed_controller(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True)
    now = int(time.time())
    conn = sqlite3.connect(db_path)
    conn.executescript(_CONTROLLER_SCHEMA)
    conn.execute(
        "INSERT INTO jobs(id,title,description,status,priority,risk_level,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("job-1", "Controller smoke", "Planning-only job", "queued", 2, "planning", now - 100, now - 100),
    )
    conn.executemany(
        "INSERT INTO tasks(id,job_id,title,description,agent_name,status,priority,risk_level,created_at,updated_at,assigned_at,completed_at,summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("ct-ready", "job-1", "Athena research", "Collect sources", "Athena", "ready", 10, "planning", now - 90, now - 90, None, None, None),
            ("ct-assigned", "job-1", "Hephaestus plan", "Draft local plan", "Hephaestus", "assigned", 5, "planning", now - 80, now - 70, now - 70, None, None),
            ("ct-done", "job-1", "Aegis review", "Review risks", "Aegis", "completed", 1, "planning", now - 60, now - 10, now - 50, now - 10, "Looks safe"),
        ],
    )
    conn.execute(
        "INSERT INTO task_events(task_id,job_id,event_type,actor,details_json,created_at) VALUES (?,?,?,?,?,?)",
        ("ct-assigned", "job-1", "task_assigned", "controller", '{"planning_only":true}', now - 70),
    )
    conn.execute(
        "INSERT INTO artifacts(id,task_id,job_id,path,kind,trust_level,summary,provenance,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("art-1", "ct-assigned", "job-1", "/opt/obsidian_vault/Agent-Shared/reports/controller.md", "obsidian_ref", "untrusted", "result ref", "controller_cli", now - 60),
    )
    conn.commit()
    conn.close()


def _client(tmp_path: Path) -> TestClient:
    _seed_controller(tmp_path / "controller" / "controller.db")
    cfg = DashboardConfig(
        host="127.0.0.1",
        port=2002,
        hermes_home=tmp_path,
        api_server_url="http://127.0.0.1:8642/v1",
    )
    return TestClient(create_app(cfg))


def test_controller_board_endpoint_projects_columns(tmp_path):
    client = _client(tmp_path)
    r = client.get("/api/controller/board")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["available"] is True
    assert data["planning_only"] is True
    assert data["execution_enabled"] is False
    cols = {c["name"]: [t["id"] for t in c["tasks"]] for c in data["columns"]}
    assert cols["Queued / Assigned"] == ["ct-ready"]
    assert cols["In Progress"] == ["ct-assigned"]
    assert cols["Done"] == ["ct-done"]


def test_controller_task_detail_exposes_events_and_artifact_refs(tmp_path):
    client = _client(tmp_path)
    r = client.get("/api/controller/tasks/ct-assigned")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["task"]["source"] == "controller"
    assert data["task"]["assignee"] == "Hephaestus"
    assert data["events"][0]["event_type"] == "task_assigned"
    assert data["artifacts"][0]["path"].startswith("/opt/obsidian_vault/")


def test_combined_task_board_includes_controller_cards(tmp_path):
    client = _client(tmp_path)
    r = client.get("/api/tasks/board")
    assert r.status_code == 200
    data = r.json()["data"]
    all_cards = [t for c in data["columns"] for t in c["tasks"]]
    assert any(t["id"] == "ct-ready" and t["source"] == "controller" for t in all_cards)
    assert any(t["id"] == "ct-assigned" and t["source"] == "controller" for t in all_cards)
