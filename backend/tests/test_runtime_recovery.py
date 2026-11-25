"""Behavioral regression tests for routing, bounded work and recoverable claims."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.adapters.base import AdapterEvent
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Account, Group, GroupMember, Message, Plugin, ScheduledTask
from app.services import qq_inbox, queue_execution
from app.services.account_manager import AccountManager, RuntimeState, account_manager
from app.services.bot_engine import BotEngine, engine
from app.services.plugins import PluginManager
from app.services.scheduler import SchedulerService


def event(text="/roll 1d6", *, group=900001, user=60001):
    return AdapterEvent(post_type="message", message_type="group" if group else "private",
                        group_id=group, user_id=user, raw_message=text, self_id=100001,
                        raw={"message": [{"type": "at", "data": {"qq": "100001"}}]})


@pytest.mark.parametrize("group", [900001, None])
async def test_plugin_command_works_with_implicit_ai_enabled(client, db, mock_account, monkeypatch, group):
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    monkeypatch.setattr(engine, "schedule_ai_reply", lambda *args, **kwargs: pytest.fail("plugin was swallowed by AI"))
    before = len(adapter.outbox)
    await engine.handle_event(db, account.id, adapter, event(group=group))
    assert len(adapter.outbox) == before + 1
    assert "1d6" in adapter.outbox[-1]["message"]


async def test_admission_is_bounded_before_tasks_exist_and_reserves_other_users(monkeypatch):
    local = BotEngine()
    monkeypatch.setattr(settings, "ai_queue_per_scope", 4)
    monkeypatch.setattr(settings, "ai_queue_max_pending", 8)
    accepted = [local.schedule_ai_reply(41, None, event(user=1), "one") for _ in range(100)]
    assert sum(accepted) == 2
    assert local.schedule_ai_reply(41, None, event(user=2), "two")
    assert len(local._ai_tasks) == 1
    assert sum(len(queue) for queue in local._ai_pending[41].values()) == 3
    await local.cancel_account(41)
    assert not local._ai_pending and not local._ai_account_tasks


async def test_queue_deadline_expires_while_another_scope_is_active(monkeypatch):
    local = BotEngine()
    monkeypatch.setattr(settings, "ai_max_concurrency", 1)
    monkeypatch.setattr(settings, "ai_queue_wait_seconds", 0.05)
    entered = asyncio.Event()
    errors = []

    async def busy(*args, **kwargs):
        entered.set()
        await asyncio.sleep(10)

    async def finish(adapter, received, *, error=None):
        errors.append(error)

    monkeypatch.setattr(local, "_ai_reply_task", busy)
    monkeypatch.setattr(local, "_finish_inbox", finish)
    local.schedule_ai_reply(42, None, event(group=1), "active")
    await asyncio.wait_for(entered.wait(), timeout=1)
    local.schedule_ai_reply(42, None, event(group=2), "waiting")
    await asyncio.sleep(0.12)
    assert "AI queue deadline exceeded" in errors
    assert not local._ai_pending[42]
    await local.cancel_account(42)


async def test_renewal_exception_triggers_loss_handler_instead_of_dead_renew_task(monkeypatch):
    manager = AccountManager()
    manager._runtimes[77] = RuntimeState(77, "test", "test", lease_id="token")
    monkeypatch.setattr(settings, "account_lease_seconds", 3)
    monkeypatch.setattr(settings, "account_lease_renew_seconds", 1)
    monkeypatch.setattr(manager, "_renew_lease", AsyncMock(side_effect=OSError("database unavailable")))
    lost = AsyncMock()
    monkeypatch.setattr(manager, "_on_lease_lost", lost)
    await asyncio.wait_for(manager._renew_lease_loop(77), timeout=2)
    lost.assert_awaited_once()


async def test_account_acquisition_has_one_winner(client, db):
    account = Account(account_id="lease-test-" + uuid4().hex, name="lease test")
    db.add(account)
    await db.commit()
    manager = AccountManager()

    async def take(token):
        async with SessionLocal() as session:
            return await manager._acquire_lease(session, account.id, token)

    try:
        assert sum(await asyncio.gather(take("first"), take("second"))) == 1
    finally:
        await db.delete(account)
        await db.commit()


async def test_only_one_scheduler_owns_scheduling_and_standby_can_take_over(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.models.task import RuntimeLease

    first, second = SchedulerService(), SchedulerService()
    monkeypatch.setattr(first, "reload", AsyncMock())
    monkeypatch.setattr(second, "reload", AsyncMock())
    try:
        await first.start()
        await second.start()
        assert first.running and not second.running
        async with SessionLocal() as db:
            await db.execute(update(RuntimeLease).where(RuntimeLease.name == "scheduler").values(
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            ))
            await db.commit()
        await second._try_ownership()
        assert second.running
        assert not await first._owns_scheduling()
        assert not first.running
    finally:
        await first.shutdown()
        await second.shutdown()


async def test_known_success_and_receipt_are_committed_before_redis_ack(client, db, monkeypatch):
    from app.services.scheduler import TASK_HANDLERS

    task = ScheduledTask(name="receipt", task_type="health_check", payload={}, max_retries=0)
    db.add(task)
    await db.commit()
    handler = AsyncMock(return_value={"ok": True})
    monkeypatch.setitem(TASK_HANDLERS, "health_check", handler)
    job_id = uuid4().hex
    assert await queue_execution.begin(job_id, task.id, "claim", seconds=60) == "claimed"
    record = await SchedulerService().execute_task(task.id, trigger="queue", queue_job_id=job_id, queue_claim_id="claim")
    assert record.status == "success" and record.queue_job_id == job_id
    assert await queue_execution.begin(job_id, task.id, "after-ack-loss", seconds=60) == "success"
    assert handler.await_count == 1
    await db.delete(task)
    await db.commit()


async def test_consumer_recovers_when_dequeue_connection_fails(monkeypatch):
    from app import worker

    stop = asyncio.Event()
    calls = 0

    async def dequeue(timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("Redis connection closed")
        stop.set()
        return None

    monkeypatch.setattr(worker.redis_task_queue, "requeue_stale", AsyncMock(return_value={"requeued": 0, "dead_lettered": 0}))
    monkeypatch.setattr(worker.redis_task_queue, "dequeue", dequeue)
    monkeypatch.setattr(worker.redis_task_queue, "close", AsyncMock())
    await asyncio.wait_for(worker._consume_queue(stop), timeout=2)
    assert calls == 2


async def test_retried_inbox_does_not_duplicate_message_history_or_member_count(client, db, mock_account, monkeypatch):
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    received = event(text="ordinary", user=60002)
    inbox_id, _ = await qq_inbox.accept(account.id, {"t": "GROUP_AT_MESSAGE_CREATE", "d": {"id": uuid4().hex}})
    received.raw["_inbox_id"] = inbox_id
    monkeypatch.setattr(engine, "_should_reply_with_ai", AsyncMock(return_value=False))
    await engine.handle_event(db, account.id, adapter, received)
    await engine.handle_event(db, account.id, adapter, received)
    assert await db.scalar(select(func.count(Message.id)).where(Message.inbox_id == inbox_id)) == 1
    group = await db.scalar(select(Group).where(Group.account_id == account.id, Group.group_number == received.group_id))
    member = await db.scalar(select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == received.user_id))
    assert member.message_count == 1


def _plugin(root: Path, *, permissions=None):
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"id": "recovery-custom", "version": "1.0.0",
                                                "permissions": permissions or ["message:reply"]}), encoding="utf-8")
    (root / "main.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")
    return Plugin(plugin_id="recovery-custom", name="custom", version="1.0.0", permissions=permissions or ["message:reply"],
                  builtin=False, enabled=True, path=str(root), config={})


def test_invalid_manifest_cannot_execute_module_top_level(tmp_path, monkeypatch):
    marker = tmp_path / "executed"
    plugin = _plugin(tmp_path / "invalid", permissions=["unsupported:permission"])
    (Path(plugin.path) / "main.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
    monkeypatch.setattr(settings, "plugin_extensions_dir", str(tmp_path / "persistent"))
    assert PluginManager().load_one(plugin) is None
    assert not marker.exists()


def test_custom_code_survives_release_switch(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path / "releases" / "old" / "backend" / "plugins" / "recovery-custom")
    persistent = tmp_path / "persistent"
    monkeypatch.setattr(settings, "plugin_extensions_dir", str(persistent))
    manager = PluginManager()
    assert manager.load_one(plugin)
    assert Path(plugin.path).is_relative_to(persistent)
    monkeypatch.setattr(settings, "plugin_dir", str(tmp_path / "releases" / "new" / "backend" / "plugins"))
    assert PluginManager().load_one(plugin)


def test_literal_current_path_recovers_registered_previous_release(tmp_path, monkeypatch):
    old = tmp_path / "releases" / "old"
    plugin = _plugin(old / "backend" / "plugins" / "recovery-custom")
    new = tmp_path / "releases" / "new"
    new.mkdir()
    current = tmp_path / "current"
    try:
        current.symlink_to(new, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    if os.name != "nt" and old.stat().st_uid != 0:
        pytest.skip("native legacy recovery requires root-owned releases")
    plugin.path = str(current / "backend" / "plugins" / "recovery-custom")
    monkeypatch.setattr(settings, "plugin_extensions_dir", str(tmp_path / "persistent"))
    assert PluginManager().load_one(plugin)
    assert Path(plugin.path).is_relative_to(tmp_path / "persistent")
