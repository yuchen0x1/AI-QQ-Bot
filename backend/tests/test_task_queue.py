"""Redis task queue delivery guarantees."""

from __future__ import annotations

import json
import asyncio
import os
import time
from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest

from app.services.task_queue import RedisTaskQueue


class _Pipeline:
    def __init__(self, client: "_FakeRedis") -> None:
        self.client = client
        self.commands: list[tuple[str, tuple[object, ...]]] = []

    def lrem(self, key: str, count: int, value: str):
        self.commands.append(("lrem", (key, count, value)))
        return self

    def lpush(self, key: str, value: str):
        self.commands.append(("lpush", (key, value)))
        return self

    async def execute(self):
        result = []
        for name, args in self.commands:
            result.append(await getattr(self.client, name)(*args))
        return result


class _FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.strings: dict[str, str] = {}

    async def eval(self, script: str, count: int, *arguments):
        keys, args = arguments[:count], arguments[count:]
        if "qbot:claim" in script:
            source = self.lists.setdefault(keys[0], [])
            if not source:
                return None
            raw = source.pop()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                payload.setdefault("_job_id", args[0])
                if keys[2] + payload["_job_id"] in self.strings:
                    return None
                payload.update(_claim_owner=args[1], _claim_id=args[2], _claimed_at=float(args[3]), _lease_until=float(args[4]))
                raw = json.dumps(payload)
            self.lists.setdefault(keys[1], []).insert(0, raw)
            return raw
        source = self.lists.setdefault(keys[0], [])
        if "qbot:replay" in script and keys[2] in self.strings:
            return 0
        if "qbot:renew" in script and json.loads(args[0])["_lease_until"] <= time.time():
            return 0
        if args[0] not in source:
            return 0
        source.remove(args[0])
        if "qbot:ack" in script:
            self.strings[keys[1]] = args[1]
        else:
            destination = keys[0] if "qbot:renew" in script else keys[1]
            self.lists.setdefault(destination, []).insert(0, args[1])
        return 1

    async def lpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def brpoplpush(self, source: str, destination: str, timeout: int = 0) -> str | None:
        values = self.lists.setdefault(source, [])
        if not values:
            return None
        value = values.pop()
        await self.lpush(destination, value)
        return value

    async def lrem(self, key: str, count: int, value: str) -> int:
        values = self.lists.setdefault(key, [])
        removed = 0
        for index in range(len(values) - 1, -1, -1):
            if values[index] == value and (count == 0 or removed < count):
                values.pop(index)
                removed += 1
        return removed

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.lists.setdefault(key, [])
        return values[start:] if end == -1 else values[start : end + 1]

    def pipeline(self, transaction: bool = True) -> _Pipeline:
        return _Pipeline(self)


@pytest.fixture
def queue() -> RedisTaskQueue:
    instance = RedisTaskQueue(url="redis://test", queue_name="qbot:test")
    instance._client = _FakeRedis()
    return instance


@pytest.mark.asyncio
async def test_dequeue_ack_removes_processing_lease(queue: RedisTaskQueue) -> None:
    job_id = await queue.enqueue(7, trigger="schedule")
    item = await queue.dequeue(timeout=0)

    assert item and item["task_id"] == 7 and item["_job_id"] == job_id
    assert len(queue._client.lists[queue.queue_name]) == 0
    assert len(queue._client.lists[queue.processing_queue_name]) == 1
    assert await queue.ack(item) == 1
    assert queue._client.lists[queue.processing_queue_name] == []


@pytest.mark.asyncio
async def test_nack_requeues_then_quarantines_after_max_attempts(queue: RedisTaskQueue) -> None:
    await queue.enqueue(8)
    first = await queue.dequeue(timeout=0)
    assert first is not None
    assert await queue.nack(first, reason="temporary", max_attempts=2) is True

    second = await queue.dequeue(timeout=0)
    assert second is not None and second["_queue_attempts"] == 1
    assert await queue.nack(second, reason="permanent", max_attempts=2) is False
    assert queue._client.lists[queue.queue_name] == []
    dead = json.loads(queue._client.lists[queue.dead_letter_queue_name][0])
    assert dead["_queue_attempts"] == 2
    assert dead["_dead_letter_reason"] == "permanent"


