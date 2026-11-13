"""QQ 官方机器人 Webhook 接入测试。

包含官方文档给出的 Ed25519 DEMO 常量，用于验证密钥派生与签名算法与平台一致；
端点测试全部走本地 ASGI + 临时 SQLite，不连接任何外部服务。
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from app.adapters.qq_official import QQOfficialAdapter
from app.services import qq_webhook_crypto as crypto
from app.services.account_manager import account_manager

APP_ID = "102099002"
APP_SECRET = "DG5g3B4j9X2KOErG"

# 官方文档《安全和授权》DEMO：secret -> seed -> 公钥
DOC_SECRET = "naOC0ocQE3shWLAfffVLB1rhYPG7"
DOC_SEED = b"naOC0ocQE3shWLAfffVLB1rhYPG7naOC"
DOC_PUBLIC_KEY = bytes(
    [
        215, 195, 98, 254, 120, 174, 248, 31, 242, 50, 135, 180, 147, 98, 139, 93,
        176, 42, 60, 79, 227, 11, 33, 94, 77, 25, 96, 155, 93, 118, 103, 58,
    ]
)

# 官方文档《Webhook 方式》DEMO：op=13 回调地址验证
VALIDATION_TS = "1725442341"
VALIDATION_TOKEN = "Arq0D5A61EgUu4OxUvOp"
VALIDATION_SIGNATURE = (
    "87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcad"
    "c0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706"
)


def signed_body(payload: dict, *, secret: str = APP_SECRET, timestamp: str | None = None) -> tuple[bytes, dict]:
    """按平台规则用私钥签 timestamp + 原始 body，返回 (原始字节, 请求头)。"""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stamp = timestamp or str(int(time.time()))
    signature = crypto.derive_private_key(secret).sign(stamp.encode("utf-8") + body).hex()
    headers = {
        "Content-Type": "application/json",
        "X-Signature-Ed25519": signature,
        "X-Signature-Timestamp": stamp,
        "X-Bot-Appid": APP_ID,
        "User-Agent": "QQBot-Callback",
    }
    return body, headers


def group_event(msg_id: str = "ROBOT1.0_webhook_in") -> dict:
    return {
        "op": 0,
        "s": 1,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "id": "evt-webhook-1",
        "d": {
            "id": msg_id,
            "author": {"member_openid": "MEMBER_WEBHOOK_1", "username": "测试用户"},
            "content": " /帮助 ",
            "group_openid": "GROUP_WEBHOOK_1",
            "message_scene": {"ext": ["msg_idx=WEBHOOK_IDX_1"]},
        },
    }


@pytest.fixture
async def webhook_account(client, admin_headers):
    response = await client.post(
        "/api/accounts",
        headers=admin_headers,
        json={
            "name": "Webhook 单测机器人",
            "protocol": "qq_official",
            "connection_mode": "official_webhook",
            "app_id": APP_ID,
            "app_secret": APP_SECRET,
            "auto_reconnect": False,
        },
    )
    assert response.status_code == 201, response.text
    account = response.json()
    try:
        yield account
    finally:
        await account_manager.stop(account["id"])
        await client.delete(f"/api/accounts/{account['id']}", headers=admin_headers)


# --------------------------------------------------------------------------
# 与官方文档 DEMO 逐字节对照，确保派生算法不是「自签自验」的假验证
# --------------------------------------------------------------------------
def test_seed_and_public_key_match_official_demo():
    assert crypto.derive_seed(DOC_SECRET) == DOC_SEED
    assert len(crypto.derive_seed(DOC_SECRET)) == crypto.SEED_SIZE
    assert crypto.public_key_bytes(DOC_SECRET) == DOC_PUBLIC_KEY


def test_validation_signature_matches_official_demo():
    signature = crypto.sign_callback_validation(APP_SECRET, VALIDATION_TS, VALIDATION_TOKEN)
    assert signature == VALIDATION_SIGNATURE
    assert len(signature) == 128


def test_event_signature_verify_and_reject_tampering():
    body = b'{"op":0,"t":"C2C_MESSAGE_CREATE"}'
    stamp = str(int(time.time()))
    signature = crypto.derive_private_key(APP_SECRET).sign(stamp.encode() + body).hex()
    assert crypto.verify_event_signature(APP_SECRET, stamp, body, signature)[0] is True
    ok, reason = crypto.verify_event_signature(APP_SECRET, stamp, body + b" ", signature)
    assert ok is False and "不匹配" in reason
    assert crypto.verify_event_signature(APP_SECRET, "", body, signature)[0] is False
    assert crypto.verify_event_signature(APP_SECRET, stamp, body, "zz")[0] is False
    assert crypto.verify_event_signature(APP_SECRET, "not-a-number", body, signature)[0] is False
    stale = str(int(time.time()) - 3600)
    ok, reason = crypto.verify_event_signature(APP_SECRET, stale, body, signature)
    assert ok is False and "时间窗口" in reason


# --------------------------------------------------------------------------
# 回调地址验证（op=13）：账号无需在线即可握手
# --------------------------------------------------------------------------
async def test_callback_validation_handshake(client, webhook_account):
    response = await client.post(
        f"/api/qqbot/webhook/{APP_ID}",
        json={"op": 13, "d": {"plain_token": VALIDATION_TOKEN, "event_ts": VALIDATION_TS}},
        headers={"X-Bot-Appid": APP_ID, "User-Agent": "QQBot-Callback"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plain_token"] == VALIDATION_TOKEN
    assert body["signature"] == VALIDATION_SIGNATURE
    # 全量测试时可能有其它测试留下的同 id runtime，必须按账号 UID 区分
    state = account_manager.get(webhook_account["id"])
    assert state is None or state.account_uid != webhook_account["account_id"], "地址验证不应启动长连接"


async def test_legacy_webhook_path_uses_header_appid(client, webhook_account):
    response = await client.post(
        "/webhook",
        json={"op": 13, "d": {"plain_token": VALIDATION_TOKEN, "event_ts": VALIDATION_TS}},
        headers={"X-Bot-Appid": APP_ID},
    )
    assert response.status_code == 200, response.text
    assert response.json()["signature"] == VALIDATION_SIGNATURE


async def test_placeholder_appid_falls_back_to_single_account(client, webhook_account):
    """平台回调地址里带着示例占位符（1029xxxx）时仍要能用，安全由验签保证。"""
    response = await client.post(
        "/api/qqbot/webhook/1029xxxx",
        json={"op": 13, "d": {"plain_token": VALIDATION_TOKEN, "event_ts": VALIDATION_TS}},
        headers={"X-Bot-Appid": APP_ID},
    )
    assert response.status_code == 200, response.text
    assert response.json()["signature"] == VALIDATION_SIGNATURE
    # 占位符 + 没有请求头时，只有一个官方账号也应回退成功
    bare = await client.post(
        "/api/qqbot/webhook/1029xxxx",
        json={"op": 13, "d": {"plain_token": VALIDATION_TOKEN, "event_ts": VALIDATION_TS}},
    )
    assert bare.status_code == 200, bare.text


async def test_webhook_get_probe_returns_200(client, webhook_account):
    """平台保存回调地址前后会做可达性探测，GET 不能返回 405。"""
    response = await client.get(f"/api/qqbot/webhook/{APP_ID}")
    assert response.status_code == 200
    assert response.json()["endpoint"] == "qqbot-webhook"


# --------------------------------------------------------------------------
# 事件推送（op=0）：验签、在线门控、事件注入
# --------------------------------------------------------------------------
async def test_event_push_rejects_missing_and_invalid_signature(client, webhook_account):
    body, headers = signed_body(group_event())
    missing = await client.post(
        f"/api/qqbot/webhook/{APP_ID}", content=body, headers={"Content-Type": "application/json", "X-Bot-Appid": APP_ID}
    )
    assert missing.status_code == 401
    tampered = dict(headers, **{"X-Signature-Ed25519": "0" * 128})
    forged = await client.post(f"/api/qqbot/webhook/{APP_ID}", content=body, headers=tampered)
    assert forged.status_code == 401
    # 改了 body 但沿用旧签名，也必须被拒绝
    altered = await client.post(
        f"/api/qqbot/webhook/{APP_ID}", content=body + b" ", headers=headers
    )
    assert altered.status_code == 401


async def test_event_push_returns_503_when_bot_offline(client, webhook_account):
    body, headers = signed_body(group_event())
    response = await client.post(f"/api/qqbot/webhook/{APP_ID}", content=body, headers=headers)
    assert response.status_code == 503
    assert "启动账号" in response.json()["detail"]


async def test_event_push_delivers_to_webhook_adapter(client, webhook_account, monkeypatch):
    adapter = QQOfficialAdapter(
        account_db_id=webhook_account["id"],
        app_id=APP_ID,
        app_secret=APP_SECRET,
        callback_mode="webhook",
    )
    await adapter.connect()
    assert adapter.is_webhook and adapter.connected
    monkeypatch.setattr(account_manager, "adapter", lambda account_db_id: adapter)
    try:
        body, headers = signed_body(group_event())
        response = await client.post(f"/api/qqbot/webhook/{APP_ID}", content=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is True
        event = await asyncio.wait_for(adapter._queue.get(), timeout=1.0)
        assert event.post_type == "message"
        assert event.message_type == "group"
        assert event.raw_message == "/帮助"
        assert event.is_at_me is True
        assert event.group_id and event.user_id
        # feed_event 会附带一条低频心跳 meta_event，先消费掉再做去重断言
        heartbeat = await asyncio.wait_for(adapter._queue.get(), timeout=1.0)
        assert heartbeat.post_type == "meta_event" and heartbeat.sub_type == "heartbeat"

        # 平台重复推送同一 msg_id + msg_idx 必须被适配器去重
        duplicate = await client.post(f"/api/qqbot/webhook/{APP_ID}", content=body, headers=headers)
        assert duplicate.status_code == 200
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(adapter._queue.get(), timeout=0.2)
    finally:
        await adapter.disconnect()


async def test_webhook_adapter_ignores_gateway_opcodes():
    adapter = QQOfficialAdapter(
        account_db_id=1, app_id=APP_ID, app_secret=APP_SECRET, callback_mode="webhook"
    )
    await adapter.connect()
    try:
        await adapter.feed_event({"op": 10, "d": {"heartbeat_interval": 40000}})
        await adapter.feed_event({"op": 13, "d": {"plain_token": "x", "event_ts": "1"}})
        assert adapter._queue.empty()
        info = await adapter.get_login_info()
        assert info.self_id == int(APP_ID)
    finally:
        await adapter.disconnect()


# --------------------------------------------------------------------------
# 账号配置：模式持久化、回调地址回显、启动不依赖外网
# --------------------------------------------------------------------------
async def test_account_api_exposes_webhook_mode_and_url(client, admin_headers, webhook_account, db):
    from app.models import Account
    from app.services.account_manager import build_adapter

    listed = await client.get("/api/accounts", headers=admin_headers)
    row = next(item for item in listed.json() if item["id"] == webhook_account["id"])
    assert row["connection_mode"] == "official_webhook"
    assert row["webhook_url"].endswith(f"/api/qqbot/webhook/{APP_ID}")

    account = await db.get(Account, webhook_account["id"])
    adapter = build_adapter(account)
    assert isinstance(adapter, QQOfficialAdapter) and adapter.is_webhook
    # Webhook 模式启动不发起任何网络请求，也不申请 AccessToken。
    info = await adapter.connect()
    assert info.nickname and adapter.connected is True
    await adapter.disconnect()


async def test_switching_to_removed_protocol_is_rejected(client, admin_headers, webhook_account):
    updated = await client.put(
        f"/api/accounts/{webhook_account['id']}",
        headers=admin_headers,
        json={"protocol": "onebot11", "api_base": "http://127.0.0.1:3000"},
    )
    assert updated.status_code == 422, updated.text
