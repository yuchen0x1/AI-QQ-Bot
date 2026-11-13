"""后台 Worker 进程入口。

机器人连接由 API 主进程维护，本进程只消费不需要机器人 adapter 的队列任务
（备份、数据清理、健康检查等）。``scheduler._task_can_go_to_queue`` 已把发送类
任务挡在队列之外，这里再加一道拒绝逻辑，防止旧版本 scheduler 投递的历史消息。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from app.core.logging import setup_logging
from app.db.init_db import init_database
from app.db.session import SessionLocal
from app.models import ScheduledTask
from app.services.plugins import plugin_manager
from app.services.scheduler import CONNECTION_BOUND_TASKS, scheduler_service
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
    if redis_task_queue.enabled:
        logger.info("后台 Worker 已启动：仅执行不依赖机器人连接的任务")
    else:
        logger.warning("后台 Worker 已启动，但 REDIS_QUEUE_ENABLED 未开启，将空转等待；请确认配置")
    worker_task = asyncio.create_task(_consume_queue(stop)) if redis_task_queue.enabled else None
    await stop.wait()
    if worker_task:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
    await redis_task_queue.close()
    logger.info("后台 Worker 正在关闭")


async def _task_type(task_id: int) -> str | None:
    async with SessionLocal() as db:
        task = await db.get(ScheduledTask, task_id)
        return task.task_type if task else None


async def _consume_queue(stop: asyncio.Event) -> None:
    while not stop.is_set():
        item = await redis_task_queue.dequeue(timeout=5)
        if not item or not item.get("task_id"):
            continue
        task_id = int(item["task_id"])
        try:
            task_type = await _task_type(task_id)
            if task_type in CONNECTION_BOUND_TASKS:
                # 这类任务需要 bot adapter，只有 backend 进程能执行。
                logger.warning("跳过需要机器人连接的任务 task_id=%s type=%s", task_id, task_type)
                await scheduler_service.record_skipped(
                    task_id, reason="该任务依赖机器人连接，worker 进程无法执行（adapter 只在 backend 内）"
                )
                continue
            await scheduler_service.execute_task(task_id, trigger=str(item.get("trigger") or "queue"))
        except Exception:
            logger.exception("Redis 队列任务执行失败 task_id=%s", task_id)


if __name__ == "__main__":
    asyncio.run(main())
