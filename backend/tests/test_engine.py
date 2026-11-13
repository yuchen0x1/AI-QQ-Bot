"""机器人引擎：消息落库、自动管理、命令权限、插件钩子。"""

from __future__ import annotations


import httpx
from sqlalchemy import select

from app.adapters.base import AdapterEvent
from app.models import Account, BotRequest, Group, Message
from app.services.account_manager import account_manager
from app.services.bot_engine import engine

GROUP_NUMBER = 900001


async def _setup_group(client: httpx.AsyncClient, headers: dict[str, str], account: dict) -> Group:
    await client.post(f"/api/groups/sync/{account['id']}", headers=headers)
    groups = (await client.get(f"/api/groups?account_id={account['id']}", headers=headers)).json()["items"]
    target = next(g for g in groups if g["group_number"] == GROUP_NUMBER)
    await client.post(f"/api/groups/{target['id']}/sync", headers=headers)
    return target


def _group_event(user_id: int, text: str, role: str = "member", at: list[int] | None = None) -> AdapterEvent:
    segments = [{"type": "text", "data": {"text": text}}]
    for uid in at or []:
        segments.append({"type": "at", "data": {"qq": str(uid)}})
    return AdapterEvent(
        post_type="message",
        message_type="group",
        group_id=GROUP_NUMBER,
        user_id=user_id,
        message_id=990001,
        raw_message=text,
        sender={"nickname": f"用户{user_id}", "role": role},
        raw={"message": segments, "raw_message": text},
        self_id=100001,
    )


async def test_message_persisted(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db):
    await _setup_group(client, admin_headers, mock_account)
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    await engine.handle_event(db, account.id, adapter, _group_event(30001, "这是一条普通消息"))

    row = await db.scalar(select(Message).where(Message.sender_id == 30001).order_by(Message.id.desc()))
    assert row is not None
    assert row.content == "这是一条普通消息"
    assert row.account_id == account.id
    assert row.qq_group == GROUP_NUMBER


async def test_banned_word_triggers_mute(
    client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db
):
    group = await _setup_group(client, admin_headers, mock_account)
    await client.put(
        f"/api/groups/{group['id']}/settings",
        headers=admin_headers,
        json={"banned_words": ["加微信"], "auto_warn_threshold": 1, "moderation_mode": "normal", "auto_mute_seconds": 120},
    )
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    await engine.handle_event(db, account.id, adapter, _group_event(30002, "快来加微信领福利"))

    assert (GROUP_NUMBER, 30002) in adapter.bans
    blocked = await db.scalar(
        select(Message).where(Message.sender_id == 30002, Message.direction == "in").order_by(Message.id.desc())
    )
    assert blocked is not None and blocked.blocked is True
    assert "违禁词" in (blocked.block_reason or "")


async def test_member_cannot_mute(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db):
    await _setup_group(client, admin_headers, mock_account)
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    before = len(adapter.outbox)
    await engine.handle_event(db, account.id, adapter, _group_event(30003, "/禁言 20001 10", role="member"))
    replies = [item["message"] for item in adapter.outbox[before:]]
    assert any("权限不足" in reply for reply in replies)
    assert (GROUP_NUMBER, 20001) not in adapter.bans


async def test_admin_can_mute(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db):
    await _setup_group(client, admin_headers, mock_account)
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    await engine.handle_event(db, account.id, adapter, _group_event(30004, "/禁言 20003 5", role="admin"))
    assert adapter.bans[(GROUP_NUMBER, 20003)] == 300


async def test_help_command(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db):
    await _setup_group(client, admin_headers, mock_account)
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    before = len(adapter.outbox)
    await engine.handle_event(db, account.id, adapter, _group_event(30005, "/help"))
    replies = [item["message"] for item in adapter.outbox[before:]]
    assert replies and "可用命令" in replies[0]


async def test_plugin_command(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db):
    await _setup_group(client, admin_headers, mock_account)
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    before = len(adapter.outbox)
    await engine.handle_event(db, account.id, adapter, _group_event(30006, "/roll 1d6"))
    replies = [item["message"] for item in adapter.outbox[before:]]
    assert replies and replies[0].startswith("🎲")


