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
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from app.api.deps import get_current_user
from app.core.events import event_hub
from app.core.logging import hub
from app.core.security import create_access_token, decode_access_token, token_matches_user
from app.core.timeutil import day_start
from app.db.session import SessionLocal
from app.models import AuthSession, Message, User
from app.services.account_manager import account_manager
from app.services.scheduler import scheduler_service

router = APIRouter()

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


async def _authenticate(token: str | None) -> User | None:
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
async def issue_ws_ticket(request: Request, current=Depends(get_current_user)):
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
    return {"ticket": token, "expires_in": WS_TICKET_TTL_SECONDS}


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
                if tick % 4 == 0 and not await _session_alive(username, session_jti):
                    await websocket.close(code=4401, reason="登录会话已失效")
                    return
                await websocket.send_json({"type": "ping", "id": None, "time": datetime.now(timezone.utc).isoformat(), "data": {}})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
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
                if tick % 4 == 0 and not await _session_alive(username, session_jti):
                    await websocket.close(code=4401, reason="登录会话已失效")
                    return
                await websocket.send_json({"type": "ping", "time": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
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
    try:
        while True:
            tick += 1
            # 状态流每 5 秒一轮，每 12 轮（约 60 秒）复核一次会话。
            if tick % 12 == 0 and not await _session_alive(username, session_jti):
                await websocket.close(code=4401, reason="登录会话已失效")
                return
            today = day_start()
            async with SessionLocal() as db:
                messages = await db.scalar(
                    select(func.count()).select_from(Message).where(Message.created_at >= today)
                ) or 0
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
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
