"""系统状态采集：CPU/内存/磁盘、数据库、Redis、调度器。"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

_PROCESS_START = time.time()

try:  # psutil 为可选依赖，缺失时退化为标准库采集
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


def process_uptime() -> int:
    return int(time.time() - _PROCESS_START)


def _memory() -> tuple[float, float, float]:
    if psutil:
        vm = psutil.virtual_memory()
        return vm.percent, vm.used / 1024 / 1024, vm.total / 1024 / 1024
    if sys.platform == "win32":  # pragma: no cover
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total = stat.ullTotalPhys / 1024 / 1024
        used = (stat.ullTotalPhys - stat.ullAvailPhys) / 1024 / 1024
        return float(stat.dwMemoryLoad), used, total
    try:  # pragma: no cover - Linux 兜底
        with open("/proc/meminfo", encoding="utf-8") as fh:
            info = {line.split(":")[0]: line.split()[1] for line in fh if ":" in line}
        total = int(info["MemTotal"]) / 1024
        available = int(info["MemAvailable"]) / 1024
        used = total - available
        return round(used / total * 100, 1), used, total
    except Exception:
        return 0.0, 0.0, 0.0


def _cpu_percent() -> float:
    if psutil:
        return float(psutil.cpu_percent(interval=None))
    try:  # pragma: no cover
        load = os.getloadavg()[0]
        return round(min(100.0, load / (os.cpu_count() or 1) * 100), 1)
    except (AttributeError, OSError):
        return 0.0


def _load_average() -> list[float]:
    try:  # pragma: no cover
        return list(os.getloadavg())
    except (AttributeError, OSError):
        return [0.0, 0.0, 0.0]


async def redis_status() -> bool:
    if not settings.redis_enabled:
        return False
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        try:
            return bool(await client.ping())
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001
        return False


async def collect_system_stats() -> dict[str, Any]:
    from app.services.scheduler import scheduler_service

    memory_percent, memory_used, memory_total = _memory()
    usage = shutil.disk_usage("/")
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "cpu_percent": _cpu_percent(),
        "memory_percent": round(memory_percent, 1),
        "memory_used_mb": round(memory_used, 1),
        "memory_total_mb": round(memory_total, 1),
        "disk_percent": round(usage.used / usage.total * 100, 1),
        "disk_used_gb": round(usage.used / 1024**3, 1),
        "disk_total_gb": round(usage.total / 1024**3, 1),
        "load_average": [round(x, 2) for x in _load_average()],
        "python_version": platform.python_version(),
        "uptime_seconds": process_uptime(),
        "db_ok": db_ok,
        "redis_ok": await redis_status(),
        "redis_enabled": settings.redis_enabled,
        "scheduler_running": scheduler_service.running,
        "scheduler_jobs": scheduler_service.job_count(),
        "process_uptime_seconds": process_uptime(),
        "platform": f"{platform.system()} {platform.release()}",
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
