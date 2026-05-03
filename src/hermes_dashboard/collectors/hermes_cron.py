"""Cron jobs from ~/.hermes/cron/jobs.json."""
from __future__ import annotations

import json
from pathlib import Path

from .base import envelope


class HermesCronCollector:
    name = "hermes_cron"

    def __init__(self, hermes_home: Path):
        self.jobs_file = hermes_home / "cron" / "jobs.json"

    async def collect(self) -> dict:
        jobs: list[dict] = []
        if self.jobs_file.exists():
            try:
                raw = json.loads(self.jobs_file.read_text())
                # Hermes stores cron as either {"jobs": [...]} or a top-level dict;
                # be defensive.
                if isinstance(raw, dict) and "jobs" in raw and isinstance(raw["jobs"], list):
                    jobs = raw["jobs"]
                elif isinstance(raw, list):
                    jobs = raw
                elif isinstance(raw, dict):
                    jobs = list(raw.values())
            except (OSError, json.JSONDecodeError):
                pass

        active = sum(1 for j in jobs if isinstance(j, dict) and j.get("enabled", True))
        return envelope(
            self.name,
            {"jobs": jobs, "count": len(jobs), "active": active},
        )
