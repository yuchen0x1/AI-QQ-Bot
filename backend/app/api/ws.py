"""WebSocket：实时日志流与运行状态推送。"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from app.core.logging import hub
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import Message, User
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
        return user if user and user.is_active else None


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket, token: str | None = Query(default=None)):
    user = await _authenticate(token)
    if not user:
        await websocket.close(code=4401, reason="未授权")
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
    if not user:
        await websocket.close(code=4401, reason="未授权")
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
            payload = {
                "type": "status",
                "time": datetime.now(timezone.utc).isoformat(),
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
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
