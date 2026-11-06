"""QQ 官方机器人 OpenID 映射服务。

官方平台对外只暴露字符串 OpenID，而本项目历史数据模型统一使用整数 QQ 号 / 群号。
这里提供稳定的双向映射，保证同一个 OpenID 在任何时候都得到同一个整数 ID，
从而让 BotEngine、群管理、AI 会话、消息统计等上层模块保持零改动。
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models import QQOfficialIdentity

logger = logging.getLogger("qbot.qq_identity")


def stable_int(value: str) -> int:
    """把字符串 ID 稳定映射为正的 63 位整数（用于 BigInteger 字段）。"""
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFFFFFFFFFF


async def _resolve_in_session(
    db: AsyncSession,
    account_id: int,
    kind: str,
    openid: str,
    *,
    scope: str = "",
    display_name: str | None = None,
) -> int:
    row = await db.scalar(
        select(QQOfficialIdentity).where(
            QQOfficialIdentity.account_id == account_id,
            QQOfficialIdentity.kind == kind,
            QQOfficialIdentity.scope == scope,
            QQOfficialIdentity.openid == openid,
        )
    )
    if row:
        if display_name and display_name != row.display_name:
            row.display_name = display_name
        row.last_seen_at = datetime.now(timezone.utc)
        await db.commit()
        return int(row.id)
    row = QQOfficialIdentity(
        account_id=account_id,
        kind=kind,
        scope=scope,
        openid=openid,
        display_name=display_name,
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    await db.commit()
    return int(row.id)


async def resolve(
    account_id: int,
    kind: str,
    openid: str,
    *,
    scope: str = "",
    display_name: str | None = None,
) -> int:
    """返回 OpenID 对应的内部整数 ID；不存在则创建。并发插入冲突会自动重查。"""
    if not openid:
        raise ValueError("openid 不能为空")
    try:
        async with SessionLocal() as db:
            return await _resolve_in_session(
                db, account_id, kind, openid, scope=scope, display_name=display_name
            )
    except IntegrityError:
        logger.debug("OpenID 并发插入冲突，改为重新查询: account=%s kind=%s", account_id, kind)
        async with SessionLocal() as db:
            return await _resolve_in_session(
                db, account_id, kind, openid, scope=scope, display_name=display_name
            )


async def get_openid(
    account_id: int, kind: str, numeric_id: int, *, scope: str | None = None
) -> str | None:
    async with SessionLocal() as db:
        query = select(QQOfficialIdentity).where(
            QQOfficialIdentity.account_id == account_id,
            QQOfficialIdentity.kind == kind,
            QQOfficialIdentity.id == numeric_id,
        )
        if scope is not None:
            query = query.where(QQOfficialIdentity.scope == scope)
        row = await db.scalar(query)
        return row.openid if row else None


async def list_identities(
    account_id: int, kind: str, *, scope: str | None = None
) -> list[dict[str, Any]]:
    async with SessionLocal() as db:
        query = select(QQOfficialIdentity).where(
            QQOfficialIdentity.account_id == account_id,
            QQOfficialIdentity.kind == kind,
        )
        if scope is not None:
            query = query.where(QQOfficialIdentity.scope == scope)
        rows = list(await db.scalars(query.order_by(QQOfficialIdentity.id)))
        return [
            {
                "id": int(row.id),
                "openid": row.openid,
                "scope": row.scope,
                "display_name": row.display_name,
                "last_seen_at": row.last_seen_at,
            }
            for row in rows
        ]
