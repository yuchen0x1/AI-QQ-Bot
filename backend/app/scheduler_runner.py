"""独立 APScheduler 进程入口（实验性，默认部署不使用）。

⚠️ 重要限制：`account_manager` 的 adapter 只存在于持有机器人连接的 backend 进程内。
本进程没有机器人连接，所有 `send_group_message` / `invoke` 调用都会抛
"账号不在线"，因此 GitHub 推送、定时群消息、群聊 AI 总结在本进程里无法完成。

只有把机器人连接迁到独立的连接服务、并经 Redis 命令通道回投之后，本入口才具备
完整能力。当前默认 Compose 拓扑把调度放在 backend 内（SCHEDULER_ENABLED=true）。
"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.init_db import init_database
from app.db.session import SessionLocal
from app.services.plugins import plugin_manager
from app.services.scheduler import scheduler_service

setup_logging()
logger = logging.getLogger("qbot.scheduler_runner")


async def main() -> None:
    if settings.redis_queue_enabled:
        # 队列模式下 worker 负责实际执行，但 worker 同样没有 adapter。
        logger.warning(
            "REDIS_QUEUE_ENABLED=true：调度任务会入队给 worker 执行，"
            "而 worker 进程没有机器人连接，消息类任务仍会失败。"
        )
    logger.warning(
        "独立调度器已启动：本进程无机器人连接，发送类任务（群消息/推送/AI 总结）会失败。"
        "生产部署请使用 backend 内置调度（SCHEDULER_ENABLED=true）。"
    )
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
    await stop.wait()
    await scheduler_service.shutdown()
    logger.info("独立调度器已停止")


if __name__ == "__main__":
    asyncio.run(main())
