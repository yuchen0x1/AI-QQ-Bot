"""日志：控制台 + 滚动文件 + 内存实时广播（供 WebSocket 日志流使用）。"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.core.config import settings

SENSITIVE_PATTERNS = [
    (re.compile(r"(api[_-]?key|token|secret|password|authorization)\s*[=:]\s*[\"']?([^\s\"',}]{4,})", re.I), r"\1=***"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer ***"),
    (re.compile(r"sk-[A-Za-z0-9]{10,}"), "sk-***"),
]


def mask_text(text: str) -> str:
    result = text
    for pattern, repl in SENSITIVE_PATTERNS:
        result = pattern.sub(repl, result)
    return result


class RealtimeLogHub:
    """进程内日志广播：给 /ws/logs 的每个订阅者一个队列。"""

    def __init__(self, maxlen: int = 300) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._subscribers.add(queue)
        for item in list(self._history)[-50:]:
            queue.put_nowait(item)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    def publish(self, record: dict[str, Any]) -> None:
        self._history.append(record)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:
                pass

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._history)


hub = RealtimeLogHub()


class HubHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            hub.publish(
                {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "level": record.levelname,
                    "category": getattr(record, "category", "system"),
                    "message": mask_text(record.getMessage()),
                    "account_id": getattr(record, "account_id", None),
                    "logger": record.name,
                }
            )
        except Exception:  # pragma: no cover - 日志永远不能拖垮业务
            pass


def setup_logging() -> None:
    log_dir = Path(settings.data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_qbot_configured", False):
        return
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(log_dir / "qbot.log", maxBytes=20 * 1024 * 1024, backupCount=10, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    hub_handler = HubHandler()
    hub_handler.setLevel(logging.INFO)
    root.addHandler(hub_handler)

    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    root._qbot_configured = True  # type: ignore[attr-defined]
