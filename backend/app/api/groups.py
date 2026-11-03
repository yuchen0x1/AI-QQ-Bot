"""群聊管理：群列表、成员、群配置、管理操作（全部经服务器端权限与协议能力校验）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, UnsupportedAction
from app.api.deps import client_ip, require
from app.db.session import get_db
from app.models import Account, Group, GroupMember, GroupSettings, User
from app.schemas.account import (
    GroupActionOut,
    GroupActionRequest,
    GroupMemberOut,
    GroupOut,
    GroupSettingsOut,
    GroupSettingsUpdate,
)
from app.schemas.common import MessageOut, Page
from app.services.account_manager import account_manager
from app.services.logs import audit, write_log

router = APIRouter(prefix="/groups", tags=["群聊"])


async def _get_group(db: AsyncSession, group_db_id: int) -> Group:
    group = await db.get(Group, group_db_id)
    if not group:
        raise HTTPException(status_code=404, detail="群不存在")
    return group


async def ensure_settings(db: AsyncSession, group: Group) -> GroupSettings:
    settings = await db.scalar(select(GroupSettings).where(GroupSettings.group_id == group.id))
    if not settings:
        settings = GroupSettings(group_id=group.id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


def serialize_group(group: Group, account_name: str | None = None) -> GroupOut:
    return GroupOut(
        id=group.id,
        account_id=group.account_id,
        group_number=group.group_number,
        name=group.name,
        member_count=group.member_count,
        max_member_count=group.max_member_count,
        owner_id=group.owner_id,
        last_synced_at=group.last_synced_at,
        settings=GroupSettingsOut.model_validate(group.settings) if group.settings else None,
        account_name=account_name,
    )


@router.get("", response_model=Page[GroupOut])
async def list_groups(
    page: int = 1,
    page_size: int = 20,
    account_id: int | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("group:view")),
):
    query = select(Group)
    if account_id:
        query = query.where(Group.account_id == account_id)
    if keyword:
        condition = Group.name.ilike(f"%{keyword}%")
        if keyword.isdigit():
            condition = condition | (Group.group_number == int(keyword))
        query = query.where(condition)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(await db.scalars(query.order_by(Group.id.desc()).offset((page - 1) * page_size).limit(page_size)))
    accounts = {a.id: a.name for a in await db.scalars(select(Account))}
    return Page(
        items=[serialize_group(g, accounts.get(g.account_id)) for g in rows], total=total, page=page, page_size=page_size
    )


@router.get("/{group_db_id}", response_model=GroupOut)
async def get_group(group_db_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("group:view"))):
    group = await _get_group(db, group_db_id)
    account = await db.get(Account, group.account_id)
    return serialize_group(group, account.name if account else None)


@router.put("/{group_db_id}/settings", response_model=GroupSettingsOut)
async def update_group_settings(
    group_db_id: int,
    payload: GroupSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("group:manage")),
):
    group = await _get_group(db, group_db_id)
    settings = await ensure_settings(db, group)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    await db.commit()
    await db.refresh(settings)
    await audit(
        db,
        user_id=user.id,
        username=user.username,
        action="update_group_settings",
        target=str(group.group_number),
        detail=str(payload.model_dump(exclude_unset=True)),
        ip=client_ip(request),
    )
    return GroupSettingsOut.model_validate(settings)


@router.get("/{group_db_id}/members", response_model=Page[GroupMemberOut])
async def list_members(
    group_db_id: int,
    page: int = 1,
    page_size: int = 50,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("group:view")),
):
    group = await _get_group(db, group_db_id)
    query = select(GroupMember).where(GroupMember.group_id == group.id)
    if keyword:
        condition = GroupMember.nickname.ilike(f"%{keyword}%")
        if keyword.isdigit():
            condition = condition | (GroupMember.user_id == int(keyword))
        query = query.where(condition)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(
        query.order_by(GroupMember.role.asc(), GroupMember.id).offset((page - 1) * page_size).limit(page_size)
    )
    return Page(
        items=[GroupMemberOut.model_validate(m) for m in rows], total=total, page=page, page_size=page_size
    )


@router.post("/{group_db_id}/sync", response_model=MessageOut)
async def sync_members(
    group_db_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("group:manage"))
):
    group = await _get_group(db, group_db_id)
    try:
        count = await account_manager.sync_group_members(group.account_id, group.group_number)
    except AdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit(db, user_id=user.id, username=user.username, action="sync_members", target=str(group.group_number))
    return MessageOut(detail=f"已同步 {count} 名群成员")


@router.post("/sync/{account_db_id}", response_model=MessageOut)
async def sync_groups(
    account_db_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("group:manage"))
):
    account = await db.get(Account, account_db_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    try:
        count = await account_manager.sync_groups(account_db_id)
    except AdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit(db, user_id=user.id, username=user.username, action="sync_groups", target=account.name)
    return MessageOut(detail=f"已同步 {count} 个群")


@router.post("/{group_db_id}/action", response_model=GroupActionOut)
async def group_action(
    group_db_id: int,
    payload: GroupActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("group:manage")),
):
    group = await _get_group(db, group_db_id)
    settings = await ensure_settings(db, group)
    action = payload.action

    if action in {"mute", "unmute", "kick", "set_card", "set_group_name", "set_announcement", "recall", "set_admin", "unset_admin"}:
        if not group.account_id:
            raise HTTPException(status_code=400, detail="群未绑定账号")
    if action in {"mute", "unmute", "kick", "set_card", "set_admin", "unset_admin"} and not payload.user_id:
        raise HTTPException(status_code=400, detail="该操作需要指定成员 user_id")
    if action in {"set_card", "set_group_name", "set_announcement"} and payload.value is None:
        raise HTTPException(status_code=400, detail="该操作需要提供 value")
    if action == "recall" and not payload.message_id:
        raise HTTPException(status_code=400, detail="撤回操作需要 message_id")

    calls: dict[str, tuple[str, dict]] = {
        "mute": ("set_group_ban", {"group_id": group.group_number, "user_id": payload.user_id, "duration": payload.duration_seconds or 600}),
        "unmute": ("set_group_ban", {"group_id": group.group_number, "user_id": payload.user_id, "duration": 0}),
        "ban_all": ("set_group_whole_ban", {"group_id": group.group_number, "enable": True}),
        "unban_all": ("set_group_whole_ban", {"group_id": group.group_number, "enable": False}),
        "kick": ("set_group_kick", {"group_id": group.group_number, "user_id": payload.user_id}),
        "set_card": ("set_group_card", {"group_id": group.group_number, "user_id": payload.user_id, "card": payload.value}),
        "set_group_name": ("set_group_name", {"group_id": group.group_number, "name": payload.value}),
        "set_announcement": ("set_group_announce", {"group_id": group.group_number, "content": payload.value}),
        "recall": ("delete_msg", {"message_id": payload.message_id}),
        "set_admin": ("set_group_admin", {"group_id": group.group_number, "user_id": payload.user_id, "enable": True}),
        "unset_admin": ("set_group_admin", {"group_id": group.group_number, "user_id": payload.user_id, "enable": False}),
    }
    method, params = calls[action]
    adapter = account_manager.adapter(group.account_id)
    if not adapter:
        raise HTTPException(status_code=400, detail="该群所属账号当前离线，操作未执行")
    if not adapter.supports(method):
        raise HTTPException(status_code=501, detail=f"当前协议端不支持「{method}」，操作未执行")

    try:
        response = await account_manager.invoke(group.account_id, method, **params)
    except UnsupportedAction as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except AdapterError as exc:
        raise HTTPException(status_code=502, detail=f"协议端执行失败：{exc}") from exc

    if action == "set_announcement":
        settings.announcement = payload.value
        await db.commit()
    if action == "set_group_name":
        group.name = payload.value
        await db.commit()
    if action == "mute" and payload.user_id:
        member = await db.scalar(
            select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == payload.user_id)
        )
        if member:
            from datetime import datetime, timedelta, timezone

            member.muted_until = datetime.now(timezone.utc) + timedelta(seconds=payload.duration_seconds or 600)
            await db.commit()

    await write_log(
        db,
        level="INFO",
        category="group",
        message=f"群 {group.group_number} 执行管理操作：{action}（操作者 {user.username}）",
        account_id=group.account_id,
        context={"action": action, "params": params},
    )
    await audit(
        db,
        user_id=user.id,
        username=user.username,
        action=f"group_{action}",
        target=str(group.group_number),
        detail=str(params),
        ip=client_ip(request),
    )
    labels = {
        "mute": "已禁言",
        "unmute": "已解除禁言",
        "ban_all": "已开启全体禁言",
        "unban_all": "已解除全体禁言",
        "kick": "已踢出成员",
        "set_card": "已更新群名片",
        "set_group_name": "已更新群名称",
        "set_announcement": "已发布群公告",
        "recall": "已撤回消息",
        "set_admin": "已设置管理员",
        "unset_admin": "已取消管理员",
    }
    return GroupActionOut(ok=True, action=action, message=labels.get(action, "操作已完成"), provider_response=response)


@router.post("/{group_db_id}/members/{user_id}/flags", response_model=GroupMemberOut)
async def update_member_flags(
    group_db_id: int,
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("group:manage")),
):
    group = await _get_group(db, group_db_id)
    member = await db.scalar(
        select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == user_id)
    )
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在，请先同步群成员")
    for field in ("is_blacklisted", "is_whitelisted"):
        if field in payload:
            setattr(member, field, bool(payload[field]))
    if payload.get("reset_warnings"):
        member.warn_count = 0
    await db.commit()
    await db.refresh(member)
    await audit(
        db, user_id=user.id, username=user.username, action="update_member_flags", target=f"{group.group_number}/{user_id}"
    )
    return GroupMemberOut.model_validate(member)
