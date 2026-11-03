"""后台 Worker 进程入口。机器人连接管理由 API 主进程维护；任务执行在此预留独立 worker。"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from app.core.logging import setup_logging
from app.db.init_db import init_database
from app.services.plugins import plugin_manager
from app.db.session import SessionLocal
from app.services.scheduler import scheduler_service
from app.services.task_queue import redis_task_queue

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
    worker_task = asyncio.create_task(_consume_queue(stop)) if redis_task_queue.enabled else None
    await stop.wait()
    if worker_task:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
    await redis_task_queue.close()
    logger.info("后台 Worker 正在关闭")


async def _consume_queue(stop: asyncio.Event) -> None:
    while not stop.is_set():
        item = await redis_task_queue.dequeue(timeout=5)
        if item and item.get("task_id"):
            try:
                await scheduler_service.execute_task(int(item["task_id"]), trigger=str(item.get("trigger") or "queue"))
            except Exception:
                logger.exception("Redis 队列任务执行失败 task_id=%s", item.get("task_id"))

if __name__ == "__main__":
    asyncio.run(main())
