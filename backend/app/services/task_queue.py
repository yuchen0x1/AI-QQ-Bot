"""Optional Redis queue with owner-bound execution leases and conditional moves."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config import settings


# LREM and its dependent push must run in one script: a transaction alone
# cannot prevent a second reclaimer from pushing an already-removed job.
_CLAIM = """-- qbot:claim
local raw = redis.call('RPOP', KEYS[1])
if not raw then return nil end
local ok, p = pcall(cjson.decode, raw)
if not ok or type(p) ~= 'table' or not string.match(raw, '^%s*{') then
  redis.call('LPUSH', KEYS[2], raw)
  return raw
end
if type(p['_job_id']) ~= 'string' or #p['_job_id'] == 0 or #p['_job_id'] > 64 then p['_job_id'] = ARGV[1] end
if redis.call('EXISTS', KEYS[3] .. p['_job_id']) == 1 then return nil end
p['_claim_owner'] = ARGV[2]
p['_claim_id'] = ARGV[3]
p['_claimed_at'] = tonumber(ARGV[4])
p['_lease_until'] = tonumber(ARGV[5])
local claimed = cjson.encode(p)
redis.call('LPUSH', KEYS[2], claimed)
return claimed
"""

_MOVE = """-- qbot:move
if redis.call('LREM', KEYS[1], 1, ARGV[1]) ~= 1 then return 0 end
redis.call('LPUSH', KEYS[2], ARGV[2])
return 1
"""

_RENEW = """-- qbot:renew
local p = cjson.decode(ARGV[1])
local now = redis.call('TIME')
if tonumber(p['_lease_until'] or 0) <= tonumber(now[1]) + tonumber(now[2]) / 1000000 then return 0 end
if redis.call('LREM', KEYS[1], 1, ARGV[1]) ~= 1 then return 0 end
redis.call('LPUSH', KEYS[1], ARGV[2])
return 1
"""

_ACK = """-- qbot:ack
if redis.call('LREM', KEYS[1], 1, ARGV[1]) ~= 1 then return 0 end
redis.call('SET', KEYS[2], ARGV[2], 'EX', 2592000)
return 1
"""

_REPLAY = """-- qbot:replay
if redis.call('EXISTS', KEYS[3]) == 1 then return 0 end
if redis.call('LREM', KEYS[1], 1, ARGV[1]) ~= 1 then return 0 end
redis.call('LPUSH', KEYS[2], ARGV[2])
return 1
"""


class RedisTaskQueue:
    def __init__(self, url: str | None = None, queue_name: str | None = None) -> None:
        self.url = url or settings.redis_url
        self.queue_name = queue_name or settings.redis_queue_name
        self.processing_queue_name = f"{self.queue_name}:processing"
        self.dead_letter_queue_name = f"{self.queue_name}:dead"
        self.completed_key_prefix = f"{self.queue_name}:completed:"
        self.owner = f"{settings.runtime_instance_id}:{uuid4().hex}"
        self.lease_seconds = 90
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
            if isinstance(raw, (bytes, str)):
                return cls._raw_for(raw)
            return cls._serialize({key: value for key, value in item.items() if key != "_queue_raw"})
        return str(item)

    async def enqueue(self, task_id: int, *, trigger: str = "schedule") -> str:
        payload = {
            "task_id": int(task_id), "trigger": str(trigger), "_job_id": uuid4().hex,
            "_queued_at": datetime.now(timezone.utc).isoformat(), "_queue_attempts": 0,
        }
        client = await self._get_client()
        await client.lpush(self.queue_name, self._serialize(payload))
        return payload["_job_id"]

    async def ping(self) -> bool:
        try:
            client = await self._get_client()
            return bool(await client.ping())
        except Exception:  # noqa: BLE001
            return False

    async def dequeue(self, timeout: int = 5) -> dict[str, Any] | None:
        client = await self._get_client()
        deadline = time.monotonic() + max(0, timeout)
        while True:
            now = time.time()
            raw = await client.eval(
                _CLAIM, 3, self.queue_name, self.processing_queue_name, self.completed_key_prefix,
                uuid4().hex, self.owner, uuid4().hex, now, now + self.lease_seconds,
            )
            if raw:
                payload = self._decode(raw)
                if not payload or not isinstance(payload.get("task_id"), int) or payload["task_id"] <= 0:
                    await self._quarantine(raw, "invalid queue payload")
                else:
                    payload["_queue_raw"] = self._raw_for(raw)
                    return payload
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(0.2, remaining))

    async def renew(self, item: dict[str, Any]) -> bool:
        if item.get("_claim_owner") != self.owner or float(item.get("_lease_until") or 0) <= time.time():
            return False
        payload = {key: value for key, value in item.items() if key != "_queue_raw"}
        payload["_lease_until"] = time.time() + self.lease_seconds
        replacement = self._serialize(payload)
        client = await self._get_client()
        if not await client.eval(_RENEW, 1, self.processing_queue_name, self._raw_for(item), replacement):
            return False
        item.update(payload)
        item["_queue_raw"] = replacement
        return True

    async def ack(self, item: Any) -> int:
        payload = self._decode(self._raw_for(item)) or {}
        if payload.get("_claim_owner") != self.owner or not payload.get("_job_id"):
            return 0
        client = await self._get_client()
        return int(await client.eval(
            _ACK, 2, self.processing_queue_name, self.completed_key_prefix + payload["_job_id"],
            self._raw_for(item), datetime.now(timezone.utc).isoformat(),
        ) or 0)

    async def nack(self, item: Any, *, reason: str = "", max_attempts: int = 3, _recover: bool = False) -> bool | None:
        raw = self._raw_for(item)
        payload = self._decode(raw) or {"raw": raw}
        if not _recover and payload.get("_claim_owner") != self.owner:
            return None
        try:
            attempts = max(0, int(payload.get("_queue_attempts") or 0)) + 1
        except (TypeError, ValueError):
            attempts = 1
        for key in ("_queue_raw", "_claim_owner", "_claim_id", "_claimed_at", "_lease_until"):
            payload.pop(key, None)
        payload["_queue_attempts"] = attempts
        payload["_queued_at"] = datetime.now(timezone.utc).isoformat()
        requeued = attempts < max(1, int(max_attempts))
        if requeued:
            destination = self.queue_name
        else:
            payload["_dead_letter_reason"] = str(reason or "worker execution failed")[:500]
            payload["_dead_letter_at"] = datetime.now(timezone.utc).isoformat()
            destination = self.dead_letter_queue_name
        if not await self._move_processing(raw, destination, self._serialize(payload)):
            return None
        return requeued

    async def requeue_stale(self, *, visibility_timeout: int = 3600, max_attempts: int = 3) -> dict[str, int]:
        client = await self._get_client()
        rows = await client.lrange(self.processing_queue_name, 0, -1)
        now = time.time()
        stats = {"requeued": 0, "dead_lettered": 0}
        for raw in rows or []:
            payload = self._decode(raw) or {}
            expires = payload.get("_lease_until")
            if not isinstance(expires, (int, float)):
                # Compatibility for processing entries left by pre-lease workers.
                try:
                    expires = datetime.fromisoformat(str(payload.get("_queued_at") or "")).timestamp() + visibility_timeout
                except (TypeError, ValueError, OverflowError):
                    expires = 0
            if expires > now:
                continue
            outcome = await self.nack(raw, reason="processing lease expired", max_attempts=max_attempts, _recover=True)
            if outcome is not None:
                stats["requeued" if outcome else "dead_lettered"] += 1
        return stats

    async def replay_dead(self, raw: str, *, actor: str, reason: str) -> bool:
        if not actor.strip() or not reason.strip():
            raise ValueError("manual replay requires an actor and reason")
        payload = self._decode(raw)
        if not payload or not payload.get("_job_id"):
            raise ValueError("invalid dead-letter payload")
        payload.update(_queue_attempts=0, _replayed_by=actor[:96], _replay_reason=reason[:500],
                       _replayed_at=datetime.now(timezone.utc).isoformat())
        client = await self._get_client()
        return bool(await client.eval(
            _REPLAY, 3, self.dead_letter_queue_name, self.queue_name,
            self.completed_key_prefix + payload["_job_id"], raw, self._serialize(payload),
        ))

    async def _move_processing(self, raw: Any, destination: str, replacement: str) -> bool:
        client = await self._get_client()
        return bool(await client.eval(_MOVE, 2, self.processing_queue_name, destination, self._raw_for(raw), replacement))

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
