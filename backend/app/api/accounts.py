"""QQ 账号管理：CRUD、启停、能力检测、日志、统计。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError
from app.api.deps import client_ip, require
from app.core.config import settings
from app.core.security import encrypt_secret
from app.core.timeutil import date_bucket, day_start
from app.db.session import get_db
from app.models import Account, AccountConnection, GithubNotificationTarget, Group, Message, PushRule, SystemLog, SystemSetting, User
from app.schemas.account import (
    AccountCreate,
    AccountOut,
    AccountStatsOut,
    AccountUpdate,
    ConnectionOut,
    DEFAULT_OFFICIAL_INTENTS,
)
from app.schemas.common import MessageOut
from app.services.account_manager import account_manager, build_adapter
from app.services.logs import audit, write_log

router = APIRouter(prefix="/accounts", tags=["QQ账号"])

OFFICIAL_FEATURE_KEYS = (
    "official_sandbox",
    "official_intents",
    "official_allow_proactive",
    "official_api_base",
)
OFFICIAL_MODES = ("official_ws", "official_webhook")
OFFICIAL_FEATURE_DEFAULTS = {
    "official_sandbox": False,
    "official_intents": DEFAULT_OFFICIAL_INTENTS,
    "official_allow_proactive": True,
    "official_api_base": "",
}


def official_features(account: Account) -> dict[str, Any]:
    features = account.features or {}
    return {key: features.get(key, default) for key, default in OFFICIAL_FEATURE_DEFAULTS.items()}


def webhook_url(account: Account) -> str | None:
    if not account.app_id:
        return None
    base = settings.public_base_url.rstrip("/")
    return f"{base}{settings.api_prefix}/qqbot/webhook/{account.app_id}"


def serialize(account: Account, groups: int = 0) -> AccountOut:
    state = account_manager.get(account.id)
    runtime = state.state if state else "stopped"
    capabilities = account_manager.capabilities(account.id)
    official = official_features(account)
    return AccountOut(
        id=account.id,
        account_id=account.account_id,
        name=account.name,
        qq_number=account.qq_number,
        nickname=account.nickname,
        avatar_url=account.avatar_url,
        protocol=account.protocol,
        connection_mode=account.connection_mode,
        self_id=account.self_id,
        app_id=account.app_id,
        bot_openid=account.bot_openid,
        webhook_url=webhook_url(account),
        has_secret=bool(account.app_secret_enc),
        official_sandbox=bool(official["official_sandbox"]),
        official_intents=int(official["official_intents"]),
        official_allow_proactive=bool(official["official_allow_proactive"]),
        official_api_base=official["official_api_base"] or None,
        enabled=account.enabled,
        auto_start=account.auto_start,
        auto_reconnect=account.auto_reconnect,
        remark=account.remark,
        created_at=account.created_at,
        connection=ConnectionOut.model_validate(account.connection) if account.connection else None,
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
    accounts = list(await db.scalars(select(Account).where(Account.protocol == "qq_official").order_by(Account.id)))
    counts = await _group_counts(db)
    return [serialize(a, counts.get(a.id, 0)) for a in accounts]


@router.get("/stats", response_model=AccountStatsOut)
async def account_stats(db: AsyncSession = Depends(get_db), _: User = Depends(require("account:view"))):
    accounts = list(await db.scalars(select(Account).where(Account.protocol == "qq_official")))
    online = sum(1 for a in accounts if account_manager.is_online(a.id))
    error = sum(
        1
        for a in accounts
        if a.connection and a.connection.status == "error" and not account_manager.is_online(a.id)
    )
    today = day_start()
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
    if payload.protocol == "qq_official" and (not payload.app_id or not payload.app_secret):
        raise HTTPException(
            status_code=400,
            detail="QQ 官方机器人必须填写 AppID 和 AppSecret（在 QQ 开放平台 → 机器人 → 开发设置 中获取）",
        )
    official_config = {
        "official_sandbox": bool(payload.official_sandbox),
        "official_intents": int(payload.official_intents),
        "official_allow_proactive": bool(payload.official_allow_proactive),
        "official_api_base": payload.official_api_base or "",
    }
    connection_mode = payload.connection_mode
    account = Account(
        account_id=uuid.uuid4().hex[:12],
        name=payload.name,
        qq_number=payload.qq_number,
        nickname=payload.nickname,
        protocol=payload.protocol,
        connection_mode=connection_mode,
        app_id=payload.app_id,
        app_secret_enc=encrypt_secret(payload.app_secret),
        enabled=payload.enabled,
        auto_start=payload.auto_start,
        auto_reconnect=payload.auto_reconnect,
        reconnect_base_seconds=payload.reconnect_base_seconds,
        reconnect_max_seconds=payload.reconnect_max_seconds,
        remark=payload.remark,
        features=official_config,
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
    next_protocol = data.get("protocol", account.protocol)
    next_mode = data.get("connection_mode", account.connection_mode)
    next_app_id = data.get("app_id", account.app_id)
    if next_protocol != "qq_official":
        raise HTTPException(status_code=400, detail="当前版本仅支持 QQ 官方机器人")
    if not next_app_id or not (data.get("app_secret") or account.app_secret_enc):
        raise HTTPException(status_code=400, detail="QQ 官方机器人必须填写 AppID 和 AppSecret")
    if next_mode not in OFFICIAL_MODES:
        data["connection_mode"] = "official_ws"
    # 空密钥保留原值，避免编辑时清空有效凭据。
    secret = data.pop("app_secret", None)
    if secret:
        account.app_secret_enc = encrypt_secret(secret)
    incoming_features = {key: data.pop(key) for key in OFFICIAL_FEATURE_KEYS if key in data}
    if incoming_features:
        account.features = {**(account.features or {}), **incoming_features}
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
    target_ids = list(await db.scalars(select(GithubNotificationTarget.id).where(GithubNotificationTarget.account_id == account.id)))
    if target_ids:
        await db.execute(update(PushRule).where(PushRule.notification_target_id.in_(target_ids)).values(enabled=False, notification_target_id=None))
        await db.execute(delete(SystemSetting).where(SystemSetting.key.startswith("github_group_bind:"), SystemSetting.value["target_id"].as_integer().in_(target_ids)))
        await db.execute(delete(GithubNotificationTarget).where(GithubNotificationTarget.id.in_(target_ids)))
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
        if account.protocol == "qq_official":
            # 官方机器人只做凭证 / 网关连通性探测，不占用长连接会话额度。
            probe = await adapter.probe()
            await adapter.disconnect()
            env = "沙箱" if probe["sandbox"] else "正式"
            if probe.get("callback_mode") == "webhook":
                message = (
                    f"凭证有效（{env}环境）。请在开放平台把回调地址设为 "
                    f"{webhook_url(account)}，保持账号在线后平台会发起地址验证"
                )
            else:
                message = f"凭证有效，网关可用（{env}环境）。启动账号后即可接收事件"
            return {"ok": True, "message": message, "data": probe}
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
    day_expr = date_bucket(Message.created_at, db.bind.dialect.name if db.bind is not None else "sqlite")
    rows = await db.execute(
        select(day_expr, Message.direction, func.count(Message.id))
        .where(Message.account_id == account_db_id, Message.created_at >= since)
        .group_by(day_expr, Message.direction)
    )
    buckets: dict[str, dict[str, int]] = {}
    for day, direction, count in rows.all():
        key = str(day)
        buckets.setdefault(key, {"date": key, "in": 0, "out": 0})
        buckets[key][direction] = count
    return sorted(buckets.values(), key=lambda item: item["date"])
