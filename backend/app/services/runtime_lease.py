"""Atomic database leases shared by singleton runtime services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.task import RuntimeLease


async def acquire(name: str, token: str, *, seconds: int = 45) -> bool:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
        stmt = insert(RuntimeLease).values(
            name=name, owner=settings.runtime_instance_id, token=token, expires_at=now + timedelta(seconds=seconds)
        ).on_conflict_do_update(
            index_elements=[RuntimeLease.name],
            set_={"owner": settings.runtime_instance_id, "token": token, "expires_at": now + timedelta(seconds=seconds)},
            where=RuntimeLease.expires_at <= now,
        ).returning(RuntimeLease.name)
        owned = await db.scalar(stmt)
        await db.commit()
        return owned is not None


async def renew(name: str, token: str, *, seconds: int = 45) -> bool:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        result = await db.execute(update(RuntimeLease).where(
            RuntimeLease.name == name, RuntimeLease.token == token,
            RuntimeLease.owner == settings.runtime_instance_id, RuntimeLease.expires_at > now,
        ).values(expires_at=now + timedelta(seconds=seconds)))
        await db.commit()
        return result.rowcount == 1


async def release(name: str, token: str) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(RuntimeLease).where(RuntimeLease.name == name, RuntimeLease.token == token))
        await db.commit()
