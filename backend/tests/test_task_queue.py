"""Redis task queue delivery guarantees."""

from __future__ import annotations

import json
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

