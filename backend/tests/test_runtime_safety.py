"""P0 稳定性回归：AI 异步化、会话串行、限流器回收、旧版回调限流。"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import replace

import httpx

from app.adapters.base import AdapterEvent
from app.core.ratelimit import SlidingWindowLimiter, legacy_webhook_limiter
from app.main import _path_matches
from app.models import Account
from app.services.account_manager import account_manager
from app.services.bot_engine import engine

GROUP_A = 910001
GROUP_B = 910002


def _group_event(user_id: int, text: str, group_id: int = GROUP_A) -> AdapterEvent:
    return AdapterEvent(
        post_type="message",
        message_type="group",
        group_id=group_id,
        user_id=user_id,
        message_id=991001,
        raw_message=text,
        sender={"nickname": f"用户{user_id}", "role": "member"},
        raw={"message": [{"type": "text", "data": {"text": text}}]},
        self_id=100001,
    )


async def _drain_ai_tasks(timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while engine._ai_tasks and time.monotonic() < deadline:
        await asyncio.sleep(0.02)


async def test_ai_reply_does_not_block_event_stream(
    client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db, monkeypatch
):
    """慢模型只应占用后台任务，不能让账号的事件循环停下来等。"""
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    calls: list[str] = []

    async def fake_ai(db_arg, account_arg, adapter_arg, event, group, group_settings, text, *, forced=False):
        calls.append(text)
        await asyncio.sleep(0.4)

    monkeypatch.setattr(engine, "_ai_reply", fake_ai)

    started = time.perf_counter()
    await engine.handle_event(db, account.id, adapter, _group_event(41001, "/ai 你好"))
    elapsed = time.perf_counter() - started

    assert elapsed < 0.25, f"handle_event 不应等待 AI 完成，实际耗时 {elapsed:.2f}s"
    assert calls == [], "AI 任务应当是异步启动的"

    await _drain_ai_tasks()
    assert calls == ["/ai 你好"]


async def test_same_group_messages_are_processed_in_order(
    client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db, monkeypatch
):
    """同一个群的多条消息必须串行，否则会话历史会乱序。"""
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    active = 0
    peak = 0
    finished: list[str] = []

    async def fake_ai(db_arg, account_arg, adapter_arg, event, group, group_settings, text, *, forced=False):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.15)
        active -= 1
        finished.append(text)

    monkeypatch.setattr(engine, "_ai_reply", fake_ai)

    for index in range(3):
        await engine.handle_event(db, account.id, adapter, _group_event(42001 + index, f"/ai 问题{index}"))
    await _drain_ai_tasks()

    assert peak == 1, "同一群内不应并发处理 AI 回复"
    assert finished == ["/ai 问题0", "/ai 问题1", "/ai 问题2"]


async def test_different_groups_can_run_concurrently(
    client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db, monkeypatch
):
    """不同群之间互相独立，应该能并发，否则多群场景仍然会排队。"""
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    active = 0
    peak = 0

    async def fake_ai(db_arg, account_arg, adapter_arg, event, group, group_settings, text, *, forced=False):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.2)
        active -= 1

    monkeypatch.setattr(engine, "_ai_reply", fake_ai)

    first = _group_event(43001, "/ai 群A")
    second = replace(first, group_id=GROUP_B, user_id=43002, raw_message="/ai 群B")
    await engine.handle_event(db, account.id, adapter, first)
    await engine.handle_event(db, account.id, adapter, second)
    await _drain_ai_tasks()

    assert peak >= 2, "不同群之间应当并发处理"


def test_limiter_reclaims_stale_keys():
    """公网扫描会制造大量 IP key，清扫后字典必须能回落。"""
    limiter = SlidingWindowLimiter(limit=100, window_seconds=1)
    limiter.SWEEP_EVERY = 10

    for index in range(30):
        limiter.allow(f"ip-{index}")
    assert len(limiter._hits) == 30

    time.sleep(1.05)
    for index in range(10):
        limiter.allow(f"fresh-{index}")

    assert len(limiter._hits) < 30, "过期 key 没有被回收"


async def test_legacy_webhook_path_is_rate_limited(client: httpx.AsyncClient, monkeypatch):
    """根路径 /webhook 不在 /api 前缀下，必须单独限流。"""
    monkeypatch.setattr(legacy_webhook_limiter, "limit", 2)
    monkeypatch.setattr(legacy_webhook_limiter, "_hits", defaultdict(deque))
    monkeypatch.setattr(legacy_webhook_limiter, "_ops", 0)

    first = await client.post("/webhook", json={})
    second = await client.post("/webhook", json={})
    third = await client.post("/webhook", json={})

    assert first.status_code != 429
    assert second.status_code != 429
    assert third.status_code == 429


def test_callback_path_matching_uses_segment_boundary():
    assert _path_matches("/api/webhook", "/api/webhook")
    assert _path_matches("/api/webhook/1905072314", "/api/webhook")
    assert not _path_matches("/api/webhook-foo", "/api/webhook")
