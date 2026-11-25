"""消息记录与手动发送。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, UnsupportedAction
from app.api.deps import require
from app.api.pagination import PageParam, PageSizeParam
from app.core.timeutil import date_bucket
from app.db.session import get_db
from app.models import Account, Group, Message, QQOfficialIdentity, User
from app.schemas.account import MessageOut, SendMessageRequest
from app.schemas.common import Page
from app.services.account_manager import account_manager
from app.services.logs import write_log
from app.services.group_display import group_labels

router = APIRouter(prefix="/messages", tags=["消息"])


@router.get("", response_model=Page[MessageOut])
async def list_messages(
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    account_id: int | None = None,
    qq_group: int | None = None,
    direction: str | None = None,
    keyword: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    blocked: bool | None = None,
    after_id: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("message:view")),
):
    query = select(Message)
    if after_id is not None:
        query = query.where(Message.id > after_id)
    if account_id:
        query = query.where(Message.account_id == account_id)
    if qq_group:
        query = query.where(Message.qq_group == qq_group)
    if direction in {"in", "out"}:
        query = query.where(Message.direction == direction)
    if keyword:
        query = query.where(Message.content.ilike(f"%{keyword}%"))
    if start:
        query = query.where(Message.created_at >= start)
    if end:
        query = query.where(Message.created_at <= end)
    if blocked is not None:
        query = query.where(Message.blocked.is_(blocked))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    # Ascending cursor batches drain a busy inbox without skipping messages beyond
    # the page size. Normal history remains newest-first for old clients.
    ordering = Message.id.asc() if after_id is not None else Message.id.desc()
    rows = await db.scalars(query.order_by(ordering).offset((page - 1) * page_size).limit(page_size))
    labels = await group_labels(db)
    items = []
    for message in rows:
        item = MessageOut.model_validate(message)
        label = labels.get((message.account_id, message.qq_group), {})
        item.group_display_number = label.get("number")
        item.group_display_name = label.get("name")
        items.append(item)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/contacts")
async def list_contacts(
    account_id: int,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("message:view")),
):
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    query = select(QQOfficialIdentity).where(
        QQOfficialIdentity.account_id == account_id,
        QQOfficialIdentity.kind == "user",
        QQOfficialIdentity.scope == "",
    )
    if keyword:
        condition = QQOfficialIdentity.display_name.ilike(f"%{keyword}%")
        if keyword.isdigit():
            condition = condition | (QQOfficialIdentity.id == int(keyword))
        query = query.where(condition)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(query.order_by(QQOfficialIdentity.id).offset((page - 1) * page_size).limit(page_size))
    return {
        "items": [
            {"id": row.id, "display_name": row.display_name, "last_seen_at": row.last_seen_at,
             "identifier_kind": "internal_mapping_id"}
            for row in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/send")
async def send_message(
    payload: SendMessageRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require("message:send"))
):
    account = await db.get(Account, payload.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if (payload.qq_group is None) == (payload.user_id is None):
        raise HTTPException(status_code=400, detail="请且只能指定群聊或已登记私聊联系人之一")
    if payload.qq_group is not None:
        target_exists = await db.scalar(select(Group.id).where(
            Group.account_id == account.id, Group.group_number == payload.qq_group,
        ))
    else:
        target_exists = await db.scalar(select(QQOfficialIdentity.id).where(
            QQOfficialIdentity.account_id == account.id, QQOfficialIdentity.kind == "user",
            QQOfficialIdentity.scope == "", QQOfficialIdentity.id == payload.user_id,
        ))
    if target_exists is None:
        raise HTTPException(status_code=422, detail="发送目标未在该账号登记，请先让机器人收到目标消息")
    capability = "send_group_message" if payload.qq_group is not None else "send_private_message"
    if not account_manager.is_online(account.id):
        raise HTTPException(status_code=409, detail="发送账号当前离线，消息未发送")
    if not account_manager.capabilities(account.id).get(capability):
        raise HTTPException(status_code=501, detail="当前账号不支持此消息类型")
    try:
        if payload.qq_group:
            result = await account_manager.send_group_message(account.id, payload.qq_group, payload.content)
            labels = await group_labels(db)
            label = labels.get((account.id, payload.qq_group), {})
            target = f"群 {label['number']}" if label.get("number") else label.get("name") or "所选群聊"
        else:
            result = await account_manager.send_private_message(account.id, payload.user_id, payload.content)
            target = f"私聊联系人（内部映射 ID {payload.user_id}）"
    except UnsupportedAction as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except AdapterError as exc:
        raise HTTPException(status_code=502, detail=f"发送失败：{exc}") from exc

    db.add(
        Message(
            account_id=account.id,
            qq_group=payload.qq_group,
            message_id=(result.get("data") or {}).get("message_id"),
            direction="out",
            message_type="group" if payload.qq_group else "private",
            sender_id=account.qq_number,
            sender_name=account.nickname or account.name,
            content=payload.content,
        )
    )
    await db.commit()
    await write_log(
        db,
        level="INFO",
        category="qq",
        message=f"后台手动发送消息到{target}（操作者 {user.username}）",
        account_id=account.id,
    )
    return {"ok": True, "message": f"已发送到{target}", "data": result.get("data")}


@router.get("/stats")
async def message_stats(
    days: int = Query(default=7, ge=1, le=30), db: AsyncSession = Depends(get_db), _: User = Depends(require("message:view"))
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    day_expr = date_bucket(Message.created_at, db.bind.dialect.name if db.bind is not None else "sqlite")
    rows = await db.execute(
        select(day_expr, Message.direction, func.count(Message.id))
        .where(Message.created_at >= since)
        .group_by(day_expr, Message.direction)
    )
    buckets: dict[str, dict[str, int]] = {}
    for day, direction, count in rows.all():
        key = str(day)
        buckets.setdefault(key, {"date": key, "in": 0, "out": 0})
        buckets[key][direction] = count
    return sorted(buckets.values(), key=lambda item: item["date"])
