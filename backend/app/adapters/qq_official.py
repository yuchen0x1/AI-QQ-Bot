"""QQ 官方机器人开放平台适配器（bot.qq.com / OpenAPI v2）。

与 OneBot v11 的本质区别，全部收敛在本文件内：

1. 登录方式：不再扫码登录个人 QQ 号，改用开放平台 AppID + AppSecret 换取
   AppAccessToken，因此不存在「模拟客户端登录」导致的风控问题。
2. 连接：支持平台两种回调方式。WebSocket 模式主动连接 Gateway，发送 Identify
   鉴权，维持应用层心跳，支持 Resume / Reconnect / Invalid Session；Webhook
   模式不建长连接，由 api/qqbot_webhook.py 验签后把事件 feed 进同一事件队列。
3. 身份：平台只给字符串 OpenID（group/user/member），通过 qq_identity 服务
   映射成稳定的整数 ID，让上层业务继续使用整数 QQ 号 / 群号。
4. 消息：只推送「群内 @机器人」和「单聊」消息；回复优先复用事件 msg_id 走
   被动消息（5 分钟、群 5 次 / 单聊 4 次），否则按配置决定是否走主动消息。
5. 能力：官方平台不提供禁言 / 踢人 / 改群名 / 审批申请 / 全量群成员等接口，
   这些动作通过 capabilities() 明确标记为不支持，绝不假装成功。

官方文档：
- https://bot.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/api-use.html
- https://bot.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html
- https://bot.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/reference.html
- https://bot.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import platform
import re
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.adapters.base import AdapterError, AdapterEvent, LoginInfo, QQAdapter
from app.core.config import settings
from app.services import qq_identity

logger = logging.getLogger("qbot.adapter.qq_official")

URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


def sanitize_official_text(text: str) -> str:
    """官方机器人普通文本消息（msg_type=0）不允许包含 http:// 或 https:// 协议头。

    若直接发送会触发平台 40054010 拒绝。本函数将链接规整为文本展示，如：
    https://github.com/foo -> [链接] github.com/foo，避免整条消息被拦截。
    """
    if not text:
        return ""

    def _replace_url(match: re.Match) -> str:
        url = match.group(0)
        # 去掉协议头
        cleaned = re.sub(r"^https?://", "", url, flags=re.I)
        return f"[链接] {cleaned}"

    return URL_PATTERN.sub(_replace_url, text)

# ---- Gateway OpCode ----
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# ---- Intents（官方事件订阅位） ----
INTENT_GUILD_MESSAGES = 1 << 9
INTENT_DIRECT_MESSAGE = 1 << 12
INTENT_GROUP_AND_C2C = 1 << 25
INTENT_INTERACTION = 1 << 26
INTENT_MESSAGE_AUDIT = 1 << 27
INTENT_FORUMS_EVENT = 1 << 28
INTENT_AUDIO_ACTION = 1 << 29
INTENT_PUBLIC_GUILD_MESSAGES = 1 << 30
DEFAULT_INTENTS = INTENT_GROUP_AND_C2C

MESSAGE_EVENTS = {"GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE"}
ROBOT_GROUP_EVENTS = {"GROUP_ADD_ROBOT", "GROUP_DEL_ROBOT"}

# 被动回复窗口：官方声称 5 分钟有效，保守取 280 秒避免边界失败。
PASSIVE_TTL_SECONDS = 280.0
MIN_HEARTBEAT_INTERVAL_SECONDS = 5.0
PASSIVE_GROUP_MAX = 5
PASSIVE_USER_MAX = 4
# msg_id 过期 / 次数超限时，若允许主动消息则自动降级重发一次。
PASSIVE_EXPIRED_CODES = {304103, 304026, 304027, 40034005, 40034128, 40034024}

ERROR_HINTS: dict[int, str] = {
    11241: "请求缺少 Token，请检查 AppSecret 配置",
    11243: "Token 校验未通过，请核对 AppID / AppSecret",
    11251: "AppID 无法识别，请核对开放平台里的 BotAppID",
    11253: "该机器人未获得此接口权限，需在开放平台申请",
    11265: "机器人已被封禁",
    304018: "机器人未连接 Gateway，请先启动账号",
    304061: "消息内容无效",
    40034005: "被动回复 msg_id 已过期（需在收到消息 5 分钟内回复）",
    40034006: "消息内容违规",
    40034024: "msg_id 无效或不属于当前机器人",
    40034100: "主动消息触发频控（Bot 60/30 QPM、单关系 20 QPM、每群每天 1000 条）",
    40034101: "机器人不是群成员，请先把机器人拉进群",
    40034105: "无主动消息权限：请确认机器人已上线、已通过审核，并在手机 QQ 机器人资料页开启主动消息",
    40034128: "被动回复时间或次数超限（群 5 次 / 单聊 4 次）",
    40054002: "机器人被禁言",
    40054003: "机器人不是群成员",
    40054005: "消息被去重，请检查 msg_seq 是否递增",
    40054007: "消息长度超限，请缩短内容",
    40054010: "消息中不允许包含 URL",
    40054013: "用户已拒收消息",
    40054016: "机器人已下线",
    40054018: "消息过长或异常",
}


class QQOfficialApiError(AdapterError):
    """携带平台 err_code，便于上层做针对性降级。"""

    def __init__(self, code: int, message: str, trace_id: str | None = None) -> None:
        self.code = code
        self.message = message
        self.trace_id = trace_id
        text = f"QQ 官方接口返回错误 {code}：{message}"
        if code in ERROR_HINTS:
            text += f"（{ERROR_HINTS[code]}）"
        if trace_id:
            text += f" [trace_id={trace_id}]"
        super().__init__(text)


@dataclass
class _ReplyWindow:
    """一条入站消息可用的被动回复额度。"""

    msg_id: str
    event_id: str | None
    created_at: float
    max_uses: int
    seq: int = 0
    used: int = 0

    def take(self) -> dict[str, Any] | None:
        if time.monotonic() - self.created_at > PASSIVE_TTL_SECONDS or self.used >= self.max_uses:
            return None
        self.used += 1
        self.seq += 1
        return {"msg_id": self.msg_id, "msg_seq": self.seq}


class QQOfficialAdapter(QQAdapter):
    """QQ 官方机器人 v2 适配器。"""

    protocol = "qq_official"

    def __init__(
        self,
        *,
        account_db_id: int,
        app_id: str,
        app_secret: str,
        sandbox: bool = False,
        intents: int = DEFAULT_INTENTS,
        allow_proactive: bool = True,
        callback_mode: str = "websocket",
        bot_openid: str = "",
        nickname: str = "",
        api_base: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        super().__init__()
        self.account_db_id = account_db_id
        self.app_id = (app_id or "").strip()
        self.app_secret = app_secret or ""
        self.sandbox = bool(sandbox)
        self.intents = int(intents or DEFAULT_INTENTS)
        self.allow_proactive = bool(allow_proactive)
        self.callback_mode = "webhook" if callback_mode == "webhook" else "websocket"
        self._display_name = nickname or ""
        self.api_base = (
            (api_base or "").strip()
            or (settings.qqbot_sandbox_openapi_base if self.sandbox else settings.qqbot_openapi_base)
        ).rstrip("/")
        self.timeout = timeout

        # 官方平台只保证消息收发与登录态；群管理、申请审批、全量资料查询均不支持。
        self._supported = {"get_login_info", "send_private_message", "send_group_message"}

        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

        self._ws: Any = None
        self._reader_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._queue: asyncio.Queue[AdapterEvent] = asyncio.Queue(maxsize=1000)
        self._connected = False
        self._ready_event: asyncio.Event | None = None
        self._ready_error: str | None = None

        self._session_id: str | None = None
        self._seq: int | None = None
        self._heartbeat_interval = 45.0
        self._heartbeat_acked = True
        self._login_info: LoginInfo | None = None
        self._bot_openid = bot_openid or ""
        self._self_id = self._app_id_to_int()
        self._last_webhook_heartbeat = 0.0
        self._reply_windows: dict[tuple[str, int], _ReplyWindow] = {}
        self._sent_messages: dict[int, tuple[str, str, str]] = {}
        self._id_cache: dict[tuple[str, str, str], int] = {}
        self._openid_cache: dict[tuple[str, int], str] = {}
        self._seen_events: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._closing = False

    @property
    def bot_openid(self) -> str:
        return self._bot_openid

    @property
    def gateway_session_id(self) -> str | None:
        return self._session_id

    @property
    def is_webhook(self) -> bool:
        return self.callback_mode == "webhook"

    def _app_id_to_int(self) -> int:
        if self.app_id.isdigit():
            return int(self.app_id) & 0x7FFFFFFFFFFFFFFF
        return qq_identity.stable_int(self.app_id or "qq-official")

    # ------------------------------------------------------------------
    # Token / REST
    # ------------------------------------------------------------------
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.api_base, timeout=self.timeout)
        return self._client

    async def _ensure_token(self, *, force: bool = False) -> str:
        now = time.monotonic()
        if not force and self._access_token and now < self._token_expires_at - 90:
            return self._access_token
        async with self._token_lock:
            now = time.monotonic()
            if not force and self._access_token and now < self._token_expires_at - 90:
                return self._access_token
            if not self.app_id or not self.app_secret:
                raise AdapterError("未配置 QQ 官方机器人 AppID / AppSecret")
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        settings.qqbot_token_url,
                        json={"appId": self.app_id, "clientSecret": self.app_secret},
                        headers={"Content-Type": "application/json"},
                    )
            except httpx.HTTPError as exc:
                raise AdapterError(f"获取 QQ 官方 AccessToken 失败：{exc}") from exc
            if response.status_code in (401, 403):
                raise AdapterError("AppID 或 AppSecret 无效，请核对 QQ 开放平台「开发设置」中的凭据")
            try:
                data = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise AdapterError("获取 AccessToken 时平台返回了非 JSON 数据") from exc
            if not isinstance(data, dict) or not data.get("access_token"):
                raise AdapterError(
                    f"获取 AccessToken 失败：{data.get('message') or data.get('err_code') or response.status_code}"
                )
            try:
                expires = max(60, int(data.get("expires_in") or 7200))
            except (TypeError, ValueError):
                expires = 7200
            self._access_token = str(data["access_token"])
            self._token_expires_at = time.monotonic() + expires
            return self._access_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        token = await self._ensure_token()
        headers = {
            "Authorization": f"QQBot {token}",
            "X-Union-Appid": self.app_id,
            "Content-Type": "application/json; charset=utf-8",
        }
        client = await self._get_client()
        try:
            response = await client.request(method, path, headers=headers, json=json_body)
        except httpx.HTTPError as exc:
            raise AdapterError(f"调用 QQ 官方 OpenAPI 失败：{method} {path} -> {exc}") from exc
        if response.status_code == 401 and retry_auth:
            await self._ensure_token(force=True)
            return await self._request(method, path, json_body=json_body, retry_auth=False)
        if response.status_code == 204:
            return {}
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise AdapterError(
                f"QQ 官方 OpenAPI {path} 返回非 JSON 数据（HTTP {response.status_code}）"
            ) from exc
        if not isinstance(data, dict):
            data = {"data": data}
        code = data.get("err_code", data.get("code", data.get("retcode")))
        try:
            code_int = int(code) if code is not None else 0
        except (TypeError, ValueError):
            code_int = 0
        if response.status_code >= 400 or code_int not in (0,):
            raise QQOfficialApiError(
                code_int or response.status_code,
                str(data.get("message") or data.get("msg") or response.reason_phrase or "未知错误"),
                str(data.get("trace_id") or response.headers.get("X-Tps-trace-ID") or "") or None,
            )
        return data

    async def probe(self) -> dict[str, Any]:
        """只验证凭据（WebSocket 模式额外探测网关），不建立长连接。"""
        await self._ensure_token(force=True)
        gateway: str | None = None
        if not self.is_webhook:
            data = await self._request("GET", "/gateway")
            gateway = data.get("url")
            if not gateway:
                raise AdapterError(
                    "平台未返回 WebSocket 网关地址，请检查机器人是否已选择 WebSocket 回调方式"
                )
        return {
            "app_id": self.app_id,
            "sandbox": self.sandbox,
            "gateway": gateway,
            "callback_mode": self.callback_mode,
            "intents": self.intents,
            "api_base": self.api_base,
        }

    # ------------------------------------------------------------------
    # OpenID 映射
    # ------------------------------------------------------------------
    async def _resolve(
        self, kind: str, openid: str, *, scope: str = "", display_name: str | None = None
    ) -> int:
        if not openid:
            raise AdapterError(f"官方事件缺少 {kind} OpenID")
        key = (kind, scope, openid)
        cached = self._id_cache.get(key)
        if cached is not None:
            return cached
        numeric = await qq_identity.resolve(
            self.account_db_id, kind, openid, scope=scope, display_name=display_name
        )
        self._id_cache[key] = numeric
        self._openid_cache[(kind, numeric)] = openid
        return numeric

    async def _lookup(self, kind: str, numeric_id: int) -> str | None:
        cached = self._openid_cache.get((kind, numeric_id))
        if cached:
            return cached
        openid = await qq_identity.get_openid(self.account_db_id, kind, numeric_id)
        if openid:
            self._openid_cache[(kind, numeric_id)] = openid
        return openid

    def _mark_seen(self, key: str) -> bool:
        """官方说明同一 msg_id 可能重复推送，结合 msg_idx 做去重。"""
        if not key:
            return True
        if key in self._seen_events:
            return False
        self._seen_events.add(key)
        self._seen_order.append(key)
        if len(self._seen_order) > 2000:
            oldest = self._seen_order.popleft()
            self._seen_events.discard(oldest)
        return True

    # ------------------------------------------------------------------
    # Gateway 生命周期
    # ------------------------------------------------------------------
    async def _connect_webhook(self) -> LoginInfo:
        """Webhook 模式没有长连接：本地就绪即可，事件由回调端点验签后注入。

        这里刻意不发起任何网络请求，避免「回调地址尚未配置 / 平台临时不可达」
        导致机器人无法启动；AccessToken 会在首次调用发消息接口时按需获取。
        """
        await self._close_ws()
        self._closing = False
        self._drain_queue()
        self._login_info = LoginInfo(
            self_id=self._self_id,
            nickname=self._display_name or f"QQ 机器人 {self.app_id}",
            avatar_url="",
            raw={
                "app_id": self.app_id,
                "bot_openid": self._bot_openid,
                "callback_mode": "webhook",
            },
        )
        self._connected = True
        return self._login_info

    async def connect(self) -> LoginInfo:
        if self.is_webhook:
            return await self._connect_webhook()
        await self._close_ws()
        self._closing = False
        self._drain_queue()
        token = await self._ensure_token()
        gateway_data = await self._request("GET", "/gateway")
        gateway_url = gateway_data.get("url")
        if not gateway_url:
            raise AdapterError("平台未返回 WebSocket 网关地址，请在开放平台确认已选择 WebSocket 回调方式")

        self._ready_event = asyncio.Event()
        self._ready_error = None
        self._heartbeat_acked = True
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover
            raise AdapterError("缺少 websockets 依赖，请安装 requirements.txt") from exc
        try:
            conn_params = inspect.signature(websockets.connect).parameters
            header_key = "additional_headers" if "additional_headers" in conn_params else "extra_headers"
            self._ws = await websockets.connect(
                gateway_url,
                **{
                    header_key: {
                        "Authorization": f"QQBot {token}",
                        "X-Union-Appid": self.app_id,
                    }
                },
                # 官方网关使用应用层 op=1 心跳，关闭 WebSocket 协议层 ping 避免重复。
                ping_interval=None,
                ping_timeout=None,
                max_size=8 * 1024 * 1024,
                open_timeout=15,
            )
        except Exception as exc:
            raise AdapterError(
                f"连接 QQ 官方机器人网关失败：{exc}。请检查出站网络、IP 白名单与平台回调方式设置"
            ) from exc

        self._reader_task = asyncio.create_task(self._reader(), name=f"qqbot-reader-{self.app_id}")
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=20)
        except asyncio.TimeoutError as exc:
            await self._close_ws()
            raise AdapterError(
                "连接官方网关后 20 秒内未完成鉴权：请检查 AppID/AppSecret、Intents 事件权限与回调方式"
            ) from exc
        if self._ready_error:
            await self._close_ws()
            raise AdapterError(self._ready_error)
        self._connected = True
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name=f"qqbot-heartbeat-{self.app_id}"
        )
        assert self._login_info is not None
        return self._login_info

    async def _send(self, op: int, payload: Any) -> None:
        if self._ws is None:
            return
        async with self._send_lock:
            if self._ws is None:
                return
            await self._ws.send(json.dumps({"op": op, "d": payload}, ensure_ascii=False))

    async def _identify_or_resume(self) -> None:
        token = await self._ensure_token()
        if self._session_id and self._seq is not None:
            await self._send(
                OP_RESUME,
                {"token": f"QQBot {token}", "session_id": self._session_id, "seq": self._seq},
            )
            return
        await self._send(
            OP_IDENTIFY,
            {
                "token": f"QQBot {token}",
                "intents": self.intents,
                "shard": [0, 1],
                "properties": {
                    "$os": platform.system().lower(),
                    "$browser": "qbot-platform",
                    "$device": "qbot-platform",
                },
            },
        )

    async def _handle_payload(self, payload: dict[str, Any]) -> None:
        op = payload.get("op")
        seq = payload.get("s")
        if isinstance(seq, int):
            self._seq = seq
        if op == OP_HELLO:
            interval = (payload.get("d") or {}).get("heartbeat_interval")
            if isinstance(interval, (int, float)) and interval > 0:
                self._heartbeat_interval = max(MIN_HEARTBEAT_INTERVAL_SECONDS, float(interval) / 1000)
            await self._identify_or_resume()
        elif op == OP_DISPATCH:
            await self._handle_dispatch(payload)
        elif op == OP_HEARTBEAT:
            await self._send(OP_HEARTBEAT, self._seq)
        elif op == OP_HEARTBEAT_ACK:
            self._heartbeat_acked = True
        elif op == OP_RECONNECT:
            logger.info("QQ 官方网关要求重连（app=%s）", self.app_id)
            if self._ws is not None:
                await self._ws.close()
        elif op == OP_INVALID_SESSION:
            self._session_id = None
            self._seq = None
            self._ready_error = (
                "官方网关拒绝鉴权（Invalid Session）：请确认 AppSecret 正确、"
                "订阅的 Intents 均已获平台授权、且回调方式选择为 WebSocket"
            )
            if self._ready_event and not self._ready_event.is_set():
                self._ready_event.set()
            if self._ws is not None:
                await self._ws.close()

    async def _handle_dispatch(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("t") or "")
        data = payload.get("d")
        if not isinstance(data, dict):
            data = {}
        event_id = payload.get("id")
        if event_type == "READY":
            self._session_id = str(data.get("session_id") or "") or None
            user = data.get("user") or {}
            self._bot_openid = str(user.get("id") or "")
            self._login_info = LoginInfo(
                self_id=self._self_id,
                nickname=str(user.get("username") or f"QQ 机器人 {self.app_id}"),
                avatar_url="",
                raw={
                    "app_id": self.app_id,
                    "bot_openid": self._bot_openid,
                    "session_id": self._session_id,
                    "ready": data,
                },
            )
            if self._ready_event:
                self._ready_event.set()
            await self._queue.put(
                AdapterEvent(
                    post_type="meta_event",
                    sub_type="lifecycle",
                    self_id=self._self_id,
                    raw={"t": "READY", "d": data},
                )
            )
            return
        if event_type == "RESUMED":
            if self._ready_event and not self._ready_event.is_set():
                self._ready_event.set()
            await self._queue.put(
                AdapterEvent(
                    post_type="meta_event",
                    sub_type="heartbeat",
                    self_id=self._self_id,
                    raw={"t": "RESUMED"},
                )
            )
            return
        event = await self._to_adapter_event(event_type, data, event_id)
        if event:
            await self._queue.put(event)

    def _drain_queue(self) -> None:
        """重连前丢弃上一轮遗留的断线事件，避免刚连上就被误判为断开。"""
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    async def _reader(self) -> None:
        ws = self._ws
        ready_event = self._ready_event
        try:
            if ws is None:
                return
            async for raw in ws:
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    await self._handle_payload(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("QQ 官方机器人 WebSocket 断开（app=%s）：%s", self.app_id, exc)
        finally:
            self._connected = False
            if ready_event and not ready_event.is_set():
                self._ready_error = self._ready_error or "官方网关连接在鉴权完成前已关闭"
                ready_event.set()
            if not self._closing:
                await self._queue.put(AdapterEvent(post_type="__disconnected__"))

    async def _heartbeat_loop(self) -> None:
        try:
            while self._connected:
                await asyncio.sleep(self._heartbeat_interval)
                if not self._connected:
                    return
                if not self._heartbeat_acked:
                    logger.warning("官方网关连续未响应心跳 ACK，主动重连（app=%s）", self.app_id)
                    if self._ws is not None:
                        await self._ws.close()
                    return
                self._heartbeat_acked = False
                await self._send(OP_HEARTBEAT, self._seq)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("心跳任务异常（app=%s）：%s", self.app_id, exc)

    async def _close_ws(self) -> None:
        self._connected = False
        self._closing = True
        current = asyncio.current_task()
        for task in (self._heartbeat_task, self._reader_task):
            if task and not task.done() and task is not current:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._heartbeat_task = None
        self._reader_task = None
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        self._drain_queue()

    async def disconnect(self) -> None:
        self._connected = False
        await self._close_ws()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._reply_windows.clear()

    @property
    def connected(self) -> bool:
        return self._connected

    async def listen(self) -> AsyncIterator[AdapterEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if event.post_type == "__disconnected__":
                return

    async def feed_event(self, payload: dict[str, Any]) -> None:
        """供 Webhook 回调 / 单元测试注入平台 Payload。"""
        if not isinstance(payload, dict):
            return
        if self.is_webhook:
            # Webhook 只推送 op=0 Dispatch；op=13 验证由 HTTP 端点直接处理，
            # 其余网关 OpCode（Hello / 心跳 / 重连）不应触发 Identify 或写 WebSocket。
            if payload.get("op") != OP_DISPATCH:
                return
            await self._handle_dispatch(payload)
            # Webhook 没有网关心跳，用低频 meta_event 让运行管理器刷新连接时间。
            now = time.monotonic()
            if now - self._last_webhook_heartbeat >= 30.0:
                self._last_webhook_heartbeat = now
                await self._queue.put(
                    AdapterEvent(
                        post_type="meta_event",
                        sub_type="heartbeat",
                        self_id=self._self_id,
                        raw={"t": "WEBHOOK_EVENT"},
                    )
                )
            return
        await self._handle_payload(payload)

    # ------------------------------------------------------------------
    # 事件 → AdapterEvent
    # ------------------------------------------------------------------
    @staticmethod
    def _scene_ext(data: dict[str, Any]) -> dict[str, str]:
        scene = data.get("message_scene") or {}
        result: dict[str, str] = {}
        for item in scene.get("ext") or []:
            if isinstance(item, str) and "=" in item:
                key, _, value = item.partition("=")
                result[key] = value
        return result

    async def _to_adapter_event(
        self, event_type: str, data: dict[str, Any], event_id: Any
    ) -> AdapterEvent | None:
        if event_type in MESSAGE_EVENTS:
            ext = self._scene_ext(data)
            dedup_key = f"{event_type}:{data.get('id') or event_id}:{ext.get('msg_idx', '')}"
            if not self._mark_seen(dedup_key):
                return None
            return await self._message_event(event_type, data, event_id)
        if event_type in ROBOT_GROUP_EVENTS:
            group_openid = str(data.get("group_openid") or "")
            if not group_openid:
                return None
            group_id = await self._resolve(
                "group", group_openid, display_name=data.get("group_name")
            )
            author = data.get("author") or {}
            user_id = 0
            member_openid = str(author.get("member_openid") or author.get("id") or "")
            if member_openid:
                user_id = await self._resolve(
                    "member", member_openid, scope=group_openid, display_name=author.get("username")
                )
            return AdapterEvent(
                post_type="notice",
                sub_type="robot_added" if event_type == "GROUP_ADD_ROBOT" else "robot_removed",
                self_id=self._self_id,
                group_id=group_id,
                user_id=user_id or None,
                raw={"t": event_type, "event_id": event_id, **data},
            )
        # 好友 / 消息开关变化等事件没有对应审批动作，保留原始事件供日志排查。
        return AdapterEvent(
            post_type="notice",
            sub_type=event_type.lower(),
            self_id=self._self_id,
            raw={"t": event_type, "event_id": event_id, **data},
        )

    async def _message_event(
        self, event_type: str, data: dict[str, Any], event_id: Any
    ) -> AdapterEvent | None:
        content = str(data.get("content") or "").strip()
        raw_id = str(data.get("id") or "")
        author = data.get("author") or {}
        is_group = event_type == "GROUP_AT_MESSAGE_CREATE"
        segments: list[dict[str, Any]]

        if is_group:
            group_openid = str(data.get("group_openid") or "")
            if not group_openid:
                return None
            group_id = await self._resolve("group", group_openid)
            member_openid = str(author.get("member_openid") or author.get("id") or "")
            user_id = (
                await self._resolve(
                    "member", member_openid, scope=group_openid, display_name=author.get("username")
                )
                if member_openid
                else 0
            )
            message_type = "group"
            sender = {
                "user_id": user_id,
                "nickname": str(author.get("username") or ""),
                "card": str(author.get("username") or ""),
                "role": str(author.get("member_role") or "member"),
            }
            # 官方群事件本身就是「@机器人」，构造 CQ at 段让 is_at_me / _clean_text 正常工作。
            segments = [
                {"type": "at", "data": {"qq": self._self_id}},
                {"type": "text", "data": {"text": content}},
            ]
            reply_key = ("group", group_id)
            max_uses = PASSIVE_GROUP_MAX
        else:
            user_openid = str(author.get("user_openid") or author.get("id") or "")
            if not user_openid:
                return None
            user_id = await self._resolve("user", user_openid, display_name=author.get("username"))
            group_id = None
            message_type = "private"
            sender = {
                "user_id": user_id,
                "nickname": str(author.get("username") or ""),
                "card": "",
                "role": "member",
            }
            segments = [{"type": "text", "data": {"text": content}}]
            reply_key = ("user", user_id)
            max_uses = PASSIVE_USER_MAX

        if raw_id:
            self._reply_windows[reply_key] = _ReplyWindow(
                msg_id=raw_id,
                event_id=str(event_id) if event_id else None,
                created_at=time.monotonic(),
                max_uses=max_uses,
            )
        raw = {**data, "t": event_type, "event_id": event_id, "message": segments}
        return AdapterEvent(
            post_type="message",
            message_type=message_type,
            sub_type="normal",
            self_id=self._self_id,
            group_id=group_id,
            user_id=user_id or None,
            message_id=qq_identity.stable_int(raw_id) if raw_id else None,
            raw_message=content,
            sender=sender,
            raw=raw,
        )

    # ------------------------------------------------------------------
    # 查询（官方无全量列表接口，仅返回平台已感知到的实体）
    # ------------------------------------------------------------------
    async def get_login_info(self) -> LoginInfo:
        if self._login_info is None:
            raise AdapterError("机器人尚未完成 READY 鉴权，无法获取登录信息")
        return self._login_info

    async def get_friend_list(self) -> list[dict[str, Any]]:
        rows = await qq_identity.list_identities(self.account_db_id, "user")
        return [
            {"user_id": row["id"], "nickname": row["display_name"] or str(row["id"]), "remark": ""}
            for row in rows
        ]

    async def get_group_list(self) -> list[dict[str, Any]]:
        rows = await qq_identity.list_identities(self.account_db_id, "group")
        return [
            {
                "group_id": row["id"],
                "group_name": row["display_name"] or f"官方群 {row['id']}",
                "member_count": 0,
                "max_member_count": 0,
            }
            for row in rows
        ]

    async def get_group_info(self, group_id: int) -> dict[str, Any]:
        openid = await self._lookup("group", group_id)
        if not openid:
            raise AdapterError("未找到该群的 OpenID：官方机器人需先被拉入群或收到过群内 @ 消息")
        rows = await qq_identity.list_identities(self.account_db_id, "group")
        name = next((row["display_name"] for row in rows if row["openid"] == openid), "")
        return {
            "group_id": group_id,
            "group_openid": openid,
            "group_name": name or f"官方群 {group_id}",
            "member_count": 0,
            "max_member_count": 0,
        }

    async def get_group_member_list(self, group_id: int) -> list[dict[str, Any]]:
        openid = await self._lookup("group", group_id)
        if not openid:
            return []
        rows = await qq_identity.list_identities(self.account_db_id, "member", scope=openid)
        return [
            {
                "user_id": row["id"],
                "nickname": row["display_name"] or str(row["id"]),
                "card": row["display_name"] or "",
                "role": "member",
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # 消息发送
    # ------------------------------------------------------------------
    def _format_send_result(
        self, data: dict[str, Any], kind: str, target_id: int, target_openid: str
    ) -> dict[str, Any]:
        raw_id = str(data.get("id") or "")
        numeric = qq_identity.stable_int(raw_id) if raw_id else None
        if numeric is not None:
            self._sent_messages[numeric] = (kind, target_openid, raw_id)
            if len(self._sent_messages) > 1000:
                self._sent_messages.pop(next(iter(self._sent_messages)))
        return {
            "status": "ok",
            "retcode": 0,
            "data": {"message_id": numeric, "id": raw_id, "timestamp": data.get("timestamp")},
            "raw": data,
        }

    async def _send_message(
        self,
        kind: str,
        target_id: int,
        message: str,
        *,
        markdown: dict[str, Any] | None = None,
        keyboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        openid = await self._lookup(kind, target_id)
        if not openid:
            scope = "群" if kind == "group" else "用户"
            raise AdapterError(
                f"未找到该{scope}的 OpenID：官方机器人只能向已产生过会话的{scope}发消息，"
                "请先在群里 @ 机器人或与机器人单聊一次"
            )
        path = (
            f"/v2/groups/{quote(openid, safe='')}/messages"
            if kind == "group"
            else f"/v2/users/{quote(openid, safe='')}/messages"
        )
        body: dict[str, Any] = {}
        if markdown:
            # 官方机器人原生 Markdown 卡片消息 (msg_type=2)
            body["msg_type"] = 2
            body["markdown"] = markdown
            if keyboard:
                body["keyboard"] = keyboard
        else:
            safe_content = sanitize_official_text(message)
            body["msg_type"] = 0
            body["content"] = safe_content

        window = self._reply_windows.get((kind, target_id))
        passive = window.take() if window else None
        if passive:
            body.update(passive)
        elif not self.allow_proactive:
            raise AdapterError(
                "当前账号未启用主动消息：官方平台只允许在收到消息后 5 分钟内被动回复，"
                "如需定时推送 / GitHub 通知请在账号设置中开启「允许主动消息」并确认机器人已获得主动消息权限"
            )
        try:
            data = await self._request("POST", path, json_body=body)
        except QQOfficialApiError as exc:
            if passive and exc.code in PASSIVE_EXPIRED_CODES and self.allow_proactive:
                logger.info("被动回复已失效（err_code=%s），降级为主动消息重发", exc.code)
                body.pop("msg_id", None)
                body.pop("msg_seq", None)
                data = await self._request("POST", path, json_body=body)
            else:
                raise
        return self._format_send_result(data, kind, target_id, openid)

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        *,
        markdown: dict[str, Any] | None = None,
        keyboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._send_message("user", user_id, message, markdown=markdown, keyboard=keyboard)

    async def send_group_message(
        self,
        group_id: int,
        message: str,
        *,
        markdown: dict[str, Any] | None = None,
        keyboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._send_message("group", group_id, message, markdown=markdown, keyboard=keyboard)

    # ------------------------------------------------------------------
    # 官方平台不支持的群管理动作：明确报错，绝不假装成功
    # ------------------------------------------------------------------
    async def set_group_ban(self, group_id: int, user_id: int, duration: int = 600) -> dict[str, Any]:
        self._require("set_group_ban")
        raise NotImplementedError

    async def set_group_whole_ban(self, group_id: int, enable: bool) -> dict[str, Any]:
        self._require("set_group_whole_ban")
        raise NotImplementedError

    async def set_group_kick(self, group_id: int, user_id: int, reject_add_request: bool = False) -> dict[str, Any]:
        self._require("set_group_kick")
        raise NotImplementedError

    async def set_group_card(self, group_id: int, user_id: int, card: str) -> dict[str, Any]:
        self._require("set_group_card")
        raise NotImplementedError

    async def set_group_name(self, group_id: int, name: str) -> dict[str, Any]:
        self._require("set_group_name")
        raise NotImplementedError

    async def set_group_announce(self, group_id: int, content: str) -> dict[str, Any]:
        self._require("set_group_announce")
        raise NotImplementedError

    async def set_group_admin(self, group_id: int, user_id: int, enable: bool) -> dict[str, Any]:
        self._require("set_group_admin")
        raise NotImplementedError

    async def delete_msg(self, message_id: int) -> dict[str, Any]:
        self._require("delete_msg")
        raise NotImplementedError

    async def set_group_add_request(
        self, flag: str, sub_type: str, approve: bool, reason: str = ""
    ) -> dict[str, Any]:
        self._require("set_group_add_request")
        raise NotImplementedError

    async def set_friend_add_request(self, flag: str, approve: bool, remark: str = "") -> dict[str, Any]:
        self._require("set_friend_add_request")
        raise NotImplementedError
