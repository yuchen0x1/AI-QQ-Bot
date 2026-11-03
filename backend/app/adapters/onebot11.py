"""OneBot v11 适配器：兼容 NapCat / Lagrange / go-cqhttp 等实现。

支持三种接入方式：
1. ws_client：主动连接协议端的正向 WebSocket 事件流（配合 HTTP API）。
2. ws_server：协议端反向 WebSocket 连到本平台，由 FastAPI 端点注入事件。
3. http：仅 HTTP API + 事件通过 webhook 注入。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.adapters.base import (
    AdapterError,
    AdapterEvent,
    LoginInfo,
    QQAdapter,
)

logger = logging.getLogger("qbot.adapter.onebot11")

# OneBot v11 标准动作集合
_ONEBOT_ACTIONS = {
    "send_private_message",
    "send_group_message",
    "get_login_info",
    "get_friend_list",
    "get_group_list",
    "get_group_info",
    "get_group_member_list",
    "set_group_ban",
    "set_group_whole_ban",
    "set_group_kick",
    "set_group_card",
    "set_group_name",
    "set_group_announce",
    "set_group_admin",
    "delete_msg",
    "set_group_add_request",
    "set_friend_add_request",
}


class OneBot11Adapter(QQAdapter):
    protocol = "onebot11"

    def __init__(
        self,
        *,
        api_base: str | None,
        ws_url: str | None,
        access_token: str | None,
        connection_mode: str = "ws_client",
        timeout: float = 15.0,
    ) -> None:
        super().__init__()
        self.api_base = (api_base or "").rstrip("/")
        self.ws_url = ws_url
        self.access_token = access_token
        self.connection_mode = connection_mode
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._ws: Any = None
        self._connected = False
        self._queue: asyncio.Queue[AdapterEvent] = asyncio.Queue(maxsize=1000)
        self._listener_task: asyncio.Task | None = None
        self._supported = set(_ONEBOT_ACTIONS)
        self.version_info: dict[str, Any] = {}

    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.api_base, timeout=self.timeout, headers=self._headers())
        return self._client

    async def call_api(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_base:
            raise AdapterError("未配置 OneBot HTTP API 地址（api_base）")
        client = await self._get_client()
        try:
            response = await client.post(f"/{action}", json=params or {})
        except httpx.HTTPError as exc:
            raise AdapterError(f"调用 OneBot API 失败：{action} -> {exc}") from exc
        if response.status_code >= 400:
            raise AdapterError(f"OneBot API {action} 返回 HTTP {response.status_code}")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise AdapterError(f"OneBot API {action} 返回非 JSON 数据") from exc
        retcode = data.get("retcode", 0)
        if retcode not in (0, 1, None):
            if retcode in (1404, 200):
                # 协议端明确表示不支持该动作：动态降级能力，避免假装成功
                self._supported.discard(action)
                raise AdapterError(f"协议端不支持该操作（retcode={retcode}）：{action}")
            raise AdapterError(f"OneBot API {action} 失败：{data.get('message') or data.get('wording') or retcode}")
        return data

    # ------------------------------------------------------------------
    async def connect(self) -> LoginInfo:
        if not self.api_base:
            raise AdapterError("OneBot 适配器必须配置 HTTP API 地址")
        try:
            version = await self.call_api("get_version_info")
            self.version_info = version.get("data") or {}
        except AdapterError:
            self.version_info = {}
        info = await self.get_login_info()
        if self.connection_mode == "ws_client":
            await self._connect_ws()
        self._connected = True
        return info

    async def _connect_ws(self) -> None:
        if not self.ws_url:
            raise AdapterError("ws_client 模式必须配置 WebSocket 地址")
        try:
            import inspect
            import websockets
        except ImportError as exc:  # pragma: no cover
            raise AdapterError("缺少 websockets 依赖") from exc
        try:
            # websockets >= 13 将 extra_headers 更名为 additional_headers，
            # 旧参数名在新版会被透传到 asyncio.create_connection 导致崩溃。
            # 这里按实际签名自适应，避免版本波动再次踩坑。
            conn_params = inspect.signature(websockets.connect).parameters
            header_key = (
                "additional_headers" if "additional_headers" in conn_params else "extra_headers"
            )
            header_val = (
                {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
            )
            self._ws = await websockets.connect(
                self.ws_url,
                **{header_key: header_val},
                ping_interval=30,
                ping_timeout=30,
                max_size=8 * 1024 * 1024,
            )
        except Exception as exc:
            raise AdapterError(f"连接 OneBot WebSocket 失败：{exc}") from exc
        self._listener_task = asyncio.create_task(self._ws_reader())

    async def _ws_reader(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    payload = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                event = self.parse_event(payload)
                if event:
                    await self._queue.put(event)
        except Exception as exc:  # 连接断开
            logger.warning("OneBot WebSocket 断开: %s", exc)
        finally:
            self._connected = False
            await self._queue.put(AdapterEvent(post_type="__disconnected__"))

    async def feed_event(self, payload: dict[str, Any]) -> None:
        """反向 WebSocket / webhook 注入事件。"""
        event = self.parse_event(payload)
        if event:
            await self._queue.put(event)

    @staticmethod
    def parse_event(payload: dict[str, Any]) -> AdapterEvent | None:
        if payload.get("post_type") == "meta_event":
            return AdapterEvent(
                post_type="meta_event",
                sub_type=payload.get("meta_event_type"),
                self_id=payload.get("self_id"),
                raw=payload,
            )
        if payload.get("post_type") != "message":
            post_type = payload.get("post_type", "unknown")
            sub_type = payload.get("sub_type") or payload.get("notice_type")
            if post_type == "request":
                # request_type 是申请类别（group/friend），不是 add/invite 子类型。
                # 缺少 sub_type 时保留 None，让申请业务层按 OneBot 默认值处理。
                sub_type = payload.get("sub_type")
            return AdapterEvent(
                post_type=post_type,
                sub_type=sub_type,
                self_id=payload.get("self_id"),
                group_id=payload.get("group_id"),
                user_id=payload.get("user_id"),
                raw=payload,
            )
        return AdapterEvent(
            post_type="message",
            message_type=payload.get("message_type"),
            sub_type=payload.get("sub_type"),
            self_id=payload.get("self_id"),
            group_id=payload.get("group_id"),
            user_id=payload.get("user_id"),
            message_id=payload.get("message_id"),
            raw_message=payload.get("raw_message") or "",
            sender=payload.get("sender") or {},
            raw=payload,
        )

    async def disconnect(self) -> None:
        self._connected = False
        if self._listener_task:
            self._listener_task.cancel()
            self._listener_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def listen(self) -> AsyncIterator[AdapterEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if event.post_type == "__disconnected__":
                return

    # ------------------------------------------------------------------
    async def get_login_info(self) -> LoginInfo:
        data = await self.call_api("get_login_info")
        payload = data.get("data") or {}
        return LoginInfo(
            self_id=int(payload.get("user_id") or 0),
            nickname=payload.get("nickname") or "",
            avatar_url=f"https://q1.qlogo.cn/g?b=qq&nk={payload.get('user_id')}&s=640" if payload.get("user_id") else "",
            raw=payload,
        )

    async def get_friend_list(self) -> list[dict[str, Any]]:
        return list((await self.call_api("get_friend_list")).get("data") or [])

    async def get_group_list(self) -> list[dict[str, Any]]:
        return list((await self.call_api("get_group_list")).get("data") or [])

    async def get_group_info(self, group_id: int) -> dict[str, Any]:
        return dict((await self.call_api("get_group_info", {"group_id": group_id})).get("data") or {})

    async def get_group_member_list(self, group_id: int) -> list[dict[str, Any]]:
        return list((await self.call_api("get_group_member_list", {"group_id": group_id})).get("data") or [])

    async def send_private_message(self, user_id: int, message: str) -> dict[str, Any]:
        return await self.call_api("send_private_msg", {"user_id": user_id, "message": message})

    async def send_group_message(self, group_id: int, message: str) -> dict[str, Any]:
        return await self.call_api("send_group_msg", {"group_id": group_id, "message": message})

    async def set_group_ban(self, group_id: int, user_id: int, duration: int = 600) -> dict[str, Any]:
        return await self.call_api("set_group_ban", {"group_id": group_id, "user_id": user_id, "duration": duration})

    async def set_group_whole_ban(self, group_id: int, enable: bool) -> dict[str, Any]:
        return await self.call_api("set_group_whole_ban", {"group_id": group_id, "enable": enable})

    async def set_group_kick(self, group_id: int, user_id: int, reject_add_request: bool = False) -> dict[str, Any]:
        return await self.call_api(
            "set_group_kick", {"group_id": group_id, "user_id": user_id, "reject_add_request": reject_add_request}
        )

    async def set_group_card(self, group_id: int, user_id: int, card: str) -> dict[str, Any]:
        return await self.call_api("set_group_card", {"group_id": group_id, "user_id": user_id, "card": card})

    async def set_group_name(self, group_id: int, name: str) -> dict[str, Any]:
        return await self.call_api("set_group_name", {"group_id": group_id, "group_name": name})

    async def set_group_announce(self, group_id: int, content: str) -> dict[str, Any]:
        # NapCat / go-cqhttp 常见扩展；部分实现不支持，调用失败会明确报错
        return await self.call_api("_send_group_notice", {"group_id": group_id, "content": content})

    async def set_group_admin(self, group_id: int, user_id: int, enable: bool) -> dict[str, Any]:
        return await self.call_api("set_group_admin", {"group_id": group_id, "user_id": user_id, "enable": enable})

    async def delete_msg(self, message_id: int) -> dict[str, Any]:
        return await self.call_api("delete_msg", {"message_id": message_id})

    async def set_group_add_request(
        self, flag: str, sub_type: str, approve: bool, reason: str = ""
    ) -> dict[str, Any]:
        return await self.call_api(
            "set_group_add_request",
            {"flag": flag, "sub_type": sub_type, "approve": approve, "reason": reason},
        )

    async def set_friend_add_request(self, flag: str, approve: bool, remark: str = "") -> dict[str, Any]:
        return await self.call_api(
            "set_friend_add_request", {"flag": flag, "approve": approve, "remark": remark}
        )
