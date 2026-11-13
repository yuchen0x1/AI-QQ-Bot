"""Defer outbound jobs during the updater's isolated health-check phase."""

import asyncio
from pathlib import Path

from app.core.config import settings
from app.services.account_manager import account_manager
from app.services.scheduler import scheduler_service

services_deferred = False


async def start_runtime() -> None:
    global services_deferred
    gate = Path(settings.update_maintenance_file) if settings.update_maintenance_file else None
    services_deferred = bool(gate and gate.exists())
    while gate and gate.exists():
        await asyncio.sleep(0.5)
    if settings.scheduler_enabled:
        await scheduler_service.start()
    await account_manager.boot_auto_start()
    services_deferred = False