@pytest.mark.asyncio
async def test_requeue_stale_recovers_crashed_worker_job(queue: RedisTaskQueue) -> None:
    raw = json.dumps(
        {
            "task_id": 9,
            "trigger": "schedule",
            "_job_id": "crashed-job",
            "_queued_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "_queue_attempts": 0,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    queue._client.lists[queue.processing_queue_name] = [raw]

    assert await queue.requeue_stale(visibility_timeout=60) == {"requeued": 1, "dead_lettered": 0}
    recovered = json.loads(queue._client.lists[queue.queue_name][0])
    assert recovered["task_id"] == 9
    assert recovered["_queue_attempts"] == 1


async def test_two_reclaimers_do_not_duplicate_the_same_job(queue):
    await queue.enqueue(12)
    item = await queue.dequeue(timeout=0)
    expired = {key: value for key, value in item.items() if key != "_queue_raw"}
    expired["_lease_until"] = time.time() - 1
    queue._client.lists[queue.processing_queue_name] = [queue._serialize(expired)]
    outcomes = await asyncio.gather(queue.requeue_stale(), queue.requeue_stale())
    assert sum(result["requeued"] for result in outcomes) == 1
    assert len(queue._client.lists[queue.queue_name]) == 1
    assert await queue.ack(item) == 0


async def test_old_enqueued_job_gets_a_fresh_execution_lease(queue):
    raw = json.dumps({"task_id": 13, "_job_id": "old-ready", "_queued_at": "2000-01-01T00:00:00+00:00"})
    queue._client.lists[queue.queue_name] = [raw]
    item = await queue.dequeue(timeout=0)
    assert item["_claim_owner"] == queue.owner
    assert await queue.requeue_stale(visibility_timeout=1) == {"requeued": 0, "dead_lettered": 0}
    assert await queue.renew(item)
    assert await queue.ack(item) == 1


async def test_successful_job_cannot_be_manually_replayed(queue):
    await queue.enqueue(14)
    item = await queue.dequeue(timeout=0)
    assert await queue.ack(item) == 1
    raw = item["_queue_raw"]
    queue._client.lists[queue.dead_letter_queue_name] = [raw]
    assert not await queue.replay_dead(raw, actor="operator", reason="reviewed")
    assert not queue._client.lists[queue.queue_name]


async def test_real_redis_claim_recovery_and_connection_reconnect():
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL not configured")
    name = "qbot:test:" + uuid4().hex
    first, second = RedisTaskQueue(url, name), RedisTaskQueue(url, name)
    client = await first._get_client()
    try:
        await first.enqueue(21)
        claimed = await asyncio.gather(first.dequeue(timeout=0), second.dequeue(timeout=0))
        assert len([item for item in claimed if item]) == 1
        item = next(item for item in claimed if item)
        expired = {key: value for key, value in item.items() if key != "_queue_raw"}
        expired["_lease_until"] = time.time() - 1
        await client.lset(first.processing_queue_name, 0, first._serialize(expired))
        outcomes = await asyncio.gather(first.requeue_stale(), second.requeue_stale())
        assert sum(result["requeued"] for result in outcomes) == 1
        assert await client.llen(first.queue_name) == 1
        assert await first.ack(item) == 0
        recovered = await first.dequeue(timeout=0)
        assert recovered and await first.renew(recovered)
        await client.connection_pool.disconnect()
        assert await first.ack(recovered) == 1
        assert await first.ping()
    finally:
        keys = [key async for key in client.scan_iter(match=name + "*")]
        if keys:
            await client.delete(*keys)
        await first.close()
        await second.close()

