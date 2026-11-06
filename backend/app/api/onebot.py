"""OneBot v11 接入端点：

- 反向 WebSocket：协议端（NapCat / Lagrange）主动连到本平台上报事件
- HTTP 事件上报：协议端以 POST 方式推送事件
"""

from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.onebot11 import OneBot11Adapter
from app.core.security import decrypt_secret
from app.db.session import SessionLocal, get_db
from app.models import Account
from app.services.account_manager import account_manager

logger = logging.getLogger("qbot.onebot")
router = APIRouter(prefix="/onebot/v11", tags=["OneBot接入"])


async def _load_account(account_uid: str) -> Account | None:
    async with SessionLocal() as db:
        return await db.scalar(select(Account).where(Account.account_id == account_uid))


def _check_token(account: Account, token: str | None) -> bool:
    """Fail-closed：未配置 Token 或密文无法解密时一律拒绝接入。"""
    expected = decrypt_secret(account.access_token_enc)
    if not expected or not token:
        return False
    return hmac.compare_digest(token, expected)


@router.websocket("/ws/{account_uid}")
async def reverse_ws(websocket: WebSocket, account_uid: str, access_token: str | None = Query(default=None)):
    account = await _load_account(account_uid)
    if not account:
        await websocket.close(code=4404, reason="账号不存在")
        return
    header_token = None
    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        header_token = auth_header[7:]
    if not _check_token(account, access_token or header_token):
        await websocket.close(code=4401, reason="Token 校验失败")
        return
    adapter = account_manager.adapter(account.id)
    if not isinstance(adapter, OneBot11Adapter):
        await websocket.close(code=4409, reason="账号未启动或不是 OneBot 协议")
        return
    await websocket.accept()
    logger.info("OneBot 反向 WebSocket 已连接：%s", account.name)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if "echo" in payload:
                continue
            if payload.get("post_type") == "meta_event" and payload.get("meta_event_type") == "lifecycle":
                await websocket.send_text(
                    json.dumps({"status": "ok", "retcode": 0, "data": {"self_id": payload.get("self_id")}})
                )
            await adapter.feed_event(payload)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("OneBot 反向 WebSocket 异常：%s", exc)
    finally:
        logger.info("OneBot 反向 WebSocket 已断开：%s", account.name)


@router.post("/events/{account_uid}")
async def http_events(
    account_uid: str,
    request: Request,
    access_token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    account = await db.scalar(select(Account).where(Account.account_id == account_uid))
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not _check_token(account, access_token or request.headers.get("authorization", "").replace("Bearer ", "")):
        raise HTTPException(status_code=401, detail="Token 校验失败")
    adapter = account_manager.adapter(account.id)
    if not isinstance(adapter, OneBot11Adapter):
        raise HTTPException(status_code=409, detail="账号未启动或不是 OneBot 协议")
    payload = await request.json()
    await adapter.feed_event(payload)
    return {"status": "ok", "retcode": 0}
