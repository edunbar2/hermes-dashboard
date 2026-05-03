import json
import os
import sqlite3
import time
from pathlib import Path


def _seed_state_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            user_id TEXT,
            model TEXT,
            model_config TEXT,
            system_prompt TEXT,
            parent_session_id TEXT,
            started_at REAL,
            ended_at REAL,
            end_reason TEXT,
            message_count INTEGER,
            tool_call_count INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read_tokens INTEGER,
            cache_write_tokens INTEGER,
            reasoning_tokens INTEGER,
            billing_provider TEXT,
            billing_base_url TEXT,
            billing_mode TEXT,
            estimated_cost_usd REAL,
            actual_cost_usd REAL,
            cost_status TEXT,
            cost_source TEXT,
            pricing_version TEXT,
            title TEXT,
            api_call_count INTEGER
        );
        """
    )
    now = time.time()
    conn.execute(
        "INSERT INTO sessions(id, source, model, started_at, ended_at, message_count, tool_call_count, title) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("s1", "discord", "claude-opus-4-7", now - 3600, now - 1800, 30, 12, "Old session"),
    )
    conn.execute(
        "INSERT INTO sessions(id, source, model, started_at, ended_at, message_count, tool_call_count, title) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("s2", "signal", "claude-opus-4-7", now - 600, None, 5, 2, "Active session"),
    )
    conn.commit()
    conn.close()


def _seed_cron_jobs(hermes_home: Path) -> None:
    cron_dir = hermes_home / "cron"
    cron_dir.mkdir(parents=True, exist_ok=True)
    (cron_dir / "jobs.json").write_text(
        json.dumps({"jobs": [
            {"id": "j1", "name": "daily-report", "enabled": True, "schedule": "0 9 * * *"},
            {"id": "j2", "name": "old-archived", "enabled": False, "schedule": "0 0 * * 0"},
        ]})
    )


def test_gateway_status_no_pidfile(client):
    r = client.get("/api/hermes/gateway")
    assert r.status_code == 200
    assert r.json()["data"]["running"] is False


def test_gateway_status_with_live_pidfile(client, config):
    pidfile = config.hermes_home / "gateway.pid"
    pidfile.write_text(str(os.getpid()))  # bare-PID format (legacy)
    try:
        r = client.get("/api/hermes/gateway")
        body = r.json()["data"]
        assert body["running"] is True
        assert body["pid"] == os.getpid()
    finally:
        pidfile.unlink()


def test_gateway_status_json_pidfile(client, config):
    """Hermes writes pidfile as JSON: {pid, kind, argv}. Make sure we parse it."""
    pidfile = config.hermes_home / "gateway.pid"
    pidfile.write_text(json.dumps({"pid": os.getpid(), "kind": "hermes-gateway", "argv": []}))
    try:
        body = client.get("/api/hermes/gateway").json()["data"]
        assert body["running"] is True
        assert body["pid"] == os.getpid()
    finally:
        pidfile.unlink()


def test_gateway_status_stale_pidfile(client, config):
    # PID 999999 is virtually guaranteed not to exist
    pidfile = config.hermes_home / "gateway.pid"
    pidfile.write_text("999999")
    try:
        body = client.get("/api/hermes/gateway").json()["data"]
        assert body["running"] is False
    finally:
        pidfile.unlink()


def test_sessions_endpoint_empty(client):
    r = client.get("/api/hermes/sessions?limit=5")
    assert r.status_code == 200
    body = r.json()["data"]
    assert "sessions" in body
    assert body["count"] == 0


def test_sessions_with_data(client, config):
    _seed_state_db(config.hermes_home / "state.db")
    body = client.get("/api/hermes/sessions?limit=5").json()["data"]
    assert body["count"] == 2
    titles = [s["title"] for s in body["sessions"]]
    assert "Active session" in titles
    assert body["active"] == 1  # s2 has ended_at NULL


def test_cron_endpoint_empty(client):
    body = client.get("/api/hermes/cron").json()["data"]
    assert body["count"] == 0
    assert body["active"] == 0


def test_cron_with_data(client, config):
    _seed_cron_jobs(config.hermes_home)
    body = client.get("/api/hermes/cron").json()["data"]
    assert body["count"] == 2
    assert body["active"] == 1


def test_status_aggregate(client, config):
    _seed_state_db(config.hermes_home / "state.db")
    _seed_cron_jobs(config.hermes_home)
    body = client.get("/api/hermes/status").json()["data"]
    assert "gateway" in body
    assert body["sessions_count"] == 2
    assert body["active_sessions"] == 1
    assert body["cron_active"] == 1
    assert len(body["recent_sessions"]) <= 5
