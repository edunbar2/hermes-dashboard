import pytest

from hermes_dashboard.collectors.system_resources import SystemResourcesCollector


@pytest.mark.asyncio
async def test_system_collector_returns_envelope():
    c = SystemResourcesCollector()
    snapshot = await c.collect()
    assert snapshot["name"] == "system"
    assert "ts" in snapshot
    assert "data" in snapshot


@pytest.mark.asyncio
async def test_system_collector_required_keys():
    c = SystemResourcesCollector()
    snap = await c.collect()
    d = snap["data"]
    assert "cpu_percent" in d
    assert "memory" in d and "percent" in d["memory"]
    assert "disk" in d and isinstance(d["disk"], list) and len(d["disk"]) >= 1
    assert "network" in d and "bytes_sent" in d["network"]
    assert "load" in d and len(d["load"]) == 3
    assert isinstance(d["cpu_percent"], (int, float))


@pytest.mark.asyncio
async def test_system_collector_name():
    c = SystemResourcesCollector()
    assert c.name == "system"
