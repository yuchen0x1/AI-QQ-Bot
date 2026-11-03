"""消息记录与手动发送。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, UnsupportedAction
from app.api.deps import require
from app.db.session import get_db
from app.models import Account, Message, User
from app.schemas.account import MessageOut, SendMessageRequest
from app.schemas.common import Page
from app.services.account_manager import account_manager
from app.services.logs import write_log

router = APIRouter(prefix="/messages", tags=["消息"])


@router.get("", response_model=Page[MessageOut])
async def list_messages(
    page: int = 1,
    page_size: int = 20,
    account_id: int | None = None,
    qq_group: int | None = None,
    direction: str | None = None,
    keyword: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    blocked: bool | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("message:view")),
):
    query = select(Message)
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
    rows = await db.scalars(query.order_by(Message.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[MessageOut.model_validate(m) for m in rows], total=total, page=page, page_size=page_size)


@router.post("/send")
async def send_message(
    payload: SendMessageRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require("message:send"))
):
    account = await db.get(Account, payload.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if (payload.qq_group is None) == (payload.user_id is None):
        raise HTTPException(status_code=400, detail="请且只能指定群号或用户 QQ 之一")
    try:
        if payload.qq_group:
            result = await account_manager.send_group_message(account.id, payload.qq_group, payload.content)
            target = f"群 {payload.qq_group}"
        else:
            result = await account_manager.send_private_message(account.id, payload.user_id, payload.content)
            target = f"用户 {payload.user_id}"
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
    from datetime import timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await db.execute(
        select(func.date(Message.created_at), Message.direction, func.count(Message.id))
        .where(Message.created_at >= since)
        .group_by(func.date(Message.created_at), Message.direction)
    )
    buckets: dict[str, dict[str, int]] = {}
    for day, direction, count in rows.all():
        key = str(day)
        buckets.setdefault(key, {"date": key, "in": 0, "out": 0})
        buckets[key][direction] = count
    return sorted(buckets.values(), key=lambda item: item["date"])
