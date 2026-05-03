"""Collector protocol — extension point for dashboard data sources.

Every collector implements:
  - ``name`` (str): stable identifier for routing/UI lookup
  - ``async collect()`` -> dict: returns ``{"name": str, "ts": float, "data": dict}``

Drop a new file in this package, register it in ``__init__.build_registry``,
expose it via a route in ``api/``, and the dashboard picks it up.
"""
from __future__ import annotations

import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Collector(Protocol):
    name: str

    async def collect(self) -> dict: ...


def envelope(name: str, data: dict) -> dict:
    """Wrap collector output with name + timestamp."""
    return {"name": name, "ts": time.time(), "data": data}
