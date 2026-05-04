"""Test fixtures shared across the suite."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hermes_dashboard.app import create_app
from hermes_dashboard.config import DashboardConfig


@pytest.fixture
def config(tmp_path) -> DashboardConfig:
    """A config pointed at a clean tmp dir — never touches the real ~/.hermes."""
    return DashboardConfig(
        host="127.0.0.1",
        port=2002,
        hermes_home=tmp_path,
        api_server_url="http://127.0.0.1:8642/v1",
        task_alerts_enabled=False,
    )


@pytest.fixture
def client(config) -> TestClient:
    return TestClient(create_app(config))
