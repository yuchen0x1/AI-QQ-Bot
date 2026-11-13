"""Configurable failure email outbox with bounded retries and persisted results."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import secrets
import smtplib
import ssl

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.logging import mask_text
from app.core.security import decrypt_secret
from app.db.session import SessionLocal
from app.models import EmailAlert, SystemSetting

CONFIG_KEY = "email_alert_config"
PROFILE_KEY = "email_agent_profile"
DEFAULT = {"enabled": False, "provider": "agentmail", "recipient": "", "categories": ["task", "push", "github", "account"],
           "smtp_host": "", "smtp_port": 465, "smtp_security": "ssl", "smtp_username": "", "smtp_sender": ""}


async def config(db) -> dict:
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == CONFIG_KEY))
    return {**DEFAULT, **(row.value if row and isinstance(row.value, dict) else {})}


async def put_setting(db, key: str, value: dict, *, secret: bool = False) -> None:
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if row:
        row.value, row.is_secret = value, secret
    else:
        db.add(SystemSetting(key=key, value=value, is_secret=secret))
    await db.commit()


async def enqueue(db, *, title: str, body: str, category: str, force: bool = False, event_key: str | None = None) -> EmailAlert | None:
    cfg = await config(db)
    if not cfg["enabled"] or not cfg["recipient"] or (not force and category not in cfg["categories"]):
        return None
    safe_title, safe_body = mask_text(title)[:220], mask_text(body)[:8000]
    # The recipient participates in the key; configuring a new mailbox never replays old notices to it.
    bucket = int(datetime.now(timezone.utc).timestamp()) // 180
    source = secrets.token_hex(16) if force else f'{cfg["recipient"]}:{cfg["provider"]}:{category}:{safe_title}:{event_key or safe_body}:{bucket}'
    row = EmailAlert(dedupe_key=hashlib.sha256(source.encode()).hexdigest(), recipient=cfg["recipient"],
                     provider=cfg["provider"], title=safe_title, body=safe_body, status="pending", attempts=0)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        await db.commit()
    except IntegrityError:
        # Release the outer SQLite transaction after rolling back the duplicate savepoint.
        await db.commit()
        return None
    return row


def _smtp_send(cfg: dict, row: EmailAlert) -> None:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = cfg["smtp_sender"], row.recipient, row.title
    message.set_content(row.body)
    context = ssl.create_default_context()
    if cfg["smtp_security"] == "ssl":
        client = smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], timeout=20, context=context)
    else:
        client = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=20)
    with client:
        if cfg["smtp_security"] == "starttls":
            client.starttls(context=context)
        if cfg["smtp_username"]:
            client.login(cfg["smtp_username"], decrypt_secret(cfg.get("smtp_password_enc")) or "")
        refused = client.send_message(message)
        if refused:
            raise ValueError("SMTP 服务未接收收件地址")


async def dispatch_email_alerts(record_id: int | None = None) -> None:
    async with SessionLocal() as db:
        cfg = await config(db)
        now = datetime.now(timezone.utc)
        # A crash during the last attempt must not leave the record permanently "sending".
        await db.execute(update(EmailAlert).where(EmailAlert.status == "sending", EmailAlert.attempts >= 3,
            EmailAlert.updated_at < now - timedelta(minutes=5)).values(status="failed",
                error="最后一次发送结果未确认，已达到重试上限；可能已被发信服务接收，请核对收件箱"))
        await db.commit()
        query = select(EmailAlert).where(EmailAlert.attempts < 3, or_(
            and_(EmailAlert.status.in_(["pending", "retrying"]), or_(EmailAlert.next_attempt_at.is_(None), EmailAlert.next_attempt_at <= now)),
            and_(EmailAlert.status == "sending", EmailAlert.updated_at < now - timedelta(minutes=5))))
        if record_id:
            query = query.where(EmailAlert.id == record_id)
        for row in list(await db.scalars(query.order_by(EmailAlert.id).limit(5))):
            if not cfg["enabled"] or (cfg["recipient"], cfg["provider"]) != (row.recipient, row.provider):
                row.status, row.error = "cancelled", "邮件告警已关闭或收件配置已改变，取消旧通知"
                await db.commit()
                continue
            claim = await db.execute(update(EmailAlert).where(EmailAlert.id == row.id, EmailAlert.status == row.status,
                EmailAlert.attempts == row.attempts).values(status="sending", attempts=EmailAlert.attempts + 1))
            await db.commit()
            if not claim.rowcount:
                continue
            await db.refresh(row)
            try:
                if cfg["provider"] == "agentmail":
                    from app.services.agent_mail import send
                    await send(row.recipient, row.title, row.body)
                else:
                    await asyncio.to_thread(_smtp_send, cfg, row)
                row.status, row.error, row.accepted_at = "accepted", None, datetime.now(timezone.utc)
            except Exception as exc:  # noqa: BLE001
                row.status = "failed" if row.attempts >= 3 else "retrying"
                row.error = mask_text(str(exc))[:500]
                row.next_attempt_at = now + timedelta(seconds=60 * row.attempts)
            await db.commit()
