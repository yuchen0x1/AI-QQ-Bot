"""Administrator-controlled outgoing failure email settings and connection checks."""
from datetime import datetime, timezone
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.core.security import encrypt_secret
from app.db.session import get_db
from app.models import EmailAlert, SystemSetting, User
from app.services import agent_mail
from app.services.alerting import validate_webhook_url
from app.services.email_alerts import CONFIG_KEY, PROFILE_KEY, config, dispatch_email_alerts, enqueue, put_setting
from app.services.logs import audit

router = APIRouter(prefix="/system/email", tags=["邮件告警"])


def valid_email(value: str) -> bool:
    return bool(len(value) <= 320 and re.fullmatch(r"[^@\s<>\r\n]+@[^@\s<>\r\n]+\.[^@\s<>\r\n]+", value))


class MailSettings(BaseModel):
    enabled: bool = False
    provider: Literal["agentmail", "smtp"] = "agentmail"
    recipient: str = Field(default="", max_length=320)
    categories: list[Literal["task", "push", "github", "account", "error"]] = ["task", "push", "github", "account"]
    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_security: Literal["ssl", "starttls"] = "ssl"
    smtp_username: str = Field(default="", max_length=320)
    smtp_sender: str = Field(default="", max_length=320)
    smtp_password: str | None = Field(default=None, max_length=1024)
    clear_password: bool = False

    @field_validator("recipient", "smtp_sender")
    @classmethod
    def email_format(cls, value):
        value = value.strip()
        if value and not valid_email(value):
            raise ValueError("请填写有效的邮箱地址")
        return value


async def public_state(db):
    cfg = await config(db)
    secret = cfg.pop("smtp_password_enc", None)
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == PROFILE_KEY))
    return {**cfg, "has_smtp_password": bool(secret), "agent": row.value if row else {"connected": False},
            "cli_installed": bool(agent_mail.executable()), "authorization": agent_mail.login_status()}


@router.get("")
async def get_email(db: AsyncSession = Depends(get_db), _: User = Depends(require("system:manage"))):
    return await public_state(db)


@router.put("")
async def save_email(payload: MailSettings, db: AsyncSession = Depends(get_db), user: User = Depends(require("system:manage"))):
    if payload.enabled and not payload.recipient:
        raise HTTPException(400, "启用邮件告警前请填写收件邮箱")
    if payload.provider == "smtp" and (payload.enabled or payload.smtp_host):
        valid, reason = validate_webhook_url(f"https://{payload.smtp_host}:{payload.smtp_port}")
        if not valid:
            raise HTTPException(400, f"SMTP 主机无效：{reason}")
        if not payload.smtp_sender:
            raise HTTPException(400, "请填写 SMTP 发信邮箱")
    previous = await config(db)
    value = payload.model_dump(exclude={"smtp_password", "clear_password"})
    password = payload.smtp_password
    if password and set(password) == {"*"}:
        raise HTTPException(400, "请填写新的 SMTP 授权码，或留空保留原授权码")
    value["smtp_password_enc"] = None if payload.clear_password else (
        encrypt_secret(password) if password else previous.get("smtp_password_enc"))
    await put_setting(db, CONFIG_KEY, value, secret=True)
    if not payload.enabled:
        await db.execute(update(EmailAlert).where(EmailAlert.status.in_(["pending", "retrying"]))
                         .values(status="cancelled", error="邮件告警已关闭，取消待发送邮件"))
        await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="configure_email_alerts", target=payload.provider)
    return await public_state(db)


@router.post("/agent/connect")
async def connect(_: User = Depends(require("system:manage"))):
    if not agent_mail.executable():
        raise HTTPException(400, "尚未安装 Agent Mail 发信工具，请按操作文档安装")
    return await agent_mail.start_login()


@router.post("/agent/check")
async def check_agent(db: AsyncSession = Depends(get_db), _: User = Depends(require("system:manage"))):
    try:
        result = await agent_mail.profile()
    except Exception as exc:  # noqa: BLE001
        result = {"connected": False, "sender": "", "error": str(exc)[:500]}
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    await put_setting(db, PROFILE_KEY, result)
    return await public_state(db)


@router.get("/records")
async def records(db: AsyncSession = Depends(get_db), _: User = Depends(require("system:manage"))):
    rows = list(await db.scalars(select(EmailAlert).order_by(EmailAlert.id.desc()).limit(50)))
    return [{"id": r.id, "recipient": r.recipient, "title": r.title, "status": r.status, "attempts": r.attempts,
             "error": r.error, "created_at": r.created_at, "accepted_at": r.accepted_at} for r in rows]


@router.post("/test")
async def test_email(db: AsyncSession = Depends(get_db), user: User = Depends(require("system:manage"))):
    cfg = await config(db)
    if not cfg["enabled"] or not cfg["recipient"]:
        raise HTTPException(400, "请先保存并启用邮件告警，测试使用已保存的发信设置")
    row = await enqueue(db, title="QBot 失败告警通道测试", category="error", force=True,
        body="这是一封 QBot 邮件告警测试。\n\n任务失败或群通知投递失败时，系统会按后台设置发送邮件。\n请在后台「邮件告警」查看每次发信结果。")
    await dispatch_email_alerts(row.id)
    await db.refresh(row)
    await audit(db, user_id=user.id, username=user.username, action="test_email_alerts", target=str(row.id))
    return {"ok": row.status == "accepted", "status": row.status, "error": row.error,
            "message": "发信服务已接收测试邮件，请到收件邮箱确认" if row.status == "accepted" else "测试发信失败，详情已保存在发信记录"}
