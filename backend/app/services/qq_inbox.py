"""Durable QQ dispatch acceptance and recoverable processing claims.

An interrupted outbound request can have an unknown platform result. Such a
dispatch becomes uncertain and requires operator review instead of blind replay.
This is at-least-once input handling, not exactly-once external delivery.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.session import SessionLocal
from app.models.account import QQEventInbox

LEASE_SECONDS = 300
MAX_ATTEMPTS = 5


def event_key(payload: dict[str, Any]) -> str:
    data = payload.get("d") or {}
    if not isinstance(data, dict):
        data = {}
    identity = data.get("id") or payload.get("id")
    index = [item for item in (data.get("message_scene") or {}).get("ext", [])
             if isinstance(item, str) and item.startswith("msg_idx=")]
    material = [payload.get("t"), identity, index]
    if not identity:
        material.append(data)
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def accept(account_id: int, payload: dict[str, Any]) -> tuple[int, str]:
    key = event_key(payload)
    async with SessionLocal() as db:
        insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
        await db.execute(insert(QQEventInbox).values(
            account_id=account_id, event_key=key, payload=payload, status="pending", attempts=0,
            side_effect_started=False,
        ).on_conflict_do_nothing(index_elements=["account_id", "event_key"]))
        await db.commit()
        row = await db.scalar(select(QQEventInbox).where(
            QQEventInbox.account_id == account_id, QQEventInbox.event_key == key,
        ))
        if not row:
            raise RuntimeError("QQ inbox acceptance was not persisted")
        return row.id, row.status


async def claim(inbox_id: int) -> str | None:
    now = datetime.now(timezone.utc)
    token = uuid4().hex
    async with SessionLocal() as db:
        # Never replay an interrupted external side effect automatically.
        await db.execute(update(QQEventInbox).where(
            QQEventInbox.id == inbox_id, QQEventInbox.status == "processing",
            QQEventInbox.lease_until <= now, QQEventInbox.side_effect_started.is_(True),
        ).values(status="uncertain", last_error="interrupted outbound operation; review platform delivery before replay"))
        await db.execute(update(QQEventInbox).where(
            QQEventInbox.id == inbox_id, QQEventInbox.attempts >= MAX_ATTEMPTS,
            or_(QQEventInbox.status == "pending", (QQEventInbox.status == "processing") & (QQEventInbox.lease_until <= now)),
        ).values(status="dead", last_error="QQ inbox attempts exhausted"))
        result = await db.execute(update(QQEventInbox).where(
            QQEventInbox.id == inbox_id, QQEventInbox.attempts < MAX_ATTEMPTS,
            or_(QQEventInbox.status == "pending", (QQEventInbox.status == "processing") &
                (QQEventInbox.lease_until <= now) & QQEventInbox.side_effect_started.is_(False)),
        ).values(status="processing", claim_id=token, lease_until=now + timedelta(seconds=LEASE_SECONDS),
                 attempts=QQEventInbox.attempts + 1, last_error=None))
        await db.commit()
        return token if result.rowcount == 1 else None


async def renew(inbox_id: int, token: str) -> bool:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        result = await db.execute(update(QQEventInbox).where(
            QQEventInbox.id == inbox_id, QQEventInbox.claim_id == token,
            QQEventInbox.status == "processing", QQEventInbox.lease_until > now,
        ).values(lease_until=now + timedelta(seconds=LEASE_SECONDS)))
        await db.commit()
        return result.rowcount == 1


async def begin_side_effect(inbox_id: int, token: str) -> None:
    async with SessionLocal() as db:
        result = await db.execute(update(QQEventInbox).where(
            QQEventInbox.id == inbox_id, QQEventInbox.claim_id == token,
            QQEventInbox.status == "processing", QQEventInbox.lease_until > datetime.now(timezone.utc),
        ).values(side_effect_started=True))
        await db.commit()
        if result.rowcount != 1:
            raise RuntimeError("QQ inbox claim was lost before outbound operation")


async def finish(inbox_id: int, token: str, *, error: str | None = None) -> None:
    async with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {"lease_until": None}
        if error:
            values.update(
                status=case((QQEventInbox.side_effect_started.is_(True), "uncertain"),
                            (QQEventInbox.attempts >= MAX_ATTEMPTS, "dead"), else_="pending"),
                last_error=error[:500],
            )
        else:
            values.update(status="success", completed_at=now)
        await db.execute(update(QQEventInbox).where(
            QQEventInbox.id == inbox_id, QQEventInbox.claim_id == token, QQEventInbox.status == "processing",
            QQEventInbox.lease_until > now,
        ).values(**values))
        await db.commit()


async def pending(account_id: int, *, limit: int = 100) -> list[tuple[int, dict[str, Any]]]:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        rows = await db.scalars(select(QQEventInbox).where(
            QQEventInbox.account_id == account_id,
            or_(QQEventInbox.status == "pending", (QQEventInbox.status == "processing") & (QQEventInbox.lease_until <= now)),
        ).order_by(QQEventInbox.id).limit(limit))
        return [(row.id, row.payload) for row in rows]


class EventAdapter:
    """Preserve a claim before invoking any external adapter side effect."""

    def __init__(self, adapter: Any, inbox_id: int, token: str) -> None:
        self.adapter = adapter
        self.inbox_id = inbox_id
        self.token = token

    def __getattr__(self, name: str):
        value = getattr(self.adapter, name)
        if callable(value) and (name.startswith(("send_", "set_")) or name == "delete_msg"):
            async def invoke(*args, **kwargs):
                await begin_side_effect(self.inbox_id, self.token)
                return await value(*args, **kwargs)
            return invoke
        return value
