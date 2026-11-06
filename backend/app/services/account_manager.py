"""多 QQ 账号运行管理器：独立运行时、事件循环、自动重连（指数退避）、状态持久化。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, QQAdapter, UnsupportedAction
from app.adapters.mock import MockAdapter
from app.adapters.onebot11 import OneBot11Adapter
from app.adapters.qq_official import QQOfficialAdapter
from app.core.config import settings
from app.core.events import publish_event
from app.core.security import decrypt_secret
from app.db.session import SessionLocal
from app.models import Account, AccountConnection, Group, GroupMember, GroupSettings
from app.schemas.account import DEFAULT_OFFICIAL_INTENTS
from app.services.logs import write_log

logger = logging.getLogger("qbot.accounts")

_FRIENDLY_NETWORK_KEYWORDS = (
    "http 502",
    "http 503",
    "http 504",
    "http 400",
    "connection refused",
    "connect_tcp",
    "getaddrinfo",
    "timed out",
    "timeout",
    "远程主机强迫关闭",
    "连接被拒",
    "目标计算机积极拒绝",
)


def _friendly_connection_error(exc: Exception, protocol: str = "onebot11") -> str:
    """把底层连接报错翻译成用户能看懂的提示，避免满屏晦涩堆栈。"""
    raw = f"{type(exc).__name__}: {exc}"
    lowered = str(exc).lower()
    if protocol == "qq_official":
        # 官方适配器抛出的错误本身已经带平台错误码与排查建议。
        if any(k in lowered for k in _FRIENDLY_NETWORK_KEYWORDS):
            return (
                f"无法连接 QQ 官方机器人平台（{raw}）。请检查：1) 服务器能否访问 "
                "bots.qq.com / api.bot.qq.com；2) 开放平台的回调方式与账号设置是否一致"
                "（WebSocket / Webhook）；3) IP 白名单是否包含本机公网出口 IP；"
                "4) Webhook 模式下回调地址是否公网 HTTPS 可达"
            )
        return raw
    if any(k in lowered for k in ("http 502", "http 503", "http 504")):
        return f"协议端无响应（{raw}）。通常是 NapCat/OneBot 协议端未启动或正在重启，请先启动协议端再观察"
    if any(k in lowered for k in _FRIENDLY_NETWORK_KEYWORDS):
        return (
            f"无法连接协议端（{raw}）。请检查：1) NapCat/OneBot 协议端是否已启动；"
            "2) HTTP API / WebSocket 地址是否填写正确；3) 防火墙是否放行"
        )
    if "token" in lowered or "unauthorized" in lowered or "403" in lowered or "401" in lowered:
        return f"协议端鉴权失败（{raw}）。请核对账号的访问令牌（access token）与协议端配置一致"
    return raw


@dataclass
class RuntimeState:
    account_db_id: int
    account_uid: str
    name: str
    adapter: QQAdapter | None = None
    task: asyncio.Task | None = None
    state: str = "stopped"  # stopped/starting/online/error/stopping
    started_at: datetime | None = None
    last_error: str | None = None
    last_logged_error: str | None = None  # 去重用：相同错误只记录一次日志
    attempts: int = 0
    stop_requested: bool = False
    messages_sent: int = 0
    messages_received: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    lease_id: str | None = None
    lease_renew_task: asyncio.Task | None = None

    @property
    def online_seconds(self) -> int:
        if self.state != "online" or not self.started_at:
            return 0
        return int((datetime.now(timezone.utc) - self.started_at).total_seconds())


def build_adapter(account: Account) -> QQAdapter:
    if account.protocol == "mock":
        return MockAdapter(self_id=account.qq_number or 10000, nickname=account.nickname or account.name)
    if account.protocol == "qq_official":
        features = account.features or {}
        secret = decrypt_secret(account.app_secret_enc)
        if not account.app_id or not secret:
            raise AdapterError(
                "QQ 官方机器人缺少 AppID / AppSecret，或密钥无法解密（SECRET_KEY 变更会导致旧密文失效，请重新填写）"
            )
        return QQOfficialAdapter(
            account_db_id=account.id,
            app_id=account.app_id,
            app_secret=secret,
            sandbox=bool(features.get("official_sandbox", False)),
            intents=int(features.get("official_intents", DEFAULT_OFFICIAL_INTENTS)),
            allow_proactive=bool(features.get("official_allow_proactive", True)),
            callback_mode=(
                "webhook" if account.connection_mode == "official_webhook" else "websocket"
            ),
            bot_openid=account.bot_openid or "",
            nickname=account.nickname or account.name,
            api_base=features.get("official_api_base") or None,
        )
    return OneBot11Adapter(
        api_base=account.api_base,
        ws_url=account.ws_url,
        access_token=decrypt_secret(account.access_token_enc),
        connection_mode=account.connection_mode,
    )


class AccountManager:
    def __init__(self) -> None:
        self._runtimes: dict[int, RuntimeState] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    def all_states(self) -> list[RuntimeState]:
        return list(self._runtimes.values())

    def get(self, account_db_id: int) -> RuntimeState | None:
        return self._runtimes.get(account_db_id)

    def adapter(self, account_db_id: int) -> QQAdapter | None:
        state = self._runtimes.get(account_db_id)
        return state.adapter if state and state.state == "online" else None

    def is_online(self, account_db_id: int) -> bool:
        state = self._runtimes.get(account_db_id)
        return bool(state and state.state == "online" and state.adapter and state.adapter.connected)

    def capabilities(self, account_db_id: int) -> dict[str, bool]:
        adapter = self.adapter(account_db_id)
        return adapter.capabilities() if adapter else {}

    # ------------------------------------------------------------------
    async def start(self, account_db_id: int, *, reset_attempts: bool = True) -> RuntimeState:
        async with self._lock:
            state = self._runtimes.get(account_db_id)
            if state and state.task and not state.task.done():
                return state
            async with SessionLocal() as db:
                account = await db.get(Account, account_db_id)
                if not account:
                    raise ValueError("账号不存在")
                if not account.enabled:
                    raise ValueError("账号已被禁用，请先启用")
                # 先构建适配器再占用运行租约：凭据缺失时不会留下 45 秒的僵尸租约。
                try:
                    adapter = build_adapter(account)
                except AdapterError as exc:
                    raise ValueError(str(exc)) from exc
                lease_id = uuid.uuid4().hex
                if not await self._acquire_lease(db, account.id, lease_id):
                    raise ValueError("账号已被其它运行实例占用，请稍后重试")
                state = RuntimeState(
                    account_db_id=account.id,
                    account_uid=account.account_id,
                    name=account.name,
                    adapter=adapter,
                    state="starting",
                    lease_id=lease_id,
                )
                if reset_attempts:
                    state.attempts = 0
                self._runtimes[account_db_id] = state
                await self._set_connection(db, account.id, status="connecting", error=None, reset_reconnect=True)
                await write_log(
                    db,
                    level="INFO",
                    category="qq",
                    message=f"账号 {account.name}({account.qq_number or '未登录'}) 正在启动，协议={account.protocol}",
                    account_id=account.id,
                )
            state.task = asyncio.create_task(self._run_loop(account_db_id), name=f"account-{account_db_id}")
            state.lease_renew_task = asyncio.create_task(self._renew_lease_loop(account_db_id), name=f"lease-{account_db_id}")
            publish_event("account.state", {"account_id": account_db_id, "state": state.state})
            return state

    async def stop(self, account_db_id: int) -> RuntimeState | None:
        state = self._runtimes.get(account_db_id)
        if not state:
            return None
        state.stop_requested = True
        state.state = "stopping"
        if state.lease_renew_task and not state.lease_renew_task.done():
            state.lease_renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await state.lease_renew_task
        if state.adapter:
            with contextlib.suppress(Exception):
                await state.adapter.disconnect()
        if state.task and not state.task.done():
            state.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await state.task
        state.state = "stopped"
        state.started_at = None
        async with SessionLocal() as db:
            await self._set_connection(db, account_db_id, status="offline", error="手动停止")
            await self._release_lease(db, account_db_id, state.lease_id)
            await write_log(db, level="INFO", category="qq", message=f"账号 {state.name} 已停止", account_id=account_db_id)
        publish_event("account.state", {"account_id": account_db_id, "state": state.state})
        return state

    async def restart(self, account_db_id: int) -> RuntimeState:
        await self.stop(account_db_id)
        await asyncio.sleep(0.3)
        return await self.start(account_db_id)

    async def stop_all(self) -> None:
        for account_db_id in list(self._runtimes):
            with contextlib.suppress(Exception):
                await self.stop(account_db_id)

    async def boot_auto_start(self) -> list[int]:
        started: list[int] = []
        async with SessionLocal() as db:
            rows = await db.scalars(select(Account).where(Account.auto_start.is_(True), Account.enabled.is_(True)))
            for account in list(rows):
                try:
                    await self.start(account.id)
                    started.append(account.id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("自动启动账号 %s 失败: %s", account.name, exc)
        return started

    # ------------------------------------------------------------------
    async def _run_loop(self, account_db_id: int) -> None:
        state = self._runtimes.get(account_db_id)
        if not state or not state.adapter:
            return
        adapter = state.adapter
        while not state.stop_requested:
            async with SessionLocal() as db:
                account = await db.get(Account, account_db_id)
                if not account or not account.enabled:
                    state.state = "stopped"
                    async with SessionLocal() as release_db:
                        await self._release_lease(release_db, account_db_id, state.lease_id)
                    publish_event("account.state", {"account_id": account_db_id, "state": "stopped"})
                    return
            try:
                state.state = "starting"
                info = await adapter.connect()
                connected_at = datetime.now(timezone.utc)
                state.last_error = None
                state.last_logged_error = None
                state.attempts = 0
                async with SessionLocal() as db:
                    account = await db.get(Account, account_db_id)
                    if account:
                        account.self_id = info.self_id or account.self_id
                        account.nickname = info.nickname or account.nickname
                        account.avatar_url = info.avatar_url or account.avatar_url
                        if account.protocol == "qq_official" and isinstance(adapter, QQOfficialAdapter):
                            # 官方机器人没有 QQ 号，self_id 是 AppID 数值；只记录机器人 OpenID。
                            account.bot_openid = adapter.bot_openid or account.bot_openid
                        elif not account.qq_number and info.self_id:
                            account.qq_number = info.self_id
                        await db.commit()
                    await self._set_connection(
                        db,
                        account_db_id,
                        status="online",
                        error=None,
                        connected_at=connected_at,
                        heartbeat=connected_at,
                        reset_reconnect=True,
                    )
                    await write_log(
                        db,
                        level="INFO",
                        category="qq",
                        message=f"账号 {state.name} 登录成功，QQ={info.self_id}，昵称={info.nickname or '未知'}",
                        account_id=account_db_id,
                    )
                state.state = "online"
                state.started_at = connected_at
                publish_event("account.state", {"account_id": account_db_id, "state": "online"})
                with contextlib.suppress(Exception):
                    await self.sync_groups(account_db_id)

                from app.services.bot_engine import engine  # 延迟导入避免循环依赖

                async for event in adapter.listen():
                    if event.post_type == "__disconnected__":
                        raise AdapterError("协议端断开连接")
                    if event.post_type == "meta_event":
                        if event.sub_type in {"heartbeat", "lifecycle"}:
                            async with SessionLocal() as db:
                                await self._set_connection(db, account_db_id, heartbeat=datetime.now(timezone.utc))
                        continue
                    try:
                        async with SessionLocal() as db:
                            await engine.handle_event(db, account_db_id, adapter, event)
                        if event.post_type == "message":
                            state.messages_received += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("处理事件失败 account=%s: %s", account_db_id, exc)
                        async with SessionLocal() as db:
                            await write_log(
                                db,
                                level="ERROR",
                                category="qq",
                                message=f"事件处理异常：{type(exc).__name__}: {exc}",
                                account_id=account_db_id,
                            )
                raise AdapterError("事件流结束")
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                friendly = _friendly_connection_error(exc, getattr(adapter, "protocol", "onebot11"))
                state.last_error = friendly
                state.state = "error"
                state.started_at = None
                publish_event("account.state", {"account_id": account_db_id, "state": "error", "error": friendly[:500]})
                async with SessionLocal() as db:
                    await self._set_connection(
                        db,
                        account_db_id,
                        status="error",
                        error=friendly[:500],
                        disconnected_at=datetime.now(timezone.utc),
                    )
                    # 相同错误在持续重连期间只记录一次，避免系统日志被刷屏
                    if state.last_logged_error != friendly:
                        state.last_logged_error = friendly
                        await write_log(
                            db,
                            level="ERROR",
                            category="qq",
                            message=f"账号 {state.name} 连接异常：{friendly}",
                            account_id=account_db_id,
                        )
                with contextlib.suppress(Exception):
                    await adapter.disconnect()

                async with SessionLocal() as db:
                    account = await db.get(Account, account_db_id)
                    auto_reconnect = bool(account and account.auto_reconnect and account.enabled)
                    base = account.reconnect_base_seconds if account else 5
                    cap = account.reconnect_max_seconds if account else 300
                if not auto_reconnect or state.stop_requested:
                    state.state = "error" if not state.stop_requested else "stopped"
                    async with SessionLocal() as release_db:
                        await self._release_lease(release_db, account_db_id, state.lease_id)
                    publish_event("account.state", {"account_id": account_db_id, "state": state.state})
                    return
                state.attempts += 1
                delay = min(base * (2 ** min(state.attempts - 1, 6)), cap)
                delay += random.uniform(0, min(5, delay * 0.2))
                logger.info("账号 %s 将在 %.1fs 后重连（第 %s 次）", state.name, delay, state.attempts)
                async with SessionLocal() as db:
                    await self._set_connection(db, account_db_id, reconnect_attempts=state.attempts)
                await asyncio.sleep(delay)
        state.state = "stopped"
        state.started_at = None
        async with SessionLocal() as db:
            await self._release_lease(db, account_db_id, state.lease_id)
        publish_event("account.state", {"account_id": account_db_id, "state": "stopped"})

    async def _acquire_lease(self, db: AsyncSession, account_db_id: int, lease_id: str) -> bool:
        conn = await db.scalar(
            select(AccountConnection).where(AccountConnection.account_id == account_db_id).with_for_update()
        )
        if not conn:
            conn = AccountConnection(account_id=account_db_id)
            db.add(conn)
            await db.flush()
        now = datetime.now(timezone.utc)
        if conn.lease_id and conn.lease_expires_at:
            expires = conn.lease_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires > now:
                return False
        conn.lease_owner = settings.runtime_instance_id
        conn.lease_id = lease_id
        conn.lease_expires_at = now + timedelta(seconds=settings.account_lease_seconds)
        await db.commit()
        return True

    async def _renew_lease(self, account_db_id: int, lease_id: str | None) -> bool:
        if not lease_id:
            return False
        async with SessionLocal() as db:
            conn = await db.scalar(select(AccountConnection).where(AccountConnection.account_id == account_db_id))
            if not conn or conn.lease_id != lease_id:
                return False
            conn.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.account_lease_seconds)
            await db.commit()
            return True

    async def _renew_lease_loop(self, account_db_id: int) -> None:
        state = self._runtimes.get(account_db_id)
        while state and not state.stop_requested:
            await asyncio.sleep(max(3, settings.account_lease_renew_seconds))
            if not await self._renew_lease(account_db_id, state.lease_id):
                state.stop_requested = True
                state.state = "error"
                publish_event("account.state", {"account_id": account_db_id, "state": "error", "error": "运行租约已失效"})
                return

    async def _release_lease(self, db: AsyncSession, account_db_id: int, lease_id: str | None) -> None:
        conn = await db.scalar(select(AccountConnection).where(AccountConnection.account_id == account_db_id))
        if conn and (lease_id is None or conn.lease_id == lease_id):
            conn.lease_owner = None
            conn.lease_id = None
            conn.lease_expires_at = None
            await db.commit()

    async def _set_connection(
        self,
        db: AsyncSession,
        account_db_id: int,
        *,
        status: str | None = None,
        error: str | None | object = ...,
        connected_at: datetime | None = None,
        disconnected_at: datetime | None = None,
        heartbeat: datetime | None = None,
        reset_reconnect: bool = False,
        reconnect_attempts: int | None = None,
    ) -> None:
        conn = await db.scalar(select(AccountConnection).where(AccountConnection.account_id == account_db_id))
        if not conn:
            conn = AccountConnection(account_id=account_db_id)
            db.add(conn)
        if status:
            conn.status = status
        if error is not ...:
            conn.last_error = error  # type: ignore[assignment]
        if connected_at:
            conn.connected_at = connected_at
        if disconnected_at:
            conn.last_disconnect_at = disconnected_at
        if heartbeat:
            conn.last_heartbeat_at = heartbeat
        if reset_reconnect:
            conn.reconnect_attempts = 0
        if reconnect_attempts is not None:
            conn.reconnect_attempts = reconnect_attempts
        await db.commit()

    # ------------------------------------------------------------------
    async def sync_groups(self, account_db_id: int) -> int:
        adapter = self.adapter(account_db_id)
        if not adapter:
            raise AdapterError("账号未在线，无法同步群列表")
        groups = await adapter.get_group_list()
        async with SessionLocal() as db:
            count = 0
            for item in groups:
                number = int(item.get("group_id") or 0)
                if not number:
                    continue
                group = await db.scalar(
                    select(Group).where(Group.account_id == account_db_id, Group.group_number == number)
                )
                if not group:
                    group = Group(account_id=account_db_id, group_number=number)
                    db.add(group)
                    await db.flush()
                    db.add(GroupSettings(group_id=group.id))
                group.name = item.get("group_name") or group.name
                group.member_count = int(item.get("member_count") or group.member_count or 0)
                group.max_member_count = int(item.get("max_member_count") or group.max_member_count or 0)
                group.owner_id = item.get("owner_id") or group.owner_id
                group.last_synced_at = datetime.now(timezone.utc)
                count += 1
            await db.commit()
            await write_log(
                db, level="INFO", category="qq", message=f"同步群列表完成，共 {count} 个群", account_id=account_db_id
            )
        return count

    async def sync_group_members(self, account_db_id: int, group_number: int) -> int:
        adapter = self.adapter(account_db_id)
        if not adapter:
            raise AdapterError("账号未在线，无法同步群成员")
        members = await adapter.get_group_member_list(group_number)
        async with SessionLocal() as db:
            group = await db.scalar(
                select(Group).where(Group.account_id == account_db_id, Group.group_number == group_number)
            )
            if not group:
                raise AdapterError(f"未找到群 {group_number}，请先同步群列表")
            count = 0
            for item in members:
                uid = int(item.get("user_id") or 0)
                if not uid:
                    continue
                member = await db.scalar(
                    select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == uid)
                )
                if not member:
                    member = GroupMember(group_id=group.id, user_id=uid)
                    db.add(member)
                member.nickname = item.get("nickname") or member.nickname
                member.card = item.get("card") or member.card
                member.role = item.get("role") or member.role or "member"
                count += 1
            group.member_count = count or group.member_count
            group.last_synced_at = datetime.now(timezone.utc)
            await db.commit()
        return count

    # ------------------------------------------------------------------
    async def send_group_message(
        self,
        account_db_id: int,
        group_number: int,
        content: str,
        *,
        markdown: dict[str, Any] | None = None,
        keyboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter = self.adapter(account_db_id)
        if not adapter:
            raise AdapterError("账号不在线，无法发送消息")
        if not adapter.supports("send_group_message"):
            raise UnsupportedAction("当前协议端不支持发送群消息")
        result = await adapter.send_group_message(group_number, content, markdown=markdown, keyboard=keyboard)
        state = self._runtimes.get(account_db_id)
        if state:
            state.messages_sent += 1
        return result

    async def send_private_message(
        self,
        account_db_id: int,
        user_id: int,
        content: str,
        *,
        markdown: dict[str, Any] | None = None,
        keyboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter = self.adapter(account_db_id)
        if not adapter:
            raise AdapterError("账号不在线，无法发送消息")
        if not adapter.supports("send_private_message"):
            raise UnsupportedAction("当前协议端不支持发送私聊消息")
        result = await adapter.send_private_message(user_id, content, markdown=markdown, keyboard=keyboard)
        state = self._runtimes.get(account_db_id)
        if state:
            state.messages_sent += 1
        return result

    async def invoke(self, account_db_id: int, action: str, **params: Any) -> dict[str, Any]:
        """统一能力门控调用：不支持则抛 UnsupportedAction，绝不返回假成功。"""
        adapter = self.adapter(account_db_id)
        if not adapter:
            raise AdapterError("账号不在线")
        if not adapter.supports(action):
            raise UnsupportedAction(f"当前协议端不支持该操作：{action}")
        method = getattr(adapter, action, None)
        if not method:
            raise UnsupportedAction(f"适配器未实现该操作：{action}")
        return await method(**params)


account_manager = AccountManager()
