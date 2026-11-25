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
import json
import socket
import sys
import time
from pathlib import Path

from app.core.logging import setup_logging
from app.core.config import settings
from app.db.init_db import init_database
from app.db.session import SessionLocal
from app.models import ScheduledTask
from app.services.plugins import plugin_manager
from app.services.scheduler import CONNECTION_BOUND_TASKS, scheduler_service
from app.services.task_queue import redis_task_queue
from app.services import queue_execution

setup_logging()
logger = logging.getLogger("qbot.worker")
_last_broker_contact = 0.0


def _health_path() -> Path:
    return Path(settings.data_dir) / f"worker-{socket.gethostname()}.json"


def worker_healthcheck() -> bool:
    try:
        state = json.loads(_health_path().read_text(encoding="utf-8"))
        return bool(state.get("consumer_alive") and state.get("ready") and time.time() - state["time"] <= 45)
    except (OSError, ValueError, KeyError, TypeError):
        return False


async def _health_loop(consumer: asyncio.Task) -> None:
    path = _health_path()
    while not consumer.done():
        payload = {"time": time.time(), "consumer_alive": True, "ready": time.monotonic() - _last_broker_contact < 45}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(path)
        await asyncio.sleep(5)


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
    health_task = asyncio.create_task(_health_loop(worker_task)) if worker_task else None
    stop_task = asyncio.create_task(stop.wait())
    watched = [stop_task, *([worker_task] if worker_task else [])]
    done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
    if worker_task in done and not stop.is_set():
        try:
            worker_task.result()
        finally:
            stop_task.cancel()
            if health_task:
                health_task.cancel()
            await redis_task_queue.close()
        raise RuntimeError("queue consumer stopped unexpectedly")
    if worker_task:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
    if health_task:
        health_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await health_task
    _health_path().unlink(missing_ok=True)
    await redis_task_queue.close()
    logger.info("后台 Worker 正在关闭")


async def _task_type(task_id: int) -> str | None:
    async with SessionLocal() as db:
        task = await db.get(ScheduledTask, task_id)
        return task.task_type if task else None


async def _consume_queue(stop: asyncio.Event) -> None:
    global _last_broker_contact
    failures = 0
    last_recovery = 0.0
    while not stop.is_set():
        item = None
        succeeded = False
        try:
            if time.monotonic() - last_recovery >= 30:
                await redis_task_queue.requeue_stale()
                last_recovery = time.monotonic()
            item = await redis_task_queue.dequeue(timeout=5)
            _last_broker_contact = time.monotonic()
            if not item:
                failures = 0
                continue
            task_id = int(item["task_id"])
            job_id, claim_id = str(item["_job_id"]), str(item["_claim_id"])
            state = await queue_execution.begin(job_id, task_id, claim_id, seconds=redis_task_queue.lease_seconds)
            if state == "success":
                succeeded = True
                await redis_task_queue.ack(item)
                continue
            if state != "claimed":
                raise RuntimeError("job already has an active database claim")
            task_type = await _task_type(task_id)
            if task_type in CONNECTION_BOUND_TASKS:
                # 这类任务需要 bot adapter，只有 backend 进程能执行。
                logger.warning("跳过需要机器人连接的任务 task_id=%s type=%s", task_id, task_type)
                await scheduler_service.record_skipped(
                    task_id, reason="该任务依赖机器人连接，worker 进程无法执行（adapter 只在 backend 内）"
                )
                await queue_execution.finish(job_id, claim_id, success=True)
                await redis_task_queue.ack(item)
                continue
            await _execute_with_lease(item)
            succeeded = True
            await redis_task_queue.ack(item)
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failures += 1
            logger.exception("Redis 队列消费失败 job=%s", (item or {}).get("_job_id"))
            if item and not succeeded:
                with contextlib.suppress(Exception):
                    await queue_execution.finish(str(item["_job_id"]), str(item["_claim_id"]), success=False)
                with contextlib.suppress(Exception):
                    await redis_task_queue.nack(item, reason=str(exc))
            # Successful jobs remain protected by the durable DB receipt when
            # ACK fails; they are never NACKed as an execution failure.
            with contextlib.suppress(Exception):
                await redis_task_queue.close()
            try:
                await asyncio.wait_for(stop.wait(), timeout=min(10.0, 0.25 * (2 ** min(failures, 5))))
            except TimeoutError:
                pass


async def _execute_with_lease(item: dict) -> None:
    execution = asyncio.create_task(scheduler_service.execute_task(
        int(item["task_id"]), trigger=str(item.get("trigger") or "queue"),
        queue_job_id=str(item["_job_id"]), queue_claim_id=str(item["_claim_id"]),
    ))

    async def heartbeat() -> None:
        global _last_broker_contact
        while True:
            await asyncio.sleep(max(0.1, redis_task_queue.lease_seconds / 3))
            if not await redis_task_queue.renew(item) or not await queue_execution.renew(
                str(item["_job_id"]), str(item["_claim_id"]), seconds=redis_task_queue.lease_seconds,
            ):
                raise RuntimeError("worker execution lease lost")
            _last_broker_contact = time.monotonic()

    lease = asyncio.create_task(heartbeat())
    try:
        done, _ = await asyncio.wait([execution, lease], return_when=asyncio.FIRST_COMPLETED)
        if lease in done:
            await lease
        record = await execution
        success = record.status == "success"
        persisted = await queue_execution.succeeded(str(item["_job_id"])) if success else await queue_execution.finish(
            str(item["_job_id"]), str(item["_claim_id"]), success=False, record_id=record.id,
        )
        if not persisted:
            raise RuntimeError("worker result could not be committed under its claim")
        if not success:
            raise RuntimeError(record.error or "task retry attempts exhausted")
    finally:
        lease.cancel()
        execution.cancel()
        await asyncio.gather(lease, execution, return_exceptions=True)


if __name__ == "__main__":
    if "--healthcheck" in sys.argv:
        raise SystemExit(0 if worker_healthcheck() else 1)
    asyncio.run(main())
