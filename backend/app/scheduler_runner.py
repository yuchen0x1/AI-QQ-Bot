"""独立 APScheduler 进程入口。"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.core.logging import setup_logging
from app.db.init_db import init_database
from app.db.session import SessionLocal
from app.services.plugins import plugin_manager
from app.services.scheduler import scheduler_service

setup_logging()
logger = logging.getLogger("qbot.scheduler_runner")

async def main() -> None:
    await init_database()
    async with SessionLocal() as db:
        await plugin_manager.load_all(db)
    await scheduler_service.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    logger.info("独立调度器已启动")
    await stop.wait()
    await scheduler_service.shutdown()
    logger.info("独立调度器已停止")

if __name__ == "__main__":
    asyncio.run(main())
