"""Redis Pub/Sub 跨实例事件转发。

多实例水平扩展时，各实例通过 Redis 频道广播实时事件，
使任意实例上的 WebSocket 订阅者看到一致的状态与日志流。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.events import EventBroker, EventHub, event_hub

logger = logging.getLogger("qbot.events")

# 断线重连间隔（秒）；Pub/Sub 短暂不可用不应导致事件转发退出。
_RECONNECT_DELAY = 5.0


class RedisEventBroker(EventBroker):
    """把本地事件发布到 Redis 频道，并把远端事件交给本地 EventHub。"""

    def __init__(self, redis_url: str, channel: str, hub: EventHub = event_hub) -> None:
        self._redis_url = redis_url
        self._channel = channel
        self._hub = hub
        self._client: aioredis.Redis | None = None
        self._listener: asyncio.Task[None] | None = None
        self._stopping = False
        # 收到 Redis 的 subscribe 确认后置位；此后发布的消息才保证能送达本实例。
        self._ready = asyncio.Event()

    async def start(self) -> None:
        self._stopping = False
        self._ready = asyncio.Event()
        self._client = aioredis.from_url(self._redis_url, decode_responses=True)
        self._listener = asyncio.create_task(self._listen(), name="redis-event-listener")
        logger.info("Redis 事件转发已启动：channel=%s", self._channel)

    async def wait_ready(self, timeout: float = 10.0) -> None:
        """等待 Redis 订阅确认；超时抛 TimeoutError，由调用方决定如何处理。"""
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    async def stop(self) -> None:
        self._stopping = True
        self._ready.clear()
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
            self._client = None

    async def broadcast(self, event: dict[str, Any]) -> None:
        if self._client is None:
            return
        await self._client.publish(self._channel, json.dumps(event, ensure_ascii=False, default=str))

    async def _listen(self) -> None:
        while not self._stopping:
            pubsub = None
            try:
                assert self._client is not None
                pubsub = self._client.pubsub()
                await pubsub.subscribe(self._channel)
                logger.info("已订阅 Redis 事件频道：%s", self._channel)
                async for message in pubsub.listen():
                    message_type = message.get("type")
                    if message_type == "subscribe":
                        self._ready.set()
                        continue
                    if message_type != "message":
                        continue
                    self._handle_raw(message.get("data"))
            except asyncio.CancelledError:
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.aclose()
                raise
            except Exception:
                self._ready.clear()
                if self._stopping:
                    break
                logger.exception("Redis 事件订阅中断，%s 秒后重试", _RECONNECT_DELAY)
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.aclose()
                await asyncio.sleep(_RECONNECT_DELAY)

    def _handle_raw(self, raw: Any) -> None:
        try:
            event = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("忽略无法解析的远端事件载荷")
            return
        if not isinstance(event, dict):
            logger.warning("忽略格式不正确的远端事件载荷")
            return
        self._hub.receive_remote(event)
