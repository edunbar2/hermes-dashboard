"""Dashboard configuration — read from env vars with sane defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DashboardConfig:
    """Immutable runtime configuration.

    Values are sourced from environment variables on startup. The dashboard
    never mutates Hermes state — it only reads. All writes go to its own
    state file under ``hermes_home / "dashboard-state.json"``.
    """

    host: str
    port: int
    hermes_home: Path
    api_server_url: str
    profiles_dir: Path = Path.home() / "Hermes Profiles"
    task_alerts_enabled: bool = False

    @classmethod
    def from_env(cls) -> "DashboardConfig":
        return cls(
            host=os.getenv("HERMES_DASHBOARD_HOST", "0.0.0.0"),
            port=int(os.getenv("HERMES_DASHBOARD_PORT", "2002")),
            hermes_home=Path(
                os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))
            ),
            api_server_url=os.getenv(
                "HERMES_API_SERVER_URL", "http://127.0.0.1:8642/v1"
            ),
            profiles_dir=Path(
                os.getenv("HERMES_PROFILES_DIR", str(Path.home() / "Hermes Profiles"))
            ),
            task_alerts_enabled=os.getenv("HERMES_DASHBOARD_TASK_ALERTS", "0").lower()
            not in {"0", "false", "no", "off"},
        )
