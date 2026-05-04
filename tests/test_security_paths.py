from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from hermes_dashboard.app import create_app
from hermes_dashboard.config import DashboardConfig
from hermes_dashboard import state
from hermes_dashboard.safe_paths import resolve_child


def test_resolve_child_rejects_parent_traversal(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    try:
        resolve_child(root, "..", "outside.txt")
    except ValueError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("parent traversal was not rejected")


def test_dashboard_state_path_is_confined_to_hermes_home(tmp_path):
    hermes_home = tmp_path / "home"
    p = state.state_path(hermes_home)

    assert p == (hermes_home / "dashboard-state.json").resolve()
    assert p.parent == hermes_home.resolve()


def test_malicious_avatar_agent_id_never_reaches_file_response(tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "Hermione.png").write_bytes(b"fake png bytes")
    cfg = DashboardConfig(
        host="127.0.0.1",
        port=2002,
        hermes_home=tmp_path / "home",
        api_server_url="http://127.0.0.1:8642/v1",
        profiles_dir=profiles,
    )
    client = TestClient(create_app(cfg))

    ok = client.get("/api/agents/hermione/avatar")
    assert ok.status_code == 200

    traversal = client.get("/api/agents/..%2F..%2Fetc%2Fpasswd/avatar")
    assert traversal.status_code in {404, 422}
