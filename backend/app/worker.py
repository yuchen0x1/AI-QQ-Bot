"""后台 Worker 进程入口。机器人连接管理由 API 主进程维护；任务执行在此预留独立 worker。"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.core.logging import setup_logging
from app.db.init_db import init_database
from app.services.plugins import plugin_manager
from app.db.session import SessionLocal

setup_logging()
logger = logging.getLogger("qbot.worker")

async def main() -> None:
    await init_database()
    async with SessionLocal() as db:
        await plugin_manager.load_all(db)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    logger.info("后台 Worker 已启动；队列型任务启用后将在此进程执行")
    await stop.wait()
    logger.info("后台 Worker 正在关闭")

if __name__ == "__main__":
    asyncio.run(main())
