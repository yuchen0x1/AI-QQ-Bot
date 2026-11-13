"""One configuration for all owned GitHub repositories and the notification group."""

import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.db.session import get_db
from app.models import Account, GithubNotificationTarget, Group, PushRule, SystemSetting, User
from app.schemas.github import GithubAutomationIn, GithubNotificationTargetIn
from app.services.github.automation import (
    annotate_group, get_target, list_targets, make_binding_code, mirror_primary_target,
    public_https_url, read_config, reconcile_rules, save_config, subscription_status,
    save_delivery_probe, save_group_permission,
)
from app.services.github.oauth import OAuthError
from app.services.logs import audit
from app.services.scheduler import scheduler_service

router = APIRouter(prefix="/github/automation", tags=["全部仓库通知"])


@router.get("")
async def status(db: AsyncSession = Depends(get_db), user: User = Depends(require("github:view"))):
    return await subscription_status(db, user.id)


@router.put("")
async def configure(payload: GithubAutomationIn, db: AsyncSession = Depends(get_db),
                    user: User = Depends(require("github:manage")), _: User = Depends(require("push:manage"))):
    account = await db.get(Account, payload.account_id) if payload.account_id else None
    if payload.account_id and (not account or not account.enabled):
        raise HTTPException(status_code=400, detail="请选择已启用的发送机器人")
    if payload.install_webhooks:
        try:
            public_https_url()
        except OAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.qq_group and account and account.protocol == "qq_official":
        group = await db.scalar(select(Group.id).where(Group.account_id == account.id, Group.group_number == payload.qq_group))
        if not group:
            raise HTTPException(status_code=400, detail="官方机器人不能用真实群号发送，请使用群内绑定口令")
    previous = await read_config(db, user.id)
    incoming = payload.model_dump(exclude={"account_id", "group_label", "qq_group"})
    value = {**previous, **incoming, "sync_requested": True, "sync_status": "queued", "revision": secrets.token_hex(12)}
    await save_config(db, user.id, value)
    # Older clients edit the first destination; newer clients use the target endpoints.
    if account:
        targets = await list_targets(db, user.id)
        target = targets[0] if targets else GithubNotificationTarget(user_id=user.id, account_id=account.id, group_label=payload.group_label, enabled=True)
        if not targets:
            db.add(target)
        if target.account_id != account.id or target.group_label != payload.group_label:
            target.qq_group = None
        target.account_id, target.group_label = account.id, payload.group_label
        if payload.qq_group is not None:
            target.qq_group = payload.qq_group
        if target.qq_group:
            await annotate_group(db, account.id, target.qq_group, target.group_label)
        await db.commit()
        await mirror_primary_target(db, user.id)
    await reconcile_rules(db, user.id)
    scheduler_service.request_activity_sync()
    await audit(db, user_id=user.id, username=user.username, action="configure_github_notifications", target=payload.group_label)
    return await subscription_status(db, user.id)


async def owned_target(db: AsyncSession, user: User, target_id: int) -> GithubNotificationTarget:
    try:
        return await get_target(db, user.id, target_id)
    except OAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def persist_target(db: AsyncSession, user: User, payload: GithubNotificationTargetIn, target: GithubNotificationTarget | None = None):
    account = await db.get(Account, payload.account_id)
    if not account or not account.enabled or account.protocol != "qq_official":
        raise HTTPException(status_code=400, detail="请选择已启用的发送机器人")
    if target is None:
        target = GithubNotificationTarget(user_id=user.id, account_id=account.id, group_label=payload.group_label)
        db.add(target)
    if target.account_id != account.id or target.group_label != payload.group_label:
        target.qq_group = None
    target.account_id, target.group_label, target.enabled = account.id, payload.group_label, payload.enabled
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="这个机器人已经添加过该通知群") from exc
    if target.qq_group:
        await annotate_group(db, account.id, target.qq_group, target.group_label)
        await db.commit()
    if not await read_config(db, user.id):
        await save_config(db, user.id, GithubAutomationIn().model_dump())
    await mirror_primary_target(db, user.id)
    await reconcile_rules(db, user.id)
    scheduler_service.request_activity_sync()
    await audit(db, user_id=user.id, username=user.username, action="save_notification_target", target=target.group_label)
    return await subscription_status(db, user.id)


