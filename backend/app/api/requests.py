"""好友 / 加群申请审核 API。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, UnsupportedAction
from app.api.deps import client_ip, require
from app.db.session import get_db
from app.models import Account, BotRequest, User
from app.schemas.account import BotRequestDecision, BotRequestOut
from app.schemas.common import Page
from app.services.account_manager import account_manager
from app.services.logs import audit, write_log

router = APIRouter(prefix="/requests", tags=["申请审核"])


def serialize_request(row: BotRequest, account_name: str | None) -> BotRequestOut:
    return BotRequestOut(
        id=row.id,
        account_id=row.account_id,
        account_name=account_name,
        request_type=row.request_type,
        sub_type=row.sub_type,
        flag=row.flag,
        user_id=row.user_id,
        group_id=row.group_id,
        comment=row.comment,
        status=row.status,
        handled_by=row.handled_by,
        handled_at=row.handled_at,
        decision_reason=row.decision_reason,
        created_at=row.created_at,
    )


@router.get("", response_model=Page[BotRequestOut])
async def list_requests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    account_id: int | None = None,
    request_type: str | None = None,
    status: str | None = "pending",
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("request:view")),
):
    if request_type not in {None, "group", "friend"}:
        raise HTTPException(status_code=422, detail="request_type 仅支持 group / friend")
    if status not in {None, "pending", "approved", "rejected"}:
        raise HTTPException(status_code=422, detail="status 仅支持 pending / approved / rejected")
    query = select(BotRequest)
    if account_id:
        query = query.where(BotRequest.account_id == account_id)
    if request_type:
        query = query.where(BotRequest.request_type == request_type)
    if status:
        query = query.where(BotRequest.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        await db.scalars(
            query.order_by(BotRequest.created_at.desc(), BotRequest.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    accounts = {a.id: a.name for a in await db.scalars(select(Account))}
    return Page(
        items=[serialize_request(row, accounts.get(row.account_id)) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{request_id}/decision", response_model=BotRequestOut)
async def decide_request(
    request_id: int,
    payload: BotRequestDecision,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("request:manage")),
):
    row = await db.get(BotRequest, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="申请记录不存在")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="该申请已处理，不能重复审核")
    adapter = account_manager.adapter(row.account_id)
    if not adapter:
        raise HTTPException(status_code=409, detail="申请所属账号当前离线，记录保持待审核")
    action = "set_group_add_request" if row.request_type == "group" else "set_friend_add_request"
    if not adapter.supports(action):
        raise HTTPException(status_code=501, detail="当前协议端不支持处理该类型申请")
    try:
        if row.request_type == "group":
            await account_manager.invoke(
                row.account_id,
                action,
                flag=row.flag,
                sub_type=row.sub_type,
                approve=payload.approve,
                reason=payload.reason,
            )
        else:
            await account_manager.invoke(
                row.account_id,
                action,
                flag=row.flag,
                approve=payload.approve,
                remark=payload.remark,
            )
    except (AdapterError, UnsupportedAction) as exc:
        raise HTTPException(status_code=502, detail=f"协议端未能处理申请，记录保持待审核：{exc}") from exc

    row.status = "approved" if payload.approve else "rejected"
    row.handled_by = user.username
    row.handled_at = datetime.now(timezone.utc)
    row.decision_reason = payload.reason or None
    await db.commit()
    await db.refresh(row)
    await write_log(
        db,
        level="INFO",
        category="request",
        message=f"{('加群' if row.request_type == 'group' else '好友')}申请已{('通过' if payload.approve else '拒绝')}：用户 {row.user_id}",
        account_id=row.account_id,
        context={"request_id": row.id, "group_id": row.group_id, "operator": user.username},
    )
    await audit(
        db,
        user_id=user.id,
        username=user.username,
        action="approve_bot_request" if payload.approve else "reject_bot_request",
        target=f"request:{row.id}",
        detail=f"type={row.request_type}, user_id={row.user_id}, group_id={row.group_id}",
        ip=client_ip(request),
    )
    account = await db.get(Account, row.account_id)
    return serialize_request(row, account.name if account else None)
