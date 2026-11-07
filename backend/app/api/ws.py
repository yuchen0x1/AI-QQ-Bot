"""WebSocket：实时日志流与运行状态推送。"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from app.core.events import event_hub
from app.core.logging import hub
from app.core.security import decode_access_token, token_matches_user
from app.db.session import SessionLocal
from app.models import AuthSession, Message, User
from app.services.account_manager import account_manager
from app.services.scheduler import scheduler_service

router = APIRouter()


async def _authenticate(token: str | None) -> User | None:
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == payload.get("sub")))
        if not user or not user.is_active or not token_matches_user(payload, user.password_hash):
            return None
        jti = payload.get("jti")
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


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket, token: str | None = Query(default=None), account_id: int | None = Query(default=None)):
    """统一事件流；兼容 token 查询认证，并按 account_id 过滤账号事件。"""
    user = await _authenticate(token)
    if not user or not ("*" in user.permission_set or "account:view" in user.permission_set or "log:view" in user.permission_set):
        await websocket.close(code=4403 if user else 4401, reason="缺少实时事件权限" if user else "未授权")
        return
    await websocket.accept()
    queue = await event_hub.subscribe()
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
async def ws_logs(websocket: WebSocket, token: str | None = Query(default=None)):
    user = await _authenticate(token)
    if not user or not ("*" in user.permission_set or "log:view" in user.permission_set):
        await websocket.close(code=4403 if user else 4401, reason="缺少日志权限" if user else "未授权")
        return
    await websocket.accept()
    queue = await hub.subscribe()
    try:
        await websocket.send_json({"type": "connected", "message": "实时日志已连接"})
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=25)
                await websocket.send_json({"type": "log", **item})
            except asyncio.TimeoutError:
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
async def ws_status(websocket: WebSocket, token: str | None = Query(default=None)):
    user = await _authenticate(token)
    if not user or not ("*" in user.permission_set or "account:view" in user.permission_set):
        await websocket.close(code=4403 if user else 4401, reason="缺少账号权限" if user else "未授权")
        return
    await websocket.accept()
    try:
        while True:
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
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
