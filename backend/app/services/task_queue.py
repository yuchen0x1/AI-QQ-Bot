"""可选 Redis 任务队列；未启用时不建立连接，不影响本地 APScheduler。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config import settings


class RedisTaskQueue:
    def __init__(self, url: str | None = None, queue_name: str | None = None) -> None:
        self.url = url or settings.redis_url
        self.queue_name = queue_name or settings.redis_queue_name
        self.processing_queue_name = f"{self.queue_name}:processing"
        self.dead_letter_queue_name = f"{self.queue_name}:dead"
        self._client: Any = None

    @property
    def enabled(self) -> bool:
        return bool(settings.redis_enabled and settings.redis_queue_enabled)

    async def _get_client(self):
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(self.url, decode_responses=True)
        return self._client

    @staticmethod
    def _serialize(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode(raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @classmethod
    def _raw_for(cls, item: Any) -> str:
        if isinstance(item, bytes):
            return item.decode("utf-8", errors="replace")
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            raw = item.get("_queue_raw")
            if isinstance(raw, bytes):
                return raw.decode("utf-8", errors="replace")
            if isinstance(raw, str):
                return raw
            return cls._serialize({key: value for key, value in item.items() if key != "_queue_raw"})
        return str(item)

    async def enqueue(self, task_id: int, *, trigger: str = "schedule") -> str:
        """Queue a durable job and return its unique id.

        Jobs are moved to a processing list by :meth:`dequeue` instead of being
        removed outright.  This keeps a worker crash from losing scheduled work.
        """
        payload = {
            "task_id": int(task_id),
            "trigger": str(trigger),
            "_job_id": uuid4().hex,
            "_queued_at": datetime.now(timezone.utc).isoformat(),
            "_queue_attempts": 0,
        }
        client = await self._get_client()
        await client.lpush(self.queue_name, self._serialize(payload))
        return payload["_job_id"]

    async def ping(self) -> bool:
        """用于启动检查与测试，不抛出 Redis 网络异常。"""
        try:
            client = await self._get_client()
            return bool(await client.ping())
        except Exception:  # noqa: BLE001
            return False

    async def dequeue(self, timeout: int = 5) -> dict[str, Any] | None:
        client = await self._get_client()
        raw = await client.brpoplpush(self.queue_name, self.processing_queue_name, timeout=timeout)
        if not raw:
            return None
        payload = self._decode(raw)
        if not payload or not payload.get("task_id"):
            await self._quarantine(raw, "invalid queue payload")
            return None
        # Private metadata is kept in-memory only; it is never passed to task
        # handlers and lets ACK/NACK remove the exact Redis list entry.
        payload["_queue_raw"] = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        return payload

    async def ack(self, item: Any) -> int:
        """Acknowledge a successfully handled job from the processing list."""
        client = await self._get_client()
        return int(await client.lrem(self.processing_queue_name, 1, self._raw_for(item)) or 0)

    async def nack(self, item: Any, *, reason: str = "", max_attempts: int = 3) -> bool:
        """Requeue a failed worker job or move it to the dead-letter list.

        The remove-and-push pair is executed in one Redis transaction so a
        process interruption cannot lose a job between the two operations.
        Returns ``True`` when the job was requeued and ``False`` when it was
        quarantined in the dead-letter list.
        """
        raw = self._raw_for(item)
        payload = self._decode(raw) or {"raw": raw}
        attempts = int(payload.get("_queue_attempts") or 0) + 1
        payload.pop("_queue_raw", None)
        payload["_queue_attempts"] = attempts
        payload["_queued_at"] = datetime.now(timezone.utc).isoformat()
        if attempts >= max(1, int(max_attempts)):
            payload["_dead_letter_reason"] = str(reason or "worker execution failed")[:500]
            payload["_dead_letter_at"] = datetime.now(timezone.utc).isoformat()
            destination = self.dead_letter_queue_name
            requeued = False
        else:
            destination = self.queue_name
            requeued = True
        await self._move_processing(raw, destination, self._serialize(payload))
        return requeued

    async def requeue_stale(self, *, visibility_timeout: int = 3600, max_attempts: int = 3) -> dict[str, int]:
        """Recover jobs left in processing after a worker crash.

        This is intended to run during worker startup.  A one-hour default is
        deliberately longer than the normal task timeout to avoid duplicating a
        long-running job in a second worker.
        """
        client = await self._get_client()
        rows = await client.lrange(self.processing_queue_name, 0, -1)
        cutoff = datetime.now(timezone.utc).timestamp() - max(1, int(visibility_timeout))
        stats = {"requeued": 0, "dead_lettered": 0}
        for raw in rows or []:
            payload = self._decode(raw)
            queued_at = None
            if payload:
                try:
                    queued_at = datetime.fromisoformat(str(payload.get("_queued_at") or "")).timestamp()
                except (TypeError, ValueError, OverflowError):
                    queued_at = None
            if queued_at is not None and queued_at > cutoff:
                continue
            item = payload or {"_queue_raw": raw}
            if payload:
                item["_queue_raw"] = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            if await self.nack(item, reason="processing lease expired", max_attempts=max_attempts):
                stats["requeued"] += 1
            else:
                stats["dead_lettered"] += 1
        return stats

    async def _move_processing(self, raw: Any, destination: str, replacement: str) -> None:
        client = await self._get_client()
        pipe = client.pipeline(transaction=True)
        pipe.lrem(self.processing_queue_name, 1, self._raw_for(raw))
        pipe.lpush(destination, replacement)
        await pipe.execute()

    async def _quarantine(self, raw: Any, reason: str) -> None:
        payload = self._decode(raw) or {"raw": self._raw_for(raw)}
        payload["_dead_letter_reason"] = reason
        payload["_dead_letter_at"] = datetime.now(timezone.utc).isoformat()
        await self._move_processing(raw, self.dead_letter_queue_name, self._serialize(payload))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


redis_task_queue = RedisTaskQueue()
