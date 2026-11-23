"""WebSocket：实时日志流与运行状态推送。

认证使用一次性短时 ticket 而不是把访问令牌放进查询串：查询串会进入反向代理的
access log、浏览器历史与 Referer，等同于长期泄漏 JWT。客户端先调用
``POST /api/ws/ticket``（走正常 Authorization 头）换取 60 秒有效的票据，
再用 ``?ticket=`` 建立连接。为兼容旧前端，仍接受 ``?token=``。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.core.events import event_hub
from app.core.logging import hub
from app.core.security import create_access_token, decode_access_token, token_matches_user
from app.core.timeutil import day_start
from app.db.session import SessionLocal
from app.models import AuthSession, Message, User, WsTicket
from app.services.account_manager import account_manager
from app.services.scheduler import scheduler_service

router = APIRouter()
logger = logging.getLogger("qbot.ws")

# WebSocket 票据的有效期（秒）。只够完成一次握手，不用于长期鉴权。
WS_TICKET_TTL_SECONDS = 60


def _raw_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get("qbot_token")


def _ticket_payload(token: str) -> dict | None:
    payload = decode_access_token(token)
    if not payload or payload.get("purpose") != "ws_ticket":
        return None
    return payload


async def _authenticate(token: str | None, *, consume: bool = True) -> User | None:
    if not token:
        return None
    # 票据与真实访问令牌共用签名，靠 purpose 区分，避免票据被当成 API 凭证使用。
    ticket = _ticket_payload(token)
    payload = ticket or decode_access_token(token)
    if not payload:
        return None
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == payload.get("sub")))
        if not user or not user.is_active:
            return None
        if not ticket and not token_matches_user(payload, user.password_hash):
            return None
        # 票据是由访问令牌换来的，会话校验用的是原会话的 jti。
        jti = payload.get("session_jti") if ticket else payload.get("jti")
        if ticket and not jti:
            return None
        if ticket and consume and not await _consume_ticket(db, user, payload):
            return None
        if jti:
            session = await db.scalar(select(AuthSession).where(AuthSession.jti == jti, AuthSession.user_id == user.id))
            now = datetime.now(timezone.utc)
            expires_at = session.expires_at if session else None
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if not session or session.revoked_at or (expires_at and expires_at <= now):
                return None
            session.last_seen_at = now
            await db.commit()
        return user


async def _consume_ticket(db: AsyncSession, user: User, payload: dict) -> bool:
    """抢占式消费票据：并发握手时只有一次 UPDATE 能命中，重复使用直接拒绝。

    票据在签发时写入 ``ws_tickets``，因此这里同时校验「确实由本服务签发」和
    「尚未被消费」两个条件，避免同一张票在 60 秒窗口内建立多条连接。
    """
    ticket_jti = str(payload.get("jti") or "")
    if not ticket_jti:
        return False
    now = datetime.now(timezone.utc)
    # SQLite stores ``DateTime(timezone=True)`` as naive text. Use a naive
    # comparison value for the predicate while keeping the audit timestamp UTC.
    query_now = now.replace(tzinfo=None)
    try:
        result = await db.execute(
            update(WsTicket)
            .where(
                WsTicket.jti == ticket_jti,
                WsTicket.user_id == user.id,
                WsTicket.consumed_at.is_(None),
                WsTicket.expires_at > query_now,
            )
            .values(consumed_at=now)
            # SQLite 存的是 naive datetime，交给 ORM 做 Python 侧评估会抛
            # "can't compare offset-naive and offset-aware datetimes"；条件本身
            # 已在 SQL 中完成，这里不需要同步会话内的对象。
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("WebSocket ticket consumption failed jti=%s", ticket_jti)
        await db.rollback()
        return False
    return result.rowcount == 1


def _session_ref(token: str | None) -> tuple[str | None, str]:
    """从票据或访问令牌里取出 (会话 jti, 用户名)，供长连接期间的会话复核。"""
    if not token:
        return None, ""
    ticket = _ticket_payload(token)
    payload = ticket or decode_access_token(token) or {}
    jti = payload.get("session_jti") if ticket else payload.get("jti")
    return jti, str(payload.get("sub") or "")


async def _session_alive(username: str, jti: str | None) -> bool:
    """长连接期间的会话复核：撤销登录或会话过期后必须主动断开。"""
    if not jti:
        return True
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username))
        if not user or not user.is_active:
            return False
        session = await db.scalar(select(AuthSession).where(AuthSession.jti == jti, AuthSession.user_id == user.id))
        if not session or session.revoked_at:
            return False
        expires_at = session.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return not (expires_at and expires_at <= datetime.now(timezone.utc))


@router.post("/ws/ticket")
async def issue_ws_ticket(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current=Depends(get_current_user),
):
    """签发一次性 WebSocket 票据，避免把长期 JWT 放进查询串。

    ticket 只携带 purpose=ws_ticket 与原会话 jti，60 秒过期；它不带 pwd_v，
    因此无法用于普通 API 鉴权（``get_current_user`` 会拒绝）。
    """
    raw = _raw_token(request)
    decoded = decode_access_token(raw) if raw else None
    session_jti = decoded.get("jti") if decoded else None
    token = create_access_token(
        current.username,
        {"purpose": "ws_ticket", "session_jti": session_jti},
        expires_minutes=1,
    )
    decoded = decode_access_token(token) or {}
    expires_at = datetime.fromtimestamp(float(decoded.get("exp") or 0), tz=timezone.utc)
    db.add(
        WsTicket(
            jti=str(decoded.get("jti") or ""),
            user_id=current.id,
            expires_at=expires_at,
        )
    )
    await _prune_tickets(db)
    await db.commit()
    return {"ticket": token, "expires_in": WS_TICKET_TTL_SECONDS}


async def _prune_tickets(db: AsyncSession) -> None:
    """清理过期票据，控制表体积；保留最近一小时便于排查重复握手。"""
    cutoff = datetime.now(timezone.utc).timestamp() - 3600
    await db.execute(delete(WsTicket).where(WsTicket.expires_at < datetime.fromtimestamp(cutoff, tz=timezone.utc)))


@router.websocket("/ws/events")
async def ws_events(
    websocket: WebSocket,
    ticket: str | None = Query(default=None),
    token: str | None = Query(default=None),
    account_id: int | None = Query(default=None),
):
    """统一事件流；优先用一次性 ticket，兼容旧的 token 查询认证。"""
    credential = ticket or token
    user = await _authenticate(credential)
    if not user or not ("*" in user.permission_set or "account:view" in user.permission_set or "log:view" in user.permission_set):
        await websocket.close(code=4403 if user else 4401, reason="缺少实时事件权限" if user else "未授权")
        return
    await websocket.accept()
    queue = await event_hub.subscribe()
    session_jti, username = _session_ref(credential)
    tick = 0
    try:
        await websocket.send_json({"type": "connected", "id": None, "time": datetime.now(timezone.utc).isoformat(), "data": {"channels": ["log.created", "account.state", "status"]}})
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=25)
                data = item.get("data") or {}
                if account_id is not None and data.get("account_id") not in {None, account_id}:
                    continue
                await websocket.send_json(item)
            except asyncio.TimeoutError:
                tick += 1
                # 每 4 次心跳（约 100 秒）复核一次会话，撤销登录后必须尽快断开。
                if tick % 4 == 0:
                    try:
                        alive = await _session_alive(username, session_jti)
                    except Exception:  # noqa: BLE001
                        logger.warning("ws/events 会话复核失败，保持连接 user=%s", username, exc_info=True)
                        alive = True
                    if not alive:
                        await websocket.close(code=4401, reason="登录会话已失效")
                        return
                await websocket.send_json({"type": "ping", "id": None, "time": datetime.now(timezone.utc).isoformat(), "data": {}})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("ws/events 事件流异常关闭 user=%s", username)
    finally:
        await event_hub.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await websocket.close()


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket, ticket: str | None = Query(default=None), token: str | None = Query(default=None)):
    user = await _authenticate(ticket or token)
    if not user or not ("*" in user.permission_set or "log:view" in user.permission_set):
        await websocket.close(code=4403 if user else 4401, reason="缺少日志权限" if user else "未授权")
        return
    await websocket.accept()
    queue = await hub.subscribe()
    session_jti, username = _session_ref(ticket or token)
    tick = 0
    try:
        await websocket.send_json({"type": "connected", "message": "实时日志已连接"})
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=25)
                await websocket.send_json({"type": "log", **item})
            except asyncio.TimeoutError:
                tick += 1
                if tick % 4 == 0:
                    try:
                        alive = await _session_alive(username, session_jti)
                    except Exception:  # noqa: BLE001
                        logger.warning("ws/logs 会话复核失败，保持连接 user=%s", username, exc_info=True)
                        alive = True
                    if not alive:
                        await websocket.close(code=4401, reason="登录会话已失效")
                        return
                await websocket.send_json({"type": "ping", "time": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("ws/logs 日志流异常关闭 user=%s", username)
    finally:
        await hub.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await websocket.close()


@router.websocket("/ws/status")
async def ws_status(websocket: WebSocket, ticket: str | None = Query(default=None), token: str | None = Query(default=None)):
    user = await _authenticate(ticket or token)
    if not user or not ("*" in user.permission_set or "account:view" in user.permission_set):
        await websocket.close(code=4403 if user else 4401, reason="缺少账号权限" if user else "未授权")
        return
    await websocket.accept()
    credential = ticket or token
    session_jti, username = _session_ref(credential)
    tick = 0
    messages = 0
    db_errors = 0
    started = time.monotonic()
    close_code: int | None = None
    logger.info("ws/status 已连接 user=%s", username)
    try:
        while True:
            tick += 1
            # 状态流每 5 秒一轮，每 12 轮（约 60 秒）复核一次会话。
            if tick % 12 == 0:
                try:
                    alive = await _session_alive(username, session_jti)
                except Exception:  # noqa: BLE001
                    # 复核失败（数据库抖动）不等于会话失效，保持连接、下一轮再试。
                    logger.warning("ws/status 会话复核失败，保持连接 user=%s", username, exc_info=True)
                    alive = True
                if not alive:
                    close_code = 4401
                    await websocket.close(code=4401, reason="登录会话已失效")
                    return
            today = day_start()
            try:
                async with SessionLocal() as db:
                    messages = await db.scalar(
                        select(func.count()).select_from(Message).where(Message.created_at >= today)
                    ) or 0
            except Exception:  # noqa: BLE001
                # 单次统计失败（SQLite 写入高峰的锁等待）不再掐断整条实时状态流，
                # 沿用上一次计数，5 秒后重试；否则前端会莫名显示一次「连接已断开」。
                db_errors += 1
                if db_errors == 1 or db_errors % 60 == 0:
                    logger.warning(
                        "ws/status 统计今日消息失败，沿用上一次结果（连续 %s 次）", db_errors, exc_info=db_errors == 1,
                    )
            else:
                db_errors = 0
            states = account_manager.all_states()
            status_data = {
                "online": sum(1 for s in states if s.state == "online"),
                "error": sum(1 for s in states if s.state == "error"),
                "total_runtime": len(states),
                "messages_today": messages,
                "scheduler_running": scheduler_service.running,
                "accounts": [
                    {"id": s.account_db_id, "name": s.name, "state": s.state, "online_seconds": s.online_seconds}
                    for s in states
                ],
            }
            payload = {"type": "status", "id": None, "time": datetime.now(timezone.utc).isoformat(), "data": status_data}
            # 旧客户端仍可读取顶层 status 字段。
            payload.update(status_data)
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
            await asyncio.sleep(5)
    except WebSocketDisconnect as exc:
        close_code = getattr(exc, "code", None)
    except Exception:  # noqa: BLE001
        # 以前是静默 pass，前端只看到「连接已断开」而服务端毫无记录，无法定位。
        logger.exception("ws/status 推送循环异常，连接关闭 user=%s", username)
    finally:
        logger.info(
            "ws/status 连接结束 user=%s 关闭码=%s 时长=%.0fs",
            username, close_code if close_code is not None else "客户端断开", time.monotonic() - started,
        )
