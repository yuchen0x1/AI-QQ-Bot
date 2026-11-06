"""系统日志与审计日志写入。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
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
    item = {
        "id": record.id,
        "time": record.created_at.isoformat() if record.created_at else None,
        "level": record.level,
        "category": record.category,
        "account_id": record.account_id,
        "message": safe_message,
    }
    # 旧日志 Hub 保留，统一事件总线同时提供跨业务 WS 事件格式。
    hub.publish(item)
    publish_event("log.created", item, event_id=str(record.id) if record.id else None)

    # 错误级别日志异步触发第三方告警
    if record.level in ("ERROR", "CRITICAL"):
        try:
            import asyncio
            from app.services.alerting import send_alert
            asyncio.create_task(
                send_alert(
                    title=f"系统错误 [{record.category}]",
                    content=f"账号: {record.account_id or '全局'}\n详情: {record.message}",
                )
            )
        except Exception:  # noqa: BLE001
            pass

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
