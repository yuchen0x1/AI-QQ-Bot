"""跨实例事件广播测试：内存双实例、回环去重与可选的真实 Redis 多进程验收。"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

import pytest

from app.core.event_broker import RedisEventBroker
from app.core.events import EventHub


class LoopbackBroker:
    """模拟 Redis Pub/Sub 语义的内存 broker：广播给所有已连接实例（含发布者）。"""

    def __init__(self, bus: "SharedBus", hub: EventHub) -> None:
        self._bus = bus
        self._hub = hub

    async def start(self) -> None:
        self._bus.connect(self)

    async def stop(self) -> None:
        self._bus.disconnect(self)

    async def broadcast(self, event: dict) -> None:
        await self._bus.deliver(event, sender=self)


class SharedBus:
    """把多个 LoopbackBroker 连成一个共享频道。"""

    def __init__(self) -> None:
        self.members: list[LoopbackBroker] = []

    def connect(self, broker: LoopbackBroker) -> None:
        self.members.append(broker)

    def disconnect(self, broker: LoopbackBroker) -> None:
        if broker in self.members:
            self.members.remove(broker)

    async def deliver(self, event: dict, sender: LoopbackBroker) -> None:
        for member in list(self.members):
            member._hub.receive_remote(event)


async def _make_linked_hubs() -> tuple[EventHub, EventHub, SharedBus, LoopbackBroker, LoopbackBroker]:
    bus = SharedBus()
    hub_a = EventHub()
    hub_b = EventHub()
    broker_a = LoopbackBroker(bus, hub_a)
    broker_b = LoopbackBroker(bus, hub_b)
    hub_a.set_broker(broker_a)
    hub_b.set_broker(broker_b)
    await broker_a.start()
    await broker_b.start()
    return hub_a, hub_b, bus, broker_a, broker_b


@pytest.mark.asyncio
async def test_cross_instance_event_reaches_other_hub():
    hub_a, hub_b, _bus, broker_a, broker_b = await _make_linked_hubs()
    try:
        queue_b = await hub_b.subscribe()
        queue_a = await hub_a.subscribe()

        hub_a.publish("account.status", {"account_id": 1, "online": True})
        await asyncio.sleep(0)

        remote = queue_b.get_nowait()
        assert remote["type"] == "account.status"
        assert remote["data"]["online"] is True
        assert remote["id"]
        # 发布者自身的订阅者只收到一次，不因 Pub/Sub 回环重复。
        assert queue_a.get_nowait()["id"] == remote["id"]
        with pytest.raises(asyncio.QueueEmpty):
            queue_a.get_nowait()
        with pytest.raises(asyncio.QueueEmpty):
            queue_b.get_nowait()
        assert [item["id"] for item in hub_b.snapshot()] == [remote["id"]]
    finally:
        await broker_a.stop()
        await broker_b.stop()


@pytest.mark.asyncio
async def test_remote_replay_is_deduplicated_by_event_id():
    hub = EventHub()
    queue = await hub.subscribe()
    published = hub.publish("github.push", {"repo": "demo"})

    replayed = dict(published)
    assert hub.receive_remote(replayed) is False
    assert queue.qsize() == 1
    assert hub.snapshot() == [published]


@pytest.mark.asyncio
async def test_receive_remote_rejects_invalid_envelopes():
    hub = EventHub()
    queue = await hub.subscribe()
    now = "2026-11-14T00:00:00+00:00"

    assert hub.receive_remote({"type": "x", "time": now, "data": {}}) is False  # 缺 id
    assert hub.receive_remote({"id": "", "type": "x", "time": now, "data": {}}) is False
    assert hub.receive_remote({"id": uuid.uuid4().hex, "time": now, "data": {}}) is False  # 缺 type
    assert hub.receive_remote({"id": uuid.uuid4().hex, "type": "", "time": now, "data": {}}) is False
    assert hub.receive_remote({"id": uuid.uuid4().hex, "type": "x", "time": now, "data": "oops"}) is False

    valid_id = uuid.uuid4().hex
    assert hub.receive_remote({"id": valid_id, "type": "x", "time": now, "data": {}}) is True
    assert queue.qsize() == 1
    assert queue.get_nowait()["id"] == valid_id


def test_redis_broker_ignores_malformed_payloads():
    hub = EventHub()
    broker = RedisEventBroker("redis://localhost:6379/0", "qbot:events", hub=hub)
    now = "2026-11-14T00:00:00+00:00"

    broker._handle_raw(None)
    broker._handle_raw("not-json")
    broker._handle_raw(json.dumps(["not", "a", "dict"]))

    event_id = uuid.uuid4().hex
    broker._handle_raw(json.dumps({"id": event_id, "type": "log.entry", "time": now, "data": {"k": 1}}))
    snapshot = hub.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0]["id"] == event_id
    assert snapshot[0]["type"] == "log.entry"


@pytest.mark.asyncio
async def test_publish_without_broker_still_has_event_id():
    hub = EventHub()
    event = hub.publish("task.done", {"task_id": 7})
    assert isinstance(event["id"], str) and event["id"]


_SUBSCRIBER_SCRIPT = """
import asyncio, json, os, sys
sys.path.insert(0, os.environ["QBOT_BACKEND"])
os.environ.setdefault("SECRET_KEY", "subprocess-secret-0123456789")
from app.core.event_broker import RedisEventBroker
from app.core.events import EventHub