async def test_group_request_is_durable_deduplicated_and_reviewable(
    client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db
):
    account = await db.get(Account, mock_account["id"])
    event = AdapterEvent(post_type="request", sub_type="add", user_id=32123, group_id=GROUP_NUMBER,
        raw={"request_type":"group", "sub_type":"add", "flag":"group-flag-1", "group_id":GROUP_NUMBER,
             "user_id":32123, "comment":"我想加入群聊"})
    assert event is not None
    await engine.handle_event(db, account.id, account_manager.adapter(account.id), event)
    await engine.handle_event(db, account.id, account_manager.adapter(account.id), event)

    pending = await client.get("/api/requests", headers=admin_headers, params={"account_id": account.id})
    assert pending.status_code == 200, pending.text
    items = pending.json()["items"]
    assert len(items) == 1
    request_id = items[0]["id"]
    assert items[0]["comment"] == "我想加入群聊"

    rejected = await client.post(
        f"/api/requests/{request_id}/decision",
        headers=admin_headers,
        json={"approve": False, "reason": "请补充群内熟人"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["decision_reason"] == "请补充群内熟人"
    adapter = account_manager.adapter(account.id)
    assert adapter.request_decisions[-1]["flag"] == "group-flag-1"
    assert adapter.request_decisions[-1]["approve"] is False
    duplicate = await client.post(
        f"/api/requests/{request_id}/decision",
        headers=admin_headers,
        json={"approve": True},
    )
    assert duplicate.status_code == 409
    stored = await db.get(BotRequest, request_id)
    assert stored.status == "rejected"


async def test_friend_request_approval_calls_protocol(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db):
    account = await db.get(Account, mock_account["id"])
    event = AdapterEvent(
        post_type="request",
        sub_type="add",
        user_id=32124,
        raw={"request_type": "friend", "sub_type": "add", "flag": "friend-flag-1", "user_id": 32124, "comment": "机器人交流"},
    )
    await engine.handle_event(db, account.id, account_manager.adapter(account.id), event)
    listed = await client.get("/api/requests", headers=admin_headers, params={"account_id": account.id, "request_type": "friend"})
    request_id = listed.json()["items"][0]["id"]
    approved = await client.post(
        f"/api/requests/{request_id}/decision",
        headers=admin_headers,
        json={"approve": True, "remark": "QBot"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    adapter = account_manager.adapter(account.id)
    assert adapter.request_decisions[-1]["type"] == "friend"
    assert adapter.request_decisions[-1]["remark"] == "QBot"


async def test_viewer_cannot_decide_request(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db):
    account = await db.get(Account, mock_account["id"])
    event = AdapterEvent(
        post_type="request",
        sub_type="add",
        user_id=32125,
        raw={"request_type": "friend", "flag": "friend-flag-2", "user_id": 32125},
    )
    await engine.handle_event(db, account.id, account_manager.adapter(account.id), event)
    listed = await client.get("/api/requests", headers=admin_headers, params={"account_id": account.id, "request_type": "friend"})
    request_id = next(item["id"] for item in listed.json()["items"] if item["user_id"] == 32125)
    roles = (await client.get("/api/roles", headers=admin_headers)).json()
    viewer = next(item for item in roles if item["name"] == "viewer")
    await client.post("/api/users", headers=admin_headers, json={"username": "request_viewer", "password": "Viewer@12345", "role_id": viewer["id"]})
    login = await client.post("/api/auth/login", json={"username": "request_viewer", "password": "Viewer@12345"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied = await client.post(f"/api/requests/{request_id}/decision", headers=headers, json={"approve": True})
    assert denied.status_code == 403


async def test_request_record_stays_pending_when_account_offline(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db):
    account = await db.get(Account, mock_account["id"])
    event = AdapterEvent(
        post_type="request", sub_type="add", user_id=32126,
        raw={"request_type": "friend", "flag": "friend-flag-offline", "user_id": 32126},
    )
    await engine.handle_event(db, account.id, account_manager.adapter(account.id), event)
    listed = await client.get("/api/requests", headers=admin_headers, params={"account_id": account.id, "request_type": "friend"})
    request_id = listed.json()["items"][0]["id"]
    await client.post(f"/api/accounts/{account.id}/stop", headers=admin_headers)
    stopped = await client.post(f"/api/requests/{request_id}/decision", headers=admin_headers, json={"approve": True})
    assert stopped.status_code == 409
    stored = await db.get(BotRequest, request_id)
    assert stored.status == "pending"


async def test_welcome_on_member_join(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict, db):
    group = await _setup_group(client, admin_headers, mock_account)
    await client.put(
        f"/api/groups/{group['id']}/settings",
        headers=admin_headers,
        json={"welcome_enabled": True, "welcome_template": "欢迎 {nickname} 加入 {group_name}"},
    )
    account = await db.get(Account, mock_account["id"])
    adapter = account_manager.adapter(account.id)
    before = len(adapter.outbox)
    notice = AdapterEvent(
        post_type="notice",
        sub_type="group_increase",
        group_id=GROUP_NUMBER,
        user_id=30007,
        sender={"nickname": "新同学"},
        raw={"notice_type": "group_increase", "user_id": 30007},
        self_id=100001,
    )
    await engine.handle_event(db, account.id, adapter, notice)
    replies = [item["message"] for item in adapter.outbox[before:]]
    assert replies and "新同学" in replies[0]
