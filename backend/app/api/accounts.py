"""QQ 账号管理：CRUD、启停、能力检测、日志、统计。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError
from app.api.deps import client_ip, require
from app.core.security import encrypt_secret
from app.db.session import get_db
from app.models import Account, AccountConnection, Group, Message, SystemLog, User
from app.schemas.account import (
    AccountCreate,
    AccountOut,
    AccountStatsOut,
    AccountUpdate,
    ConnectionOut,
)
from app.schemas.common import MessageOut
from app.services.account_manager import account_manager, build_adapter
from app.services.logs import audit, write_log

router = APIRouter(prefix="/accounts", tags=["QQ账号"])


def serialize(account: Account, groups: int = 0) -> AccountOut:
    state = account_manager.get(account.id)
    runtime = state.state if state else "stopped"
    capabilities = account_manager.capabilities(account.id)
    return AccountOut(
        id=account.id,
        account_id=account.account_id,
        name=account.name,
        qq_number=account.qq_number,
        nickname=account.nickname,
        avatar_url=account.avatar_url,
        protocol=account.protocol,
        connection_mode=account.connection_mode,
        api_base=account.api_base,
        ws_url=account.ws_url,
        self_id=account.self_id,
        enabled=account.enabled,
        auto_start=account.auto_start,
        auto_reconnect=account.auto_reconnect,
        remark=account.remark,
        created_at=account.created_at,
        connection=ConnectionOut.model_validate(account.connection) if account.connection else None,
        has_token=bool(account.access_token_enc),
        online_seconds=state.online_seconds if state else 0,
        group_count=groups,
        capabilities=capabilities,
        runtime_state=runtime,
    )


async def _group_counts(db: AsyncSession) -> dict[int, int]:
    rows = await db.execute(select(Group.account_id, func.count(Group.id)).group_by(Group.account_id))
    return {account_id: count for account_id, count in rows.all()}


@router.get("", response_model=list[AccountOut])
async def list_accounts(db: AsyncSession = Depends(get_db), _: User = Depends(require("account:view"))):
    accounts = list(await db.scalars(select(Account).order_by(Account.id)))
    counts = await _group_counts(db)
    return [serialize(a, counts.get(a.id, 0)) for a in accounts]


@router.get("/stats", response_model=AccountStatsOut)
async def account_stats(db: AsyncSession = Depends(get_db), _: User = Depends(require("account:view"))):
    accounts = list(await db.scalars(select(Account)))
    online = sum(1 for a in accounts if account_manager.is_online(a.id))
    error = sum(
        1
        for a in accounts
        if a.connection and a.connection.status == "error" and not account_manager.is_online(a.id)
    )
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    sent = await db.scalar(
        select(func.count()).select_from(Message).where(Message.direction == "out", Message.created_at >= today)
    )
    received = await db.scalar(
        select(func.count()).select_from(Message).where(Message.direction == "in", Message.created_at >= today)
    )
    last_connected = max(
        (a.connection.connected_at for a in accounts if a.connection and a.connection.connected_at), default=None
    )
    last_heartbeat = max(
        (a.connection.last_heartbeat_at for a in accounts if a.connection and a.connection.last_heartbeat_at), default=None
    )
    return AccountStatsOut(
        total=len(accounts),
        online=online,
        offline=len(accounts) - online - error,
        error=error,
        today_sent=sent or 0,
        today_received=received or 0,
        last_connected_at=last_connected,
        last_heartbeat_at=last_heartbeat,
    )


@router.post("", response_model=AccountOut, status_code=201)
async def create_account(
    payload: AccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("account:manage")),
):
    if payload.protocol == "onebot11" and not payload.api_base:
        raise HTTPException(status_code=400, detail="OneBot v11 账号必须填写 HTTP API 地址（例如 http://127.0.0.1:3000）")
    if payload.connection_mode == "ws_client" and not payload.ws_url:
        raise HTTPException(status_code=400, detail="ws_client 模式必须填写 WebSocket 地址（例如 ws://127.0.0.1:3001）")
    account = Account(
        account_id=uuid.uuid4().hex[:12],
        name=payload.name,
        qq_number=payload.qq_number,
        nickname=payload.nickname,
        protocol=payload.protocol,
        connection_mode=payload.connection_mode,
        api_base=payload.api_base,
        ws_url=payload.ws_url,
        access_token_enc=encrypt_secret(payload.access_token),
        enabled=payload.enabled,
        auto_start=payload.auto_start,
        auto_reconnect=payload.auto_reconnect,
        reconnect_base_seconds=payload.reconnect_base_seconds,
        reconnect_max_seconds=payload.reconnect_max_seconds,
        remark=payload.remark,
        features={},
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    db.add(AccountConnection(account_id=account.id, status="offline"))
    await db.commit()
    await db.refresh(account)
    await audit(
        db,
        user_id=user.id,
        username=user.username,
        action="create_account",
        target=account.account_id,
        detail=f"协议={account.protocol} 模式={account.connection_mode}",
        ip=client_ip(request),
    )
    await write_log(
        db, level="INFO", category="account", message=f"新增账号 {account.name}", account_id=account.id
    )
    return serialize(account)


@router.put("/{account_db_id}", response_model=AccountOut)
async def update_account(
    account_db_id: int,
    payload: AccountUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("account:manage")),
):
    account = await db.get(Account, account_db_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    data = payload.model_dump(exclude_unset=True)
    token = data.pop("access_token", None)
    if token is not None:
        account.access_token_enc = encrypt_secret(token) if token else None
    for field, value in data.items():
        setattr(account, field, value)
    await db.commit()
    await db.refresh(account)
    await audit(
        db, user_id=user.id, username=user.username, action="update_account", target=account.account_id, ip=client_ip(request)
    )
    state = account_manager.get(account.id)
    if state and state.state == "online":
        await account_manager.restart(account.id)
    counts = await _group_counts(db)
    return serialize(account, counts.get(account.id, 0))


@router.delete("/{account_db_id}", response_model=MessageOut)
async def delete_account(
    account_db_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("account:manage")),
):
    account = await db.get(Account, account_db_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    await account_manager.stop(account.id)
    name = account.name
    await db.delete(account)
    await db.commit()
    await audit(
        db, user_id=user.id, username=user.username, action="delete_account", target=name, ip=client_ip(request)
    )
    return MessageOut(detail=f"账号 {name} 及其数据已删除")


@router.post("/{account_db_id}/start", response_model=AccountOut)
async def start_account(
    account_db_id: int, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require("account:manage"))
):
    account = await db.get(Account, account_db_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    try:
        await account_manager.start(account.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit(db, user_id=user.id, username=user.username, action="start_account", target=account.name, ip=client_ip(request))
    await db.refresh(account)
    counts = await _group_counts(db)
    return serialize(account, counts.get(account.id, 0))


@router.post("/{account_db_id}/stop", response_model=AccountOut)
async def stop_account(
    account_db_id: int, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require("account:manage"))
):
    account = await db.get(Account, account_db_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    await account_manager.stop(account.id)
    await audit(db, user_id=user.id, username=user.username, action="stop_account", target=account.name, ip=client_ip(request))
    await db.refresh(account)
    counts = await _group_counts(db)
    return serialize(account, counts.get(account.id, 0))


@router.post("/{account_db_id}/restart", response_model=AccountOut)
async def restart_account(
    account_db_id: int, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require("account:manage"))
):
    account = await db.get(Account, account_db_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    await account_manager.restart(account.id)
    await audit(db, user_id=user.id, username=user.username, action="restart_account", target=account.name, ip=client_ip(request))
    await db.refresh(account)
    counts = await _group_counts(db)
    return serialize(account, counts.get(account.id, 0))


@router.post("/batch/{action}", response_model=MessageOut)
async def batch_action(
    action: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("account:manage")),
):
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(status_code=400, detail="不支持的操作")
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="请提供账号 ID 列表")
    ok, failed = 0, 0
    for account_id in ids:
        account = await db.get(Account, int(account_id))
        if not account:
            failed += 1
            continue
        try:
            if action == "start":
                await account_manager.start(account.id)
            elif action == "stop":
                await account_manager.stop(account.id)
            else:
                await account_manager.restart(account.id)
            ok += 1
        except Exception:  # noqa: BLE001
            failed += 1
    await audit(db, user_id=user.id, username=user.username, action=f"batch_{action}", detail=f"成功 {ok}，失败 {failed}")
    return MessageOut(detail=f"批量{action}完成：成功 {ok}，失败 {failed}")


@router.get("/{account_db_id}/capabilities")
async def account_capabilities(
    account_db_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("account:view"))
):
    account = await db.get(Account, account_db_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    from app.adapters.base import CAPABILITIES

    caps = account_manager.capabilities(account.id)
    if not caps:
        adapter = build_adapter(account)
        caps = adapter.capabilities()
    return {
        "account_id": account.account_id,
        "online": account_manager.is_online(account.id),
        "protocol": account.protocol,
        "capabilities": [
            {"key": key, "label": label, "supported": bool(caps.get(key, False))} for key, label in CAPABILITIES.items()
        ],
    }


@router.post("/{account_db_id}/test-connection")
async def test_connection(
    account_db_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("account:manage"))
):
    account = await db.get(Account, account_db_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    adapter = build_adapter(account)
    try:
        info = await adapter.connect()
        groups = await adapter.get_group_list()
        await adapter.disconnect()
        return {
            "ok": True,
            "message": f"连接成功：{info.nickname}（{info.self_id}），可访问 {len(groups)} 个群",
            "data": {"self_id": info.self_id, "nickname": info.nickname, "groups": len(groups)},
        }
    except (AdapterError, Exception) as exc:  # noqa: BLE001
        try:
            await adapter.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "message": f"连接失败：{exc}", "data": None}


@router.get("/{account_db_id}/logs")
async def account_logs(
    account_db_id: int,
    limit: int = Query(default=100, le=500),
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("account:view")),
):
    query = select(SystemLog).where(SystemLog.account_id == account_db_id)
    if category:
        query = query.where(SystemLog.category == category)
    rows = await db.scalars(query.order_by(SystemLog.id.desc()).limit(limit))
    return [
        {
            "id": log.id,
            "level": log.level,
            "category": log.category,
            "message": log.message,
            "context": log.context,
            "created_at": log.created_at,
        }
        for log in rows
    ]


@router.get("/{account_db_id}/messages-stats")
async def message_stats(
    account_db_id: int, days: int = Query(default=7, ge=1, le=30), db: AsyncSession = Depends(get_db),
    _: User = Depends(require("message:view")),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await db.execute(
        select(func.date(Message.created_at), Message.direction, func.count(Message.id))
        .where(Message.account_id == account_db_id, Message.created_at >= since)
        .group_by(func.date(Message.created_at), Message.direction)
    )
    buckets: dict[str, dict[str, int]] = {}
    for day, direction, count in rows.all():
        key = str(day)
        buckets.setdefault(key, {"date": key, "in": 0, "out": 0})
        buckets[key][direction] = count
    return sorted(buckets.values(), key=lambda item: item["date"])
