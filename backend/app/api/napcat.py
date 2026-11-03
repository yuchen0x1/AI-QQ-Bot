"""NapCat 扫码登录：只对已授权管理用户暴露二维码会话。"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, require
from app.core.security import encrypt_secret
from app.db.session import get_db
from app.models import Account, AccountConnection, User
from app.schemas.napcat import (
    NapCatInstanceOut,
    NapCatLoginOut,
    NapCatLoginStart,
    NapCatLoginStatusOut,
)
from app.services.account_manager import account_manager
from app.services.logs import audit
from app.services.napcat import NapCatError, NapCatInstance, napcat_bridge

router = APIRouter(prefix="/napcat", tags=["NapCat扫码登录"])
SESSION_TTL = 300


@dataclass
class _LoginSession:
    session_id: str
    instance: NapCatInstance
    qrcode: str
    created_at: float
    expires_at: float
    status: str = "waiting_qrcode"
    login_phase: str | None = None
    login_error: str | None = None
    qq_number: int | None = None
    nickname: str | None = None
    account_id: int | None = None
    name: str | None = None

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


_sessions: dict[str, _LoginSession] = {}


def _cleanup() -> None:
    for key, value in list(_sessions.items()):
        if value.expired:
            _sessions.pop(key, None)


def _session_or_404(session_id: str) -> _LoginSession:
    _cleanup()
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="扫码会话不存在或已过期，请重新获取二维码")
    return session


def _instance_out() -> list[NapCatInstanceOut]:
    return [NapCatInstanceOut(id=item["id"], name=item["name"]) for item in napcat_bridge.public_instances()]


def _error(exc: NapCatError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/instances", response_model=list[NapCatInstanceOut])
async def list_instances(_: User = Depends(require("account:manage"))):
    return _instance_out()


@router.post("/login/start", response_model=NapCatLoginOut)
async def start_login(
    payload: NapCatLoginStart,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("account:manage")),
):
    try:
        instance = napcat_bridge.get_instance(payload.instance_id)
        qrcode = await napcat_bridge.get_qr(instance)
    except NapCatError as exc:
        raise _error(exc) from exc
    session_id = secrets.token_urlsafe(24)
    now = time.time()
    session = _LoginSession(
        session_id=session_id,
        instance=instance,
        qrcode=qrcode,
        created_at=now,
        expires_at=now + SESSION_TTL,
        name=payload.name.strip() if payload.name else None,
    )
    _sessions[session_id] = session
    await audit(
        db,
        user_id=user.id,
        username=user.username,
        action="napcat_qr_start",
        target=instance.id,
        detail="创建扫码登录会话",
        ip=client_ip(request),
    )
    return _serialize(session)


@router.get("/login/{session_id}", response_model=NapCatLoginStatusOut)
async def login_status(session_id: str, _: User = Depends(require("account:manage"))):
    session = _session_or_404(session_id)
    try:
        data = await napcat_bridge.status(session.instance)
    except NapCatError as exc:
        session.status = "error"
        session.login_error = str(exc)
        return _serialize_status(session)
    session.login_phase = data.get("loginPhase")
    session.login_error = data.get("loginError") or None
    if data.get("isLogin") or data.get("coreReady"):
        session.status = "online"
        info = await _safe_login_info(session.instance)
        session.qq_number = _as_int(info.get("uin") or info.get("user_id") or info.get("account"))
        session.nickname = str(info.get("nick") or info.get("nickname") or info.get("nickName") or "") or None
        if session.account_id is None:
            await _finish_account(session)
    elif data.get("qrLoginAccepted"):
        session.status = "qrcode_scanned"
    elif session.login_phase == "initializing":
        session.status = "initializing"
    elif data.get("isOffline"):
        session.status = "offline"
    else:
        session.status = "waiting_qrcode"
    if data.get("qrcodeurl"):
        session.qrcode = str(data["qrcodeurl"])
    return _serialize_status(session)


@router.post("/login/{session_id}/refresh", response_model=NapCatLoginOut)
async def refresh_login(session_id: str, _: User = Depends(require("account:manage"))):
    session = _session_or_404(session_id)
    try:
        session.qrcode = await napcat_bridge.refresh_qr(session.instance)
    except NapCatError as exc:
        raise _error(exc) from exc
    session.created_at = time.time()
    session.expires_at = session.created_at + SESSION_TTL
    session.status = "waiting_qrcode"
    session.login_phase = None
    session.login_error = None
    return _serialize(session)


@router.delete("/login/{session_id}")
async def cancel_login(session_id: str, _: User = Depends(require("account:manage"))):
    _session_or_404(session_id)
    _sessions.pop(session_id, None)
    return {"detail": "扫码会话已取消"}


async def _finish_account(session: _LoginSession) -> None:
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        adapter = account_manager.adapter(session.account_id) if session.account_id else None
        if session.account_id and adapter:
            return
        # NapCat API defaults are kept server-side; browser never sees WebUI credentials.
        account_name = session.name or f"QQ {session.qq_number or '扫码账号'}"
        existing = (
            await db.scalar(select(Account).where(Account.qq_number == session.qq_number))
            if session.qq_number
            else None
        )
        if existing:
            # 同一 QQ 号重新扫码时更新接入配置并复用账号记录，避免重复账号。
            existing.nickname = session.nickname or existing.nickname
            existing.api_base = session.instance.api_base
            existing.ws_url = session.instance.ws_url
            if session.instance.access_token:
                existing.access_token_enc = encrypt_secret(session.instance.access_token)
            existing.enabled = True
            existing.auto_start = True
            existing.features = {**(existing.features or {}), "napcat_instance_id": session.instance.id}
            account = existing
        else:
            account = Account(
                account_id=secrets.token_hex(6),
                name=account_name,
                qq_number=session.qq_number,
                nickname=session.nickname,
                protocol="onebot11",
                connection_mode="ws_client",
                api_base=session.instance.api_base,
                ws_url=session.instance.ws_url,
                access_token_enc=encrypt_secret(session.instance.access_token)
                if session.instance.access_token
                else None,
                enabled=True,
                auto_start=True,
                auto_reconnect=True,
                remark="NapCat 扫码接入",
                features={"napcat_instance_id": session.instance.id},
            )
            db.add(account)
            await db.flush()
            db.add(AccountConnection(account_id=account.id, status="offline"))
        await db.commit()
        await db.refresh(account)
        session.account_id = account.id
        try:
            await napcat_bridge.configure_onebot(session.instance)
        except NapCatError as exc:
            session.status = "error"
            session.login_error = f"QQ 已登录，但 OneBot 配置失败：{exc}"
            return
        try:
            await account_manager.restart(account.id) if account_manager.get(account.id) else await account_manager.start(account.id)
        except Exception as exc:  # noqa: BLE001
            session.status = "error"
            session.login_error = f"QQ 已登录，但平台接入失败：{exc}"


async def _safe_login_info(instance: NapCatInstance) -> dict[str, Any]:
    try:
        return await napcat_bridge.get_login_info(instance)
    except NapCatError:
        return {}


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _serialize(session: _LoginSession) -> NapCatLoginOut:
    return NapCatLoginOut(
        session_id=session.session_id,
        instance_id=session.instance.id,
        instance_name=session.instance.name,
        qrcode=session.qrcode,
        status=session.status,
        expires_at=int(session.expires_at),
        message="请使用手机 QQ 扫描二维码完成登录",
    )


def _serialize_status(session: _LoginSession) -> NapCatLoginStatusOut:
    return NapCatLoginStatusOut(
        session_id=session.session_id,
        instance_id=session.instance.id,
        instance_name=session.instance.name,
        status=session.status,
        qrcode=session.qrcode if session.status in {"waiting_qrcode", "qrcode_scanned", "initializing"} else None,
        login_phase=session.login_phase,
        login_error=session.login_error,
        qq_number=session.qq_number,
        nickname=session.nickname,
        expires_at=int(session.expires_at),
        message="扫码成功，正在接入 OneBot" if session.status == "online" else None,
        account={"id": session.account_id} if session.account_id else None,
    )
