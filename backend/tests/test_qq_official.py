"""QQ 官方机器人接入单元测试。

全部使用临时 SQLite + 本地 mock，不连接 QQ 开放平台、不建立任何真实 WebSocket。
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque

import httpx
import pytest
import websockets

from app.adapters import qq_official
from app.adapters.base import AdapterError, UnsupportedAction
from app.adapters.qq_official import (
    DEFAULT_INTENTS,
    QQOfficialAdapter,
    QQOfficialApiError,
    _ReplyWindow,
)
from app.services.bot_engine import engine

APP_ID = "102099001"
GROUP_OPENID = "GROUP_OPENID_UNIT_1"
MEMBER_OPENID = "MEMBER_OPENID_UNIT_1"
USER_OPENID = "USER_OPENID_UNIT_1"


def make_adapter(account_id: int, **kwargs) -> QQOfficialAdapter:
    return QQOfficialAdapter(
        account_db_id=account_id, app_id=APP_ID, app_secret="unit-test-secret", **kwargs
    )


def group_payload(msg_id: str = "ROBOT1.0_group_in", event_id: str = "evt-group-1") -> dict:
    return {
        "op": 0,
        "s": 1,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "id": event_id,
        "d": {
            "id": msg_id,
            "author": {
                "member_openid": MEMBER_OPENID,
                "username": "小明",
                "member_role": "admin",
            },
            "content": " /天气 ",
            "group_openid": GROUP_OPENID,
            "message_type": 0,
            "message_scene": {"source": "default", "ext": ["msg_idx=REFIDX_UNIT_1"]},
        },
    }


def c2c_payload(msg_id: str = "ROBOT1.0_c2c_in", event_id: str = "evt-c2c-1") -> dict:
    return {
        "op": 0,
        "s": 2,
        "t": "C2C_MESSAGE_CREATE",
        "id": event_id,
        "d": {
            "id": msg_id,
            "author": {"user_openid": USER_OPENID, "username": "小红"},
            "content": "你好",
            "message_type": 0,
        },
    }


async def create_temp_account(client, admin_headers, **overrides) -> dict:
    payload = {
        "name": "官方适配器单测账号",
        "protocol": "mock",
        "connection_mode": "http",
        **overrides,
    }
    response = await client.post("/api/accounts", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def take_event(adapter: QQOfficialAdapter):
    return await asyncio.wait_for(adapter._queue.get(), timeout=1.0)


# --------------------------------------------------------------------------
# 能力声明：官方平台没有的群管理动作必须明确报错
# --------------------------------------------------------------------------
async def test_capabilities_are_honest():
    adapter = make_adapter(1)
    caps = adapter.capabilities()
    assert caps["send_group_message"] is True
    assert caps["send_private_message"] is True
    assert caps["get_login_info"] is True
    for action in ("set_group_ban", "set_group_kick", "set_group_card", "set_group_announce",
                   "set_group_admin", "delete_msg", "get_friend_list", "get_group_member_list"):
        assert caps[action] is False, action
    with pytest.raises(UnsupportedAction):
        await adapter.set_group_ban(1, 2, 60)
    with pytest.raises(UnsupportedAction):
        await adapter.set_friend_add_request("flag", True)


async def test_reply_window_limits():
    window = _ReplyWindow(
        msg_id="m1", event_id=None, created_at=time.monotonic(), max_uses=2
    )
    assert window.take() == {"msg_id": "m1", "msg_seq": 1}
    assert window.take() == {"msg_id": "m1", "msg_seq": 2}
    assert window.take() is None
    expired = _ReplyWindow(
        msg_id="m2", event_id=None, created_at=time.monotonic() - 400, max_uses=5
    )
    assert expired.take() is None


# --------------------------------------------------------------------------
# 事件解析 + OpenID 映射
# --------------------------------------------------------------------------
async def test_group_at_message_maps_openids_and_marks_at(client, admin_headers):
    account = await create_temp_account(client, admin_headers)
    try:
        adapter = make_adapter(account["id"])
        await adapter.feed_event(group_payload())
        event = await take_event(adapter)
        assert event.post_type == "message"
        assert event.message_type == "group"
        assert event.raw_message == "/天气"
        assert event.is_at_me is True
        assert event.sender_name == "小明"
        assert event.sender["role"] == "admin"
        assert event.group_id and event.user_id
        assert engine._clean_text(event, event.raw_message) == "/天气"
        # 同一个 OpenID 反复出现必须得到同一个整数 ID
        await adapter.feed_event(group_payload("ROBOT1.0_group_in_2", "evt-group-2"))
        second = await take_event(adapter)
        assert second.group_id == event.group_id
        assert second.user_id == event.user_id
        assert second.message_id != event.message_id
        await adapter.disconnect()
    finally:
        await client.delete(f"/api/accounts/{account['id']}", headers=admin_headers)


async def test_c2c_message_and_duplicate_dedup(client, admin_headers):
    account = await create_temp_account(client, admin_headers)
    try:
        adapter = make_adapter(account["id"])
        await adapter.feed_event(c2c_payload())
        event = await take_event(adapter)
        assert event.message_type == "private"
        assert event.group_id is None
        assert event.raw_message == "你好"
        assert event.user_id
        # 相同 msg_id + 相同 msg_idx 属于平台重复推送，必须被去重
        await adapter.feed_event(c2c_payload())
        with pytest.raises(asyncio.TimeoutError):
            await take_event(adapter)
        await adapter.disconnect()
    finally:
        await client.delete(f"/api/accounts/{account['id']}", headers=admin_headers)


async def test_group_robot_event_registers_group(client, admin_headers):
    account = await create_temp_account(client, admin_headers)
    try:
        adapter = make_adapter(account["id"])
        await adapter.feed_event({
            "op": 0, "s": 3, "t": "GROUP_ADD_ROBOT", "id": "evt-add-1",
            "d": {"group_openid": GROUP_OPENID, "timestamp": "2026-11-04T10:00:00+08:00"},
        })
        event = await take_event(adapter)
        assert event.post_type == "notice"
        assert event.sub_type == "robot_added"
        assert event.group_id
        groups = await adapter.get_group_list()
        assert any(item["group_id"] == event.group_id for item in groups)
        await adapter.disconnect()
    finally:
        await client.delete(f"/api/accounts/{account['id']}", headers=admin_headers)


# --------------------------------------------------------------------------
# 消息发送：被动回复优先、额度用尽后主动消息、过期降级
# --------------------------------------------------------------------------
async def test_passive_reply_uses_msg_id_and_increments_seq(client, admin_headers):
    account = await create_temp_account(client, admin_headers)
    try:
        adapter = make_adapter(account["id"], allow_proactive=True)
        await adapter.feed_event(group_payload())
        event = await take_event(adapter)
        calls: list[dict] = []

        async def fake_request(method, path, *, json_body=None, retry_auth=True):
            calls.append({"method": method, "path": path, "body": dict(json_body or {})})
            return {"id": f"ROBOT1.0_out_{len(calls)}", "timestamp": "2026-11-04T10:00:00+08:00"}

        adapter._request = fake_request
        first = await adapter.send_group_message(event.group_id, "第一次回复")
        assert first["data"]["message_id"] is not None
        assert GROUP_OPENID in calls[0]["path"]
        assert calls[0]["body"]["msg_id"] == "ROBOT1.0_group_in"
        assert calls[0]["body"]["msg_seq"] == 1
        await adapter.send_group_message(event.group_id, "第二次回复")
        assert calls[1]["body"]["msg_seq"] == 2
        # 群被动回复上限 5 次，之后退化为主动消息（不带 msg_id）
        for _ in range(3):
            await adapter.send_group_message(event.group_id, "继续")
        sixth = await adapter.send_group_message(event.group_id, "主动消息")
        assert "msg_id" not in calls[-1]["body"]
        assert sixth["data"]["message_id"] is not None
        await adapter.disconnect()
    finally:
        await client.delete(f"/api/accounts/{account['id']}", headers=admin_headers)


async def test_proactive_disabled_and_unknown_target(client, admin_headers):
    account = await create_temp_account(client, admin_headers)
    try:
        adapter = make_adapter(account["id"], allow_proactive=False)
        group_id = await adapter._resolve("group", GROUP_OPENID)
        with pytest.raises(AdapterError, match="主动消息"):
            await adapter.send_group_message(group_id, "定时推送")
        with pytest.raises(AdapterError, match="OpenID"):
            await adapter.send_private_message(999999999, "未知用户")
        await adapter.disconnect()
    finally:
        await client.delete(f"/api/accounts/{account['id']}", headers=admin_headers)


async def test_expired_passive_reply_falls_back_to_proactive(client, admin_headers):
    account = await create_temp_account(client, admin_headers)
    try:
        adapter = make_adapter(account["id"], allow_proactive=True)
        await adapter.feed_event(group_payload())
        event = await take_event(adapter)
        calls: list[dict] = []

        async def fake_request(method, path, *, json_body=None, retry_auth=True):
            calls.append(dict(json_body or {}))
            if len(calls) == 1:
                raise QQOfficialApiError(40034005, "回复消息msg_id已过期")
            return {"id": "ROBOT1.0_out_recovered"}

        adapter._request = fake_request
        result = await adapter.send_group_message(event.group_id, "降级发送")
        assert result["data"]["message_id"] is not None
        assert "msg_id" in calls[0]
        assert "msg_id" not in calls[1]
        await adapter.disconnect()
    finally:
        await client.delete(f"/api/accounts/{account['id']}", headers=admin_headers)


async def test_openapi_error_code_is_surfaced():
    adapter = make_adapter(1)

    async def fake_token(*, force: bool = False) -> str:
        return "unit-token"

    adapter._ensure_token = fake_token

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "QQBot unit-token"
        assert request.headers["X-Union-Appid"] == APP_ID
        return httpx.Response(
            200,
            json={"err_code": 40034105, "message": "no permission", "trace_id": "trace-unit-1"},
        )

    adapter._client = httpx.AsyncClient(
        base_url=adapter.api_base, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(QQOfficialApiError) as caught:
        await adapter._request("POST", "/v2/groups/X/messages", json_body={"content": "x"})
    assert caught.value.code == 40034105
    assert "主动消息" in str(caught.value)
    assert "trace-unit-1" in str(caught.value)
    await adapter.disconnect()


# --------------------------------------------------------------------------
# 账号 API：凭据校验、加密存储、配置回显、能力接口
# --------------------------------------------------------------------------
async def test_account_api_requires_official_credentials(client, admin_headers):
    response = await client.post(
        "/api/accounts", headers=admin_headers,
        json={"name": "缺凭据的官方账号", "protocol": "qq_official"},
    )
    assert response.status_code == 400
    assert "AppID" in response.json()["detail"]


async def test_account_api_create_update_and_secret_mask(client, admin_headers, monkeypatch):
    created = await client.post(
        "/api/accounts",
        headers=admin_headers,
        json={
            "name": "官方机器人 A",
            "protocol": "qq_official",
            "app_id": APP_ID,
            "app_secret": "super-secret-value",
            "official_sandbox": True,
            "official_allow_proactive": False,
            "official_intents": DEFAULT_INTENTS,
        },
    )
    assert created.status_code == 201, created.text
    account = created.json()
    account_id = account["id"]
    try:
        assert account["app_id"] == APP_ID
        assert account["connection_mode"] == "official_ws"
        assert account["has_secret"] is True
        assert account["official_sandbox"] is True
        assert account["official_allow_proactive"] is False
        assert account["official_intents"] == DEFAULT_INTENTS
        assert "super-secret-value" not in str(account)
        assert "app_secret" not in account

        # 编辑时留空密钥必须保持原有凭据，且 features 能增量更新
        updated = await client.put(
            f"/api/accounts/{account_id}", headers=admin_headers,
            json={"name": "官方机器人 A2", "app_secret": "", "official_sandbox": False},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["has_secret"] is True
        assert updated.json()["official_sandbox"] is False
        assert updated.json()["official_allow_proactive"] is False

        caps = await client.get(f"/api/accounts/{account_id}/capabilities", headers=admin_headers)
        assert caps.status_code == 200
        mapping = {item["key"]: item["supported"] for item in caps.json()["capabilities"]}
        assert mapping["send_group_message"] is True
        assert mapping["set_group_ban"] is False

        async def fake_probe(self):
            return {
                "app_id": self.app_id,
                "sandbox": self.sandbox,
                "gateway": "wss://unit.test/websocket",
                "intents": self.intents,
                "api_base": self.api_base,
            }

        monkeypatch.setattr(QQOfficialAdapter, "probe", fake_probe)
        tested = await client.post(f"/api/accounts/{account_id}/test-connection", headers=admin_headers)
        assert tested.status_code == 200
        assert tested.json()["ok"] is True
        assert tested.json()["data"]["gateway"] == "wss://unit.test/websocket"
    finally:
        await client.delete(f"/api/accounts/{account_id}", headers=admin_headers)


class FakeGatewayWS:
    """最小 WebSocket 替身：按序下发网关 Payload，并记录客户端发出的 OpCode。"""

    def __init__(self, incoming: list[dict]) -> None:
        self.incoming = deque(incoming)
        self.sent: list[dict] = []
        self.closed = False
        self._wait: asyncio.Future | None = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.incoming:
            return json.dumps(self.incoming.popleft())
        if self.closed:
            raise StopAsyncIteration
        self._wait = asyncio.get_running_loop().create_future()
        return await self._wait

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        # 客户端心跳立即回 ACK，避免心跳看门狗提前关闭连接。
        if payload["op"] == 1 and self._wait and not self._wait.done():
            self._wait.set_result(json.dumps({"op": 11}))

    async def close(self) -> None:
        self.closed = True
        if self._wait and not self._wait.done():
            self._wait.cancel()


async def test_gateway_connect_identify_heartbeat_and_resume(client, admin_headers, monkeypatch):
    """完整状态机：连接 → Hello/Identify → READY → 事件 → 心跳 → 断线 Resume。"""
    monkeypatch.setattr(qq_official, "MIN_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    account = await create_temp_account(client, admin_headers)
    try:
        adapter = make_adapter(account["id"])
        first_ws = FakeGatewayWS([
            {"op": 10, "d": {"heartbeat_interval": 50}},
            {"op": 0, "s": 1, "t": "READY", "d": {
                "session_id": "sess-unit-1",
                "user": {"id": "BOT_OPENID_UNIT", "username": "测试机器人"},
            }},
            {
                "op": 0, "s": 2, "t": "GROUP_AT_MESSAGE_CREATE",
                "id": "evt-gateway-1", "d": group_payload()["d"],
            },
        ])

        async def fake_token(*, force: bool = False) -> str:
            return "unit-token"

        async def fake_request(method, path, *, json_body=None, retry_auth=True):
            if path == "/gateway":
                return {"url": "wss://unit.test/websocket"}
            return {"id": "ROBOT1.0_out"}

        adapter._ensure_token = fake_token
        adapter._request = fake_request

        async def fake_connect(url, **kwargs):
            assert url == "wss://unit.test/websocket"
            return first_ws

        monkeypatch.setattr(websockets, "connect", fake_connect)
        info = await adapter.connect()
        assert info.nickname == "测试机器人"
        assert info.self_id == int(APP_ID)
        assert adapter.connected is True
        assert adapter.gateway_session_id == "sess-unit-1"
        assert adapter.bot_openid == "BOT_OPENID_UNIT"

        for _ in range(30):
            if any(m["op"] == 2 for m in first_ws.sent) and any(m["op"] == 1 for m in first_ws.sent):
                break
            await asyncio.sleep(0.02)
        identify = next(m for m in first_ws.sent if m["op"] == 2)
        assert identify["d"]["token"] == "QQBot unit-token"
        assert identify["d"]["intents"] == DEFAULT_INTENTS
        assert identify["d"]["shard"] == [0, 1]
        assert any(m["op"] == 1 for m in first_ws.sent), "未发送应用层心跳"

        lifecycle = await take_event(adapter)
        assert lifecycle.post_type == "meta_event" and lifecycle.sub_type == "lifecycle"
        message = await take_event(adapter)
        assert message.message_type == "group" and message.is_at_me

        # 断开后重连，应优先用 OpCode 6 Resume 恢复会话而不是重新 Identify
        await adapter.disconnect()
        second_ws = FakeGatewayWS([
            {"op": 10, "d": {"heartbeat_interval": 60000}},
            {"op": 0, "s": 3, "t": "RESUMED", "d": ""},
        ])

        async def fake_connect_2(url, **kwargs):
            return second_ws

        monkeypatch.setattr(websockets, "connect", fake_connect_2)
        await adapter.connect()
        for _ in range(30):
            if any(m["op"] == 6 for m in second_ws.sent):
                break
            await asyncio.sleep(0.02)
        resume = next(m for m in second_ws.sent if m["op"] == 6)
        assert resume["d"]["session_id"] == "sess-unit-1"
        assert resume["d"]["seq"] is not None
        assert not any(m["op"] == 2 for m in second_ws.sent)
        await adapter.disconnect()
    finally:
        await client.delete(f"/api/accounts/{account['id']}", headers=admin_headers)
