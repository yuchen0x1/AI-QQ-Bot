"""API 菜单与命令、账号连接、消息持久化的集成。"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from app.adapters.base import AdapterError, AdapterEvent
from app.adapters.qq_official import QQOfficialApiError
from app.models import Account, BotCommand, Message
from app.services.account_manager import account_manager
from app.services.bot_engine import engine
from app.services.bot_reply import BotReply
from app.services.suyan import suyan_service

GROUP = 900001
USER = 85001


@pytest.fixture(autouse=True)
def _reset_moderation_tracker():
    """刷屏计数器是模块级状态，会话级数据库下跨用例累积；本文件不测审核，统一清空。"""
    from app.services.moderation import rate_tracker

    rate_tracker._hits.clear()
    rate_tracker._recent.clear()
    yield


def event(text: str, *, user: int = USER) -> AdapterEvent:
    return AdapterEvent(
        post_type="message", message_type="group", group_id=GROUP,
        user_id=user, self_id=100001, raw_message=text,
        sender={"nickname": "菜单用户", "role": "member"},
        raw={"message": [{"type": "text", "data": {"text": text}}]},
    )


async def setup(db, mock_account):
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    group, settings = await engine._ensure_group(db, account, GROUP)
    return account, adapter, group, settings


async def drain():
    tasks = list(engine._api_tasks.values())
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)


async def test_chinese_menu_and_help_remain_separate(client, admin_headers, mock_account, db, monkeypatch):
    account, adapter, _, _ = await setup(db, mock_account)

    def no_ai(*args, **kwargs):
        pytest.fail("菜单不应交给 AI")

    monkeypatch.setattr(engine, "schedule_ai_reply", no_ai)
    before = len(adapter.outbox)
    await engine.handle_event(db, account.id, adapter, event("菜单"))
    menu = adapter.outbox[before]
    assert "素颜" in menu["message"]
    assert menu["markdown"] is None and menu["keyboard"] is None
    assert "下一页：/菜单 2" in menu["message"]
    await engine.handle_event(db, account.id, adapter, event("菜单2"))
    assert "第 2/" in adapter.outbox[-1]["message"]
    await engine.handle_event(db, account.id, adapter, event("帮助"))
    assert "可用命令" in adapter.outbox[-1]["message"]


async def test_api_preserves_arguments_and_custom_prefix(client, admin_headers, mock_account, db, monkeypatch):
    account, adapter, _, settings = await setup(db, mock_account)
    settings.command_prefix = "!"
    await db.commit()
    calls = []

    async def execute(key, raw_args, session_key, prefix="/"):
        calls.append((key, raw_args, session_key, prefix))
        return BotReply("接口调用结果")

    monkeypatch.setattr(suyan_service, "execute", execute)
    incoming = event('!接口 weather city="New York"')
    await engine.handle_event(db, account.id, adapter, incoming)
    await drain()
    assert calls == [("weather", 'city="New York"', (account.id, GROUP, USER), "!")]
    assert incoming.raw["_inbox_deferred"] is True
    assert adapter.outbox[-1]["message"] == "接口调用结果"
    saved = await db.scalar(select(Message).where(Message.account_id == account.id, Message.direction == "out"))
    assert saved and saved.content == "接口调用结果"


async def test_api_wait_does_not_block_menu_or_admit_duplicate(client, admin_headers, mock_account, db, monkeypatch):
    account, adapter, _, _ = await setup(db, mock_account)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def slow(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return BotReply("慢接口完成")

    monkeypatch.setattr(suyan_service, "execute", slow)
    try:
        await engine.handle_event(db, account.id, adapter, event("接口 slow"))
        await asyncio.wait_for(entered.wait(), 2)
        await engine.handle_event(db, account.id, adapter, event("接口 slow"))
        assert "正在处理" in adapter.outbox[-1]["message"]
        await engine.handle_event(db, account.id, adapter, event("菜单", user=USER + 1))
        assert adapter.outbox[-1]["keyboard"] is None
        assert "下一页：/菜单 2" in adapter.outbox[-1]["message"]
        assert calls == 1
    finally:
        release.set()
        await drain()


async def test_disabled_api_cannot_continue_existing_session(client, admin_headers, mock_account, db, monkeypatch):
    account, adapter, _, _ = await setup(db, mock_account)
    record = await db.scalar(select(BotCommand).where(BotCommand.name == "api"))
    original = record.enabled
    cancelled = []
    monkeypatch.setattr(suyan_service, "has_session", lambda key: key == (account.id, GROUP, USER))
    monkeypatch.setattr(suyan_service, "cancel_session", lambda key: cancelled.append(key) or BotReply("已取消"))

    async def must_not_run(*args, **kwargs):
        pytest.fail("已禁用命令不应继续调用接口")

    monkeypatch.setattr(suyan_service, "continue_session", must_not_run)
    try:
        record.enabled = False
        await db.commit()
        await engine.handle_event(db, account.id, adapter, event("北京"))
        await drain()
        assert cancelled == [(account.id, GROUP, USER)]
        assert "已被禁用" in adapter.outbox[-1]["message"]
    finally:
        record.enabled = original
        await db.commit()


@pytest.mark.parametrize("mode", ["plain", "template"])
async def test_account_menu_rendering_modes(client, admin_headers, mock_account, db, mode):
    account, adapter, _, _ = await setup(db, mock_account)
    account.features = {
        **(account.features or {}), "official_menu_markdown_mode": mode,
        "official_menu_template_id": "approved-template", "official_menu_template_key": "body",
    }
    await db.commit()
    await engine.handle_event(db, account.id, adapter, event("菜单"))
    sent = adapter.outbox[-1]
    if mode == "plain":
        assert sent["markdown"] is None and sent["keyboard"] is None
        assert "菜单" in sent["message"]
    else:
        assert sent["markdown"]["custom_template_id"] == "approved-template"
        assert sent["markdown"]["params"][0]["key"] == "body"
        assert sent["keyboard"]


async def test_explicit_card_rejection_falls_back_once_and_persists_once(client, admin_headers, mock_account, db, monkeypatch):
    account, adapter, _, _ = await setup(db, mock_account)
    account.features = {**(account.features or {}), "official_menu_markdown_mode": "native"}
    await db.commit()
    send = adapter.send_group_message
    attempts = []

    async def reject_markdown(group_id, message, **kwargs):
        attempts.append(kwargs)
        if kwargs.get("markdown"):
            raise QQOfficialApiError(304023, "Markdown permission denied")
        return await send(group_id, message, **kwargs)

    monkeypatch.setattr(adapter, "send_group_message", reject_markdown)
    await engine.handle_event(db, account.id, adapter, event("菜单"))
    card_attempts = [item for item in attempts if item.get("markdown")]
    assert len(card_attempts) == 1
    assert len(attempts) <= 3
    assert attempts[-1].get("markdown") is None and attempts[-1].get("keyboard") is None
    assert adapter.outbox[-1]["markdown"] is None
    count = await db.scalar(select(func.count()).select_from(Message).where(
        Message.account_id == account.id, Message.direction == "out",
    ))
    assert count == 1

async def test_uncertain_network_failure_is_not_sent_twice(client, admin_headers, mock_account, db, monkeypatch):
    account, adapter, _, _ = await setup(db, mock_account)
    attempts = 0

    async def network_failure(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise AdapterError("network timeout")

    monkeypatch.setattr(adapter, "send_group_message", network_failure)
    with pytest.raises(AdapterError, match="network timeout"):
        await engine.handle_event(db, account.id, adapter, event("菜单"))
    assert attempts <= 2


async def test_account_stop_cancels_api_and_finishes_inbox(client, admin_headers, mock_account, db, monkeypatch):
    account, adapter, _, _ = await setup(db, mock_account)
    entered, cancelled = asyncio.Event(), asyncio.Event()
    completed = []

    async def slow(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def finish(adapter, incoming, *, error=None):
        completed.append(error)

    monkeypatch.setattr(suyan_service, "execute", slow)
    monkeypatch.setattr(engine, "_finish_inbox", finish)
    await engine.handle_event(db, account.id, adapter, event("接口 slow"))
    await asyncio.wait_for(entered.wait(), 2)
    await engine.cancel_account(account.id)
    assert cancelled.is_set()
    assert completed == ["API processing cancelled"]
    assert not any(key[0] == account.id and not task.done() for key, task in engine._api_tasks.items())


async def test_cancel_before_api_task_starts_releases_inbox(monkeypatch):
    completed = []
    incoming = event("接口 slow")

    async def finish(adapter, incoming, *, error=None):
        completed.append(error)

    monkeypatch.setattr(engine, "_finish_inbox", finish)
    assert engine.schedule_api_reply(999999, None, incoming, incoming.raw_message)
    await engine.cancel_account(999999)
    assert completed == ["API processing cancelled before start"]
