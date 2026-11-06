"""系统监控、设置与备份 API。"""

from __future__ import annotations

import platform
import sys

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.core.config import settings
from app.db.session import get_db
from app.models import SystemSetting, User
from app.schemas.task import SettingOut, SystemStats
from app.services.backup import backup_database, list_backups, prune_backups
from app.services.logs import audit, write_log
from app.services.system import collect_system_stats

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/stats", response_model=SystemStats)
async def stats(_: User = Depends(require("system:view"))):
    data = await collect_system_stats()
    return SystemStats(**{k: data[k] for k in SystemStats.model_fields if k in data})


@router.get("/health")
async def health():
    """健康检查端点（供 Docker / 负载均衡探活）。"""
    from app.db.session import engine
    from sqlalchemy import text

    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "version": "1.0.0"}


@router.get("/info")
async def info(_: User = Depends(require("system:view"))):
    from app.services.scheduler import scheduler_service

    return {
        "name": settings.app_name,
        "env": settings.env,
        "version": "1.0.0",
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "executable": sys.executable,
        "database": settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url.split("///")[0],
        "redis_enabled": settings.redis_enabled,
        "scheduler_running": scheduler_service.running,
        "scheduler_jobs": scheduler_service.job_count(),
        "timezone": settings.scheduler_timezone,
        "public_base_url": settings.public_base_url,
    }


@router.get("/settings", response_model=list[SettingOut])
async def list_settings(db: AsyncSession = Depends(get_db), _: User = Depends(require("system:view"))):
    rows = await db.scalars(select(SystemSetting).order_by(SystemSetting.key))
    result = []
    for row in rows:
        value = row.value.get("value") if isinstance(row.value, dict) else row.value
        if row.is_secret:
            value = "******"
        result.append(SettingOut(key=row.key, value=value, description=row.description, is_secret=row.is_secret))
    return result


@router.put("/settings/{key}", response_model=SettingOut)
async def update_setting(
    key: str, payload: dict, db: AsyncSession = Depends(get_db), user: User = Depends(require("system:manage"))
):
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if not row:
        raise HTTPException(status_code=404, detail="配置项不存在")
    row.value = {"value": payload.get("value")}
    await db.commit()
    await db.refresh(row)
    await audit(
        db, user_id=user.id, username=user.username, action="update_setting", target=key, detail=str(payload)[:300]
    )
    return SettingOut(
        key=row.key,
        value=row.value.get("value") if isinstance(row.value, dict) else row.value,
        description=row.description,
        is_secret=row.is_secret,
    )


@router.get("/backups")
async def backups(_: User = Depends(require("system:view"))):
    return list_backups()


@router.post("/backup")
async def do_backup(db: AsyncSession = Depends(get_db), user: User = Depends(require("system:manage"))):
    try:
        path = await backup_database()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"备份失败：{exc}") from exc
    keep_row = await db.scalar(select(SystemSetting).where(SystemSetting.key == "auto_backup_keep"))
    keep = int((keep_row.value or {}).get("value", 14)) if keep_row else 14
    removed = prune_backups(keep=keep)
    await write_log(db, level="INFO", category="system", message=f"数据库备份完成：{path.name}，清理旧备份 {removed} 个")
    await audit(db, user_id=user.id, username=user.username, action="backup_database", target=path.name)
    return {"ok": True, "path": str(path), "pruned": removed, "message": f"备份已生成：{path.name}"}


@router.post("/alert/test")
async def test_alert(payload: dict, _: User = Depends(require("system:manage"))):
    """测试第三方告警推送。"""
    from app.core.http import new_client
    from app.services.alerting import _build_payload, _detect_channel

    url = str(payload.get("webhook_url") or "").strip()
    channel_type = str(payload.get("channel_type") or "auto")
    if not url:
        raise HTTPException(status_code=400, detail="缺少 webhook_url")

    channel = _detect_channel(url, channel_type)
    body = _build_payload(channel, "通道连通性测试", "这是一条来自 QBot AI 管理控制台的告警测试消息。如果您收到本条通知，说明系统告警通道配置正常！")

    try:
        async with new_client(timeout=10.0) as client:
            resp = await client.post(url, json=body)
            if resp.status_code >= 400:
                return {"ok": False, "message": f"平台返回错误 HTTP {resp.status_code}: {resp.text[:200]}"}
            return {"ok": True, "message": "测试推送成功"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"请求失败: {exc}"}

