"""统一实时事件总线，供 WebSocket 与进程内业务通知使用。"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any


class EventHub:
    """进程内事件广播；事件采用稳定的 type/time/data 信封格式。"""

    def __init__(self, maxlen: int = 500) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

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

    def publish(self, event_type: str, data: dict[str, Any] | None = None, *, event_id: str | None = None) -> dict[str, Any]:
        event = {
            "type": event_type,
            "id": event_id,
            "time": datetime.now(timezone.utc).isoformat(),
            "data": data or {},
        }
        self._history.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return event

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._history)


# 事件名使用小写点分隔，方便前端按前缀订阅。
event_hub = EventHub()


def publish_event(event_type: str, data: dict[str, Any] | None = None, *, event_id: str | None = None) -> dict[str, Any]:
    return event_hub.publish(event_type, data, event_id=event_id)
