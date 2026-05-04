from __future__ import annotations

import json
import time


def test_post_task_creates_dashboard_owned_request(client, tmp_path):
    r = client.post(
        "/api/tasks",
        json={"title": "Research STT options", "body": "Compare local vs cloud", "priority": 2},
    )
    assert r.status_code == 200
    task = r.json()["data"]["task"]
    assert task["id"].startswith("dash-")
    assert task["assignee"] == "Hermione"
    assert task["handoff_status"] == "awaiting_hermione"

    state = json.loads((tmp_path / "dashboard-state.json").read_text())
    assert state["dashboard_tasks"][0]["title"] == "Research STT options"


def test_tasks_board_includes_dashboard_request_in_awaiting_column(client):
    client.post("/api/tasks", json={"title": "Build lab", "priority": 1})
    r = client.get("/api/tasks/board")
    assert r.status_code == 200
    cols = {c["name"]: c["tasks"] for c in r.json()["data"]["columns"]}
    awaiting = cols["Assigned / Awaiting Hermione"]
    assert len(awaiting) == 1
    assert awaiting[0]["title"] == "Build lab"
    assert awaiting[0]["source"] == "dashboard"


def test_patch_dashboard_task_selects_agent(client):
    task = client.post("/api/tasks", json={"title": "Review risk"}).json()["data"]["task"]
    r = client.patch(f"/api/tasks/{task['id']}", json={"selected_agent": "aegis", "status": "todo"})
    assert r.status_code == 200
    updated = r.json()["data"]["task"]
    assert updated["selected_agent"] == "aegis"

    board = client.get("/api/tasks/board").json()["data"]
    cols = {c["name"]: c["tasks"] for c in board["columns"]}
    assert cols["Queued / Assigned"][0]["id"] == task["id"]


def test_patch_rejects_unbounded_or_unknown_values(client):
    task = client.post("/api/tasks", json={"title": "Guardrails"}).json()["data"]["task"]
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "pwned"}).status_code == 422
    assert client.patch(f"/api/tasks/{task['id']}", json={"title": "x" * 200}).status_code == 422


def test_archive_done_dashboard_tasks_older_than_three_days(client, tmp_path):
    task = client.post("/api/tasks", json={"title": "Old complete"}).json()["data"]["task"]
    old = int(time.time()) - 4 * 86400
    client.patch(f"/api/tasks/{task['id']}", json={"status": "done"})

    state_path = tmp_path / "dashboard-state.json"
    state = json.loads(state_path.read_text())
    state["dashboard_tasks"][0]["completed_at"] = old
    state["dashboard_tasks"][0]["updated_at"] = old
    state_path.write_text(json.dumps(state))

    r = client.post("/api/tasks/archive")
    assert r.status_code == 200
    assert r.json()["archived"] == 1
    board = client.get("/api/tasks/board").json()["data"]
    assert all(not c["tasks"] for c in board["columns"])