@router.post("/targets", status_code=201)
async def add_target(payload: GithubNotificationTargetIn, db: AsyncSession = Depends(get_db), user: User = Depends(require("push:manage"))):
    return await persist_target(db, user, payload)


@router.put("/targets/{target_id}")
async def edit_target(target_id: int, payload: GithubNotificationTargetIn, db: AsyncSession = Depends(get_db), user: User = Depends(require("push:manage"))):
    return await persist_target(db, user, payload, await owned_target(db, user, target_id))


@router.delete("/targets/{target_id}")
async def remove_target(target_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("push:manage"))):
    target = await owned_target(db, user, target_id)
    label = target.group_label
    # Retain delivery history. Only this target's rules are stopped and detached.
    await db.execute(update(PushRule).where(PushRule.notification_target_id == target.id, PushRule.managed_by_user_id == user.id)
                     .values(enabled=False, notification_target_id=None))
    await db.execute(delete(SystemSetting).where(SystemSetting.key.startswith("github_group_bind:"), SystemSetting.value["target_id"].as_integer() == target.id))
    await db.delete(target)
    await db.commit()
    await mirror_primary_target(db, user.id)
    await reconcile_rules(db, user.id)
    await audit(db, user_id=user.id, username=user.username, action="remove_notification_target", target=label)
    return await subscription_status(db, user.id)


@router.post("/sync")
async def sync(db: AsyncSession = Depends(get_db), user: User = Depends(require("github:manage"))):
    value = await read_config(db, user.id)
    if not value.get("enabled"):
        raise HTTPException(status_code=400, detail="请先保存并启用通知设置")
    value.update(sync_requested=True, sync_status="queued")
    await save_config(db, user.id, value)
    scheduler_service.request_activity_sync()
    return {"message": "已安排后台同步，可在本页查看结果"}


@router.post("/binding-code")
async def binding_code(target_id: int | None = None, db: AsyncSession = Depends(get_db), user: User = Depends(require("push:manage"))):
    try:
        return await make_binding_code(db, user.id, target_id)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/targets/{target_id}/permissions")
async def check_group_permission(target_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("push:manage"))):
    from app.services.account_manager import account_manager

    target = await owned_target(db, user, target_id)
    account = await db.get(Account, target.account_id)
    if not account or account.protocol != "qq_official" or not target.qq_group:
        raise HTTPException(status_code=400, detail="此检查用于已绑定的 QQ 官方通知群")
    adapter = account_manager.adapter(account.id)
    if not adapter:
        raise HTTPException(status_code=400, detail="请先启动发送机器人")
    try:
        permission = await adapter.get_group_bot_state(target.qq_group)
    except Exception as exc:  # noqa: BLE001
        await save_group_permission(db, target, allowed=None, error=str(exc))
        raise HTTPException(status_code=400, detail=f"无法读取群权限：{str(exc)[:240]}") from exc
    await save_group_permission(db, target, allowed=permission["allow_proactive_msg"])
    return await subscription_status(db, user.id)


@router.post("/test")
async def test_delivery(target_id: int | None = None, db: AsyncSession = Depends(get_db), user: User = Depends(require("push:manage"))):
    from app.services.account_manager import account_manager

    try:
        target = await get_target(db, user.id, target_id)
    except OAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    account = await db.get(Account, target.account_id)
    if not account or not target.qq_group:
        raise HTTPException(status_code=400, detail="请先完成通知群绑定")
    if account.protocol != "qq_official":
        raise HTTPException(status_code=400, detail="请选择 QQ 官方机器人")
    try:
        await account_manager.send_group_message(account.id, target.qq_group, f"【GitHub 主动通知测试】\n通知群：{target.group_label}\n这是没有收到群消息时的主动投递测试。仓库授权与同步状态请在后台查看。", proactive_only=True)
    except Exception as exc:  # noqa: BLE001
        await save_delivery_probe(db, target, ok=False, error=str(exc))
        raise HTTPException(status_code=400, detail=f"测试消息发送失败：{str(exc)[:240]}") from exc
    await save_delivery_probe(db, target, ok=True)
    if account.protocol == "qq_official":
        # A successful no-context send is fresher evidence than a cached disabled setting.
        await save_group_permission(db, target, allowed=True)
    await audit(db, user_id=user.id, username=user.username, action="test_github_notifications", target=target.group_label)
    return {"message": "测试消息已发送，请到通知群确认"}