async def main():
    hub = EventHub()
    broker = RedisEventBroker(os.environ["REDIS_TEST_URL"], os.environ.get("QBOT_TEST_CHANNEL", "qbot:events-test"), hub=hub)
    queue = await hub.subscribe()
    await broker.start()
    await broker.wait_ready()
    print("READY", flush=True)
    try:
        expected = set(json.loads(os.environ["QBOT_EXPECTED_IDS"]))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 60
        while expected and loop.time() < deadline:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            expected.discard(event["id"])
        print("RECEIVED", json.dumps(sorted(expected)), flush=True)
    finally:
        await broker.stop()

asyncio.run(main())
"""


@pytest.mark.skipif(not os.environ.get("REDIS_TEST_URL"), reason="需要设置 REDIS_TEST_URL 指向真实 Redis")
def test_multi_instance_broadcast_over_real_redis():
    """真实 Redis 多进程验收：本进程发布，另一进程通过频道收到全部事件。"""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    channel = f"qbot:events-test-{uuid.uuid4().hex}"
    ids = [uuid.uuid4().hex for _ in range(3)]

    env = {
        **os.environ,
        "QBOT_BACKEND": backend_dir,
        "REDIS_TEST_URL": os.environ["REDIS_TEST_URL"],
        "QBOT_TEST_CHANNEL": channel,
        "QBOT_EXPECTED_IDS": json.dumps(ids),
    }
    proc = subprocess.Popen(
        [sys.executable, "-c", _SUBSCRIBER_SCRIPT],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # 订阅进程打印 READY 后才发布：Pub/Sub 不补发历史，必须先确认订阅已建立。
        lines: list[str] = []

        def _read() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.append(line)

        import threading
        reader = threading.Thread(target=_read, daemon=True)
        reader.start()
        deadline = 120.0
        waited = 0.0
        while not any(line.startswith("READY") for line in lines):
            if proc.poll() is not None:
                break
            if waited >= deadline:
                break
            time.sleep(0.5)
            waited += 0.5

        async def publish_all():
            hub = EventHub()
            broker = RedisEventBroker(os.environ["REDIS_TEST_URL"], channel, hub=hub)
            hub.set_broker(broker)
            await broker.start()
            try:
                for event_id in ids:
                    hub.publish("broadcast.probe", {"seq": ids.index(event_id)}, event_id=event_id)
                await asyncio.sleep(2)  # 等待发布动作完成
            finally:
                await broker.stop()

        assert any(line.startswith("READY") for line in lines), f"订阅进程未就绪：lines={lines!r}"
        asyncio.run(publish_all())
        reader.join(timeout=60)
        stdout = "".join(lines)
        stderr = ""
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

    assert "RECEIVED []" in stdout, f"订阅进程未收齐事件：stdout={stdout!r} stderr={stderr!r}"
