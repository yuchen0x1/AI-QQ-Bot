"""系统日志与审计日志写入。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import hub, mask_text
from app.models import AuditLog, SystemLog

logger = logging.getLogger("qbot")


async def write_log(
    db: AsyncSession,
    *,
    level: str,
    category: str,
    message: str,
    account_id: int | None = None,
    context: dict[str, Any] | None = None,
    commit: bool = True,
) -> SystemLog:
    safe_message = mask_text(message)
    record = SystemLog(
        level=level.upper(),
        category=category,
        account_id=account_id,
        message=safe_message,
        context=context,
    )
    db.add(record)
    if commit:
        await db.commit()
        await db.refresh(record)
    hub.publish(
        {
            "id": record.id,
            "time": record.created_at.isoformat() if record.created_at else None,
            "level": record.level,
            "category": record.category,
            "account_id": record.account_id,
            "message": safe_message,
        }
    )
    return record


async def audit(
    db: AsyncSession,
    *,
    user_id: int | None,
    username: str | None,
    action: str,
    target: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            target=target,
            detail=detail,
            ip=ip,
        )
    )
    await db.commit()
