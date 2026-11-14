"""统一实时事件总线，供 WebSocket 与进程内业务通知使用。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger("qbot.events")

# 远端事件去重窗口：防止 Pub/Sub 回环或重连重放导致同一事件重复投递。
_REMOTE_DEDUPE_SIZE = 2000


class EventBroker(Protocol):
    """跨实例事件转发接口；实现方负责把事件送达其他实例。"""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def broadcast(self, event: dict[str, Any]) -> None: ...


class EventHub:
    """进程内事件广播；事件采用稳定的 type/time/data 信封格式。

    挂载 EventBroker 后，publish 的事件会转发给其他实例，
    其他实例的事件经 receive_remote 进入本地订阅队列与历史。
    """

    def __init__(self, maxlen: int = 500) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()
        self._broker: EventBroker | None = None
        self._remote_ids: deque[str] = deque(maxlen=_REMOTE_DEDUPE_SIZE)
        # create_task 只被事件循环弱引用；挂起中的转发任务必须强持有，否则会被 GC 静默丢弃。
        self._pending_tasks: set[asyncio.Task[None]] = set()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=300)
        async with self._lock:
            self._subscribers.add(queue)
        for item in list(self._history)[-50:]:
            queue.put_nowait(item)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    def set_broker(self, broker: EventBroker | None) -> None:
        self._broker = broker

    def publish(self, event_type: str, data: dict[str, Any] | None = None, *, event_id: str | None = None) -> dict[str, Any]:
        event = {
            "type": event_type,
            "id": event_id or uuid.uuid4().hex,
            "time": datetime.now(timezone.utc).isoformat(),
            "data": data or {},
        }
        # 记入去重窗口：Redis Pub/Sub 会把消息回传给发布者自身，避免重复投递。
        self._remote_ids.append(event["id"])
        self._history.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        broker = self._broker
        if broker is not None:
            self._dispatch_to_broker(broker, event)
        return event

    # Pub/Sub 转发失败只影响其他实例的实时展示，不应打断业务调用方。
    def _dispatch_to_broker(self, broker: EventBroker, event: dict[str, Any]) -> None:
        task = asyncio.get_running_loop().create_task(self._broadcast_safely(broker, event))
        self._pending_tasks.add(task)
        task.add_done_callback(self._on_broadcast_done)

    def _on_broadcast_done(self, task: asyncio.Task[None]) -> None:
        self._pending_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("跨实例事件广播任务异常：%s", task.exception())

    @staticmethod
    async def _broadcast_safely(broker: EventBroker, event: dict[str, Any]) -> None:
        try:
            await broker.broadcast(event)
        except Exception:
            logger.exception("跨实例事件广播失败：type=%s", event.get("type"))

    def receive_remote(self, event: dict[str, Any]) -> bool:
        """接收来自其他实例的事件；返回是否被本地接受。"""
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id:
            return False
        if event_id in self._remote_ids:
            return False
        self._remote_ids.append(event_id)
        if not self._is_valid_envelope(event):
            return False
        self._history.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return True

    @staticmethod
    def _is_valid_envelope(event: dict[str, Any]) -> bool:
        return (
            isinstance(event.get("type"), str)
            and bool(event.get("type"))
            and isinstance(event.get("time"), str)
            and isinstance(event.get("data"), dict)
        )

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._history)


# 事件名使用小写点分隔，方便前端按前缀订阅。
event_hub = EventHub()


def publish_event(event_type: str, data: dict[str, Any] | None = None, *, event_id: str | None = None) -> dict[str, Any]:
    return event_hub.publish(event_type, data, event_id=event_id)
