"""Collector registry — extension point.

To add a new metric source:
  1. Create ``my_collector.py`` exposing a class with ``name`` + ``async collect()``
  2. Import it here and add to the dict returned by ``build_registry``
  3. Wire it into a route under ``api/``

The registry is constructed per-app (in ``app.create_app``) with the dashboard
config so that tests can inject a fresh ``hermes_home`` without touching real state.
"""
from __future__ import annotations

from pathlib import Path

from .base import Collector, envelope
from .hermes_cron import HermesCronCollector
from .hermes_gateway import HermesGatewayCollector
from .hermes_sessions import HermesSessionsCollector
from .hermes_status import HermesStatusCollector
from .system_resources import SystemResourcesCollector


def build_registry(hermes_home: Path) -> dict[str, Collector]:
    return {
        SystemResourcesCollector.name: SystemResourcesCollector(),
        HermesGatewayCollector.name: HermesGatewayCollector(hermes_home),
        HermesSessionsCollector.name: HermesSessionsCollector(hermes_home),
        HermesCronCollector.name: HermesCronCollector(hermes_home),
        HermesStatusCollector.name: HermesStatusCollector(hermes_home),
    }


__all__ = ["Collector", "build_registry", "envelope"]
