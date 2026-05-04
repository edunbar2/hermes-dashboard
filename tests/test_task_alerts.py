from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hermes_dashboard.api import tasks as api_tasks
from hermes_dashboard.app import create_app
from hermes_dashboard.config import DashboardConfig


@pytest.mark.anyio
async def test_dashboard_task_create_schedules_hermione_alert(tmp_path, monkeypatch):
    sent: list[tuple[str, str]] = []

    async def fake_alert(config, task):
        sent.append((config.api_server_url, task["title"]))

    monkeypatch.setattr(api_tasks, "send_dashboard_task_alert", fake_alert)
    cfg = DashboardConfig(
        host="127.0.0.1",
        port=2002,
        hermes_home=tmp_path,
        api_server_url="http://127.0.0.1:8642/v1",
        task_alerts_enabled=True,
    )
    client = TestClient(create_app(cfg))

    with client:
        r = client.post(
            "/api/tasks",
            json={"title": "Review new kanban alert flow", "priority": 2},
        )

    assert r.status_code == 200
    assert sent == [("http://127.0.0.1:8642/v1", "Review new kanban alert flow")]


@pytest.mark.anyio
async def test_dashboard_task_alert_prompt_is_self_contained(config):
    task = {
        "id": "dash-123",
        "title": "Fix dashboard storage card",
        "body": "Make storage prominent",
        "priority": 2,
        "preferred_agent": "hephaestus",
        "created_at": 1777777777,
    }

    prompt = api_tasks.build_dashboard_task_alert_prompt(task)

    assert "New dashboard kanban task" in prompt
    assert "dash-123" in prompt
    assert "Fix dashboard storage card" in prompt
    assert "preferred agent: hephaestus" in prompt
    assert "Open the Hermes Dashboard" in prompt
