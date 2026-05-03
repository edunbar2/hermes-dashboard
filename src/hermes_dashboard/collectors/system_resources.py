"""System resources via psutil. Cheap to call ~once a second."""
from __future__ import annotations

import asyncio
import os

import psutil

from .base import envelope


# Mounts we filter out — pseudo-filesystems and snap loop mounts don't
# represent real disks the user cares about.
_FILTERED_MOUNT_PREFIXES = ("/proc", "/sys", "/dev", "/run", "/snap", "/var/lib/docker")


class SystemResourcesCollector:
    name = "system"

    def __init__(self) -> None:
        # First call to cpu_percent() always returns 0.0 — prime it once at construction.
        psutil.cpu_percent(interval=None)

    async def collect(self) -> dict:
        # psutil is sync; offload to a thread so we don't block the event loop.
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        net = psutil.net_io_counters()
        try:
            load = os.getloadavg()
        except (OSError, AttributeError):
            load = (0.0, 0.0, 0.0)

        disks = []
        for part in psutil.disk_partitions(all=False):
            if not part.mountpoint:
                continue
            if any(part.mountpoint.startswith(p) for p in _FILTERED_MOUNT_PREFIXES):
                continue
            try:
                u = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            disks.append(
                {
                    "mount": part.mountpoint,
                    "device": part.device,
                    "fstype": part.fstype,
                    "total": u.total,
                    "used": u.used,
                    "free": u.free,
                    "percent": u.percent,
                }
            )

        data = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count_logical": psutil.cpu_count(logical=True),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "memory": {
                "total": vm.total,
                "used": vm.used,
                "available": vm.available,
                "percent": vm.percent,
            },
            "swap": {
                "total": sm.total,
                "used": sm.used,
                "percent": sm.percent,
            },
            "disk": disks,
            "network": {
                "bytes_sent": net.bytes_sent,
                "bytes_recv": net.bytes_recv,
                "packets_sent": net.packets_sent,
                "packets_recv": net.packets_recv,
            },
            "load": list(load),
            "boot_time": psutil.boot_time(),
        }
        return envelope(self.name, data)
