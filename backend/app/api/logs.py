"""日志中心 API（支持筛选、搜索、分页、清理）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.api.pagination import PageParam, PageSizeParam
from app.db.session import get_db
from app.models import SystemLog, User
from app.schemas.common import MessageOut, Page
from app.schemas.task import LogOut
from app.services.logs import audit

router = APIRouter(prefix="/logs", tags=["日志"])

CATEGORIES = [
    {"value": "system", "label": "系统日志"},
    {"value": "qq", "label": "QQ 连接日志"},
    {"value": "message", "label": "QQ 消息日志"},
    {"value": "ai", "label": "AI 请求日志"},
    {"value": "github", "label": "GitHub 监控日志"},
    {"value": "push", "label": "推送日志"},
    {"value": "task", "label": "任务日志"},
    {"value": "moderation", "label": "自动管理日志"},
    {"value": "command", "label": "命令日志"},
    {"value": "group", "label": "群操作日志"},
    {"value": "account", "label": "账号操作日志"},
    {"value": "auth", "label": "登录日志"},
    {"value": "error", "label": "错误日志"},
]


@router.get("/categories")
async def categories(_: User = Depends(require("log:view"))):
    return CATEGORIES


@router.get("", response_model=Page[LogOut])
async def list_logs(
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    category: str | None = None,
    level: str | None = None,
    keyword: str | None = None,
    account_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("log:view")),
):
    query = select(SystemLog)
    if category:
        query = query.where(SystemLog.category == category)
    if level:
        query = query.where(SystemLog.level == level.upper())
    if keyword:
        query = query.where(SystemLog.message.ilike(f"%{keyword}%"))
    if account_id:
        query = query.where(SystemLog.account_id == account_id)
    if start:
        query = query.where(SystemLog.created_at >= start)
    if end:
        query = query.where(SystemLog.created_at <= end)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(query.order_by(SystemLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[LogOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.delete("/cleanup", response_model=MessageOut)
async def cleanup_logs(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("system:manage")),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await db.scalars(select(SystemLog).where(SystemLog.created_at < cutoff))
    items = list(rows)
    for item in items:
        await db.delete(item)
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="cleanup_logs", detail=f"删除 {len(items)} 条，保留 {days} 天")
    return MessageOut(detail=f"已清理 {len(items)} 条历史日志")
