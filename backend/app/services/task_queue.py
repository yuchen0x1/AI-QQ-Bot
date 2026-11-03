"""可选 Redis 任务队列；未启用时不建立连接，不影响本地 APScheduler。"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import settings


class RedisTaskQueue:
    def __init__(self, url: str | None = None, queue_name: str | None = None) -> None:
        self.url = url or settings.redis_url
        self.queue_name = queue_name or settings.redis_queue_name
        self._client: Any = None

    @property
    def enabled(self) -> bool:
        return bool(settings.redis_enabled and settings.redis_queue_enabled)

    async def _get_client(self):
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(self.url, decode_responses=True)
        return self._client

    async def enqueue(self, task_id: int, *, trigger: str = "schedule") -> None:
        client = await self._get_client()
        await client.lpush(self.queue_name, json.dumps({"task_id": task_id, "trigger": trigger}))

    async def ping(self) -> bool:
        """用于启动检查与测试，不抛出 Redis 网络异常。"""
        try:
            client = await self._get_client()
            return bool(await client.ping())
        except Exception:  # noqa: BLE001
            return False

    async def dequeue(self, timeout: int = 5) -> dict[str, Any] | None:
        client = await self._get_client()
        item = await client.brpop(self.queue_name, timeout=timeout)
        if not item:
            return None
        try:
            payload = json.loads(item[1])
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


redis_task_queue = RedisTaskQueue()
