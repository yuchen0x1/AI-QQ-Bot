"""Durable queue execution receipts for restart and ACK-loss recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.session import SessionLocal
from app.models.task import QueueExecution


async def begin(job_id: str, task_id: int, claim_id: str, *, seconds: int) -> str:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
        row = dict(job_id=job_id, task_id=task_id, claim_id=claim_id, status="processing",
                   lease_until=now + timedelta(seconds=seconds), updated_at=now)
        claimed = await db.scalar(insert(QueueExecution).values(**row).on_conflict_do_update(
            index_elements=[QueueExecution.job_id], set_=row,
            where=(QueueExecution.status != "success") & or_(QueueExecution.lease_until <= now, QueueExecution.status == "failed"),
        ).returning(QueueExecution.job_id))
        await db.commit()
        if claimed:
            return "claimed"
        existing = await db.get(QueueExecution, job_id)
        return "success" if existing and existing.status == "success" else "busy"


async def renew(job_id: str, claim_id: str, *, seconds: int) -> bool:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        result = await db.execute(update(QueueExecution).where(
            QueueExecution.job_id == job_id, QueueExecution.claim_id == claim_id,
            QueueExecution.status == "processing", QueueExecution.lease_until > now,
        ).values(lease_until=now + timedelta(seconds=seconds), updated_at=now))
        await db.commit()
        return result.rowcount == 1


async def finish(job_id: str, claim_id: str, *, success: bool, record_id: int | None = None) -> bool:
    async with SessionLocal() as db:
        result = await db.execute(update(QueueExecution).where(
            QueueExecution.job_id == job_id, QueueExecution.claim_id == claim_id,
            QueueExecution.status == "processing", QueueExecution.lease_until > datetime.now(timezone.utc),
        ).values(status="success" if success else "failed", record_id=record_id, updated_at=datetime.now(timezone.utc)))
        await db.commit()
        return result.rowcount == 1


async def succeeded(job_id: str) -> bool:
    async with SessionLocal() as db:
        return (await db.scalar(select(QueueExecution.status).where(QueueExecution.job_id == job_id))) == "success"
