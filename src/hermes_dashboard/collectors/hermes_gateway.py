"""Gateway status — read pidfile + live process inspection."""
from __future__ import annotations

import json
from pathlib import Path

import psutil

from .base import envelope


class HermesGatewayCollector:
    name = "hermes_gateway"

    def __init__(self, hermes_home: Path):
        self.hermes_home = hermes_home

    async def collect(self) -> dict:
        pidfile = self.hermes_home / "gateway.pid"
        running = False
        pid: int | None = None
        cmdline: str | None = None
        if pidfile.exists():
            raw = pidfile.read_text().strip()
            # Hermes writes the pidfile as JSON: {"pid": N, "kind": ..., "argv": ...}
            # Older versions wrote just the bare integer. Handle both.
            try:
                if raw.startswith("{"):
                    pid = int(json.loads(raw).get("pid", 0)) or None
                else:
                    pid = int(raw)
            except (ValueError, json.JSONDecodeError):
                pid = None
            if pid and psutil.pid_exists(pid):
                try:
                    p = psutil.Process(pid)
                    cmdline = " ".join(p.cmdline())
                    running = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        state: dict = {}
        state_file = self.hermes_home / "gateway_state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
            except (OSError, json.JSONDecodeError):
                pass

        return envelope(
            self.name,
            {
                "running": running,
                "pid": pid,
                "cmdline": cmdline,
                "state": state,
            },
        )
