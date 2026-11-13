"""Per-user first-run guidance backed by the actual configuration."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Account, EmailAlert, SystemSetting, User
from app.services.account_manager import account_manager
from app.services.email_alerts import config as email_config
from app.services.github.automation import subscription_status

router = APIRouter(prefix="/onboarding", tags=["新手指引"])


class GuideProgress(BaseModel):
    seen: bool = True
    step: int = Field(default=0, ge=0, le=4)


@router.get("")
async def state(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    perms = user.permission_set
    permitted = lambda p: "*" in perms or p in perms  # noqa: E731
    accounts = list(await db.scalars(select(Account.id))) if permitted("account:view") else []
    gh = await subscription_status(db, user.id) if permitted("github:view") else {}
    destinations = [t for t in gh.get("targets", []) if t["enabled"]]
    cfg = await email_config(db) if permitted("system:manage") else {}
    mail_ok = bool(cfg.get("enabled") and cfg.get("recipient") and await db.scalar(
        select(EmailAlert.id).where(EmailAlert.status == "accepted", EmailAlert.recipient == cfg["recipient"],
                                   EmailAlert.provider == cfg["provider"]).limit(1)))
    steps = [
        {"title": "连接 QQ 机器人", "path": "/accounts", "permission": "account:manage",
         "ready": any(account_manager.is_online(i) for i in accounts), "hint": "账号在线后继续"},
        {"title": "连接 GitHub 仓库", "path": "/github", "permission": "github:manage",
         "ready": bool(gh.get("connected") and gh.get("monitored_count")), "hint": "连接 Token，保存并同步仓库"},
        {"title": "绑定通知群并授权", "path": "/github", "permission": "push:manage",
         "ready": bool(destinations) and all(t["bound"] and t.get("delivery", {}).get("allow_proactive_msg") is True for t in destinations),
         "hint": "群内绑定，再在 QQ 开启允许主动发送，最后检查群权限"},
        {"title": "验证群通知", "path": "/github", "permission": "push:manage",
         "ready": any(t.get("delivery", {}).get("delivered", 0) > 0 or t.get("delivery", {}).get("probe_ok") is True for t in destinations),
         "hint": "测试主动通知，在 QQ 群中确认收到消息"},
        {"title": "配置失败邮件", "path": "/email", "permission": "system:manage", "ready": mail_ok,
         "hint": "设置发信账号与收件邮箱，发送一封测试邮件", "optional": True},
    ]
    for step in steps:
        step["allowed"] = permitted(step.pop("permission"))
    progress = await db.scalar(select(SystemSetting).where(SystemSetting.key == f"onboarding:{user.id}"))
    return {"steps": steps, "progress": progress.value if progress else {"seen": False, "step": 0},
            "complete": all(s["ready"] for s in steps if not s.get("optional"))}


@router.put("")
async def save(payload: GuideProgress, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    key = f"onboarding:{user.id}"
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if row:
        row.value = payload.model_dump()
    else:
        db.add(SystemSetting(key=key, value=payload.model_dump(), description="首次使用教学进度"))
    await db.commit()
    return {"ok": True}
