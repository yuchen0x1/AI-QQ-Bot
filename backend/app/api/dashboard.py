"""仪表盘聚合数据。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.db.session import get_db
from app.models import (
    Account,
    AIUsageLog,
    GithubRelease,
    GithubRepository,
    Group,
    Message,
    PushRecord,
    SystemLog,
    TaskRecord,
    User,
)
from app.schemas.task import DashboardOut
from app.services.account_manager import account_manager

router = APIRouter(prefix="/dashboard", tags=["仪表盘"])


def _day_start(days_ago: int = 0) -> datetime:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("", response_model=DashboardOut)
async def dashboard(db: AsyncSession = Depends(get_db), _: User = Depends(require("account:view"))):
    today = _day_start()
    week_ago = _day_start(6)

    accounts = list(await db.scalars(select(Account)))
    online = sum(1 for a in accounts if account_manager.is_online(a.id))
    error = sum(1 for a in accounts if a.connection and a.connection.status == "error" and not account_manager.is_online(a.id))
    offline = len(accounts) - online - error

    groups_total = await db.scalar(select(func.count()).select_from(Group)) or 0
    messages_today = await db.scalar(select(func.count()).select_from(Message).where(Message.created_at >= today)) or 0
    sent_today = await db.scalar(
        select(func.count()).select_from(Message).where(Message.created_at >= today, Message.direction == "out")
    ) or 0
    ai_today = await db.scalar(
        select(func.count()).select_from(AIUsageLog).where(AIUsageLog.created_at >= today)
    ) or 0
    repos_total = await db.scalar(select(func.count()).select_from(GithubRepository)) or 0
    releases_today = await db.scalar(
        select(func.count()).select_from(GithubRelease).where(GithubRelease.detected_at >= today)
    ) or 0
    pushes_today = await db.scalar(
        select(func.count()).select_from(PushRecord).where(PushRecord.created_at >= today, PushRecord.status == "success")
    ) or 0
    failed_tasks = await db.scalar(
        select(func.count()).select_from(TaskRecord).where(TaskRecord.status == "failed", TaskRecord.started_at >= today)
    ) or 0

    total_push = await db.scalar(
        select(func.count()).select_from(PushRecord).where(PushRecord.created_at >= week_ago)
    ) or 0
    success_push = await db.scalar(
        select(func.count())
        .select_from(PushRecord)
        .where(PushRecord.created_at >= week_ago, PushRecord.status == "success")
    ) or 0
    success_rate = round(success_push / total_push * 100, 1) if total_push else 100.0

    message_rows = await db.execute(
        select(func.date(Message.created_at), Message.direction, func.count(Message.id))
        .where(Message.created_at >= week_ago)
        .group_by(func.date(Message.created_at), Message.direction)
    )
    msg_map: dict[str, dict[str, int]] = {}
    for day, direction, count in message_rows.all():
        key = str(day)
        msg_map.setdefault(key, {"date": key, "in": 0, "out": 0})
        msg_map[key][direction] = count

    ai_rows = await db.execute(
        select(func.date(AIUsageLog.created_at), func.count(AIUsageLog.id), func.sum(AIUsageLog.prompt_tokens + AIUsageLog.completion_tokens))
        .where(AIUsageLog.created_at >= week_ago)
        .group_by(func.date(AIUsageLog.created_at))
    )
    ai_map = {str(day): {"date": str(day), "calls": calls or 0, "tokens": int(tokens or 0)} for day, calls, tokens in ai_rows.all()}

    trend: list[dict] = []
    ai_trend: list[dict] = []
    for offset in range(6, -1, -1):
        day = (_day_start(offset)).date()
        key = str(day)
        trend.append(msg_map.get(key, {"date": key, "in": 0, "out": 0}))
        ai_trend.append(ai_map.get(key, {"date": key, "calls": 0, "tokens": 0}))

    status_rows = []
    for account in accounts:
        state = account_manager.get(account.id)
        status_rows.append(
            {
                "id": account.id,
                "name": account.name,
                "qq_number": account.qq_number,
                "nickname": account.nickname,
                "state": state.state if state else "stopped",
                "protocol": account.protocol,
                "app_id": account.app_id,
                "online_seconds": state.online_seconds if state else 0,
                "last_error": (account.connection.last_error if account.connection else None),
            }
        )

    log_rows = await db.scalars(select(SystemLog).order_by(SystemLog.id.desc()).limit(12))
    recent = [
        {
            "id": log.id,
            "level": log.level,
            "category": log.category,
            "message": log.message,
            "created_at": log.created_at,
        }
        for log in log_rows
    ]

    return DashboardOut(
        accounts_total=len(accounts),
        accounts_online=online,
        accounts_offline=max(0, offline),
        accounts_error=error,
        messages_today=messages_today,
        messages_sent_today=sent_today,
        ai_calls_today=ai_today,
        repos_total=repos_total,
        releases_today=releases_today,
        pushes_today=pushes_today,
        failed_tasks=failed_tasks,
        groups_total=groups_total,
        push_success_rate=success_rate,
        message_trend=trend,
        ai_trend=ai_trend,
        account_status=status_rows,
        recent_events=recent,
    )
