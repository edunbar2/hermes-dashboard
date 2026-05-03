"""Aggregate Hermes status — gateway + recent sessions + cron summary."""
from __future__ import annotations

from pathlib import Path

from .base import envelope
from .hermes_cron import HermesCronCollector
from .hermes_gateway import HermesGatewayCollector
from .hermes_sessions import HermesSessionsCollector


class HermesStatusCollector:
    name = "hermes_status"

    def __init__(self, hermes_home: Path):
        self.gateway = HermesGatewayCollector(hermes_home)
        self.sessions = HermesSessionsCollector(hermes_home)
        self.cron = HermesCronCollector(hermes_home)

    async def collect(self) -> dict:
        gw = await self.gateway.collect()
        sess = await self.sessions.collect(limit=5)
        cron = await self.cron.collect()
        return envelope(
            self.name,
            {
                "gateway": gw["data"],
                "recent_sessions": sess["data"]["sessions"],
                "sessions_count": sess["data"]["count"],
                "active_sessions": sess["data"]["active"],
                "cron_jobs": cron["data"]["jobs"],
                "cron_active": cron["data"]["active"],
            },
        )
