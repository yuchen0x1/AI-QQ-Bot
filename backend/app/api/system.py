"""系统监控、设置与备份 API。"""

from __future__ import annotations

import platform
import sys

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.core.config import settings
from app.core.logging import mask_text
from app.core.version import APP_VERSION
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
    from app.services.runtime_start import services_deferred
    payload = {"status": "ok" if db_ok else "degraded", "database": db_ok, "version": APP_VERSION,
               "services_deferred": services_deferred}
    # 探活端点必须通过 HTTP 状态反映不可用，否则反向代理会把数据库故障实例
    # 继续放进流量池，只返回一个看似正常的 JSON。
    return JSONResponse(status_code=200 if db_ok else 503, content=payload)


@router.get("/config")
async def public_config():
    """登录页也要用的公开配置（无需鉴权，只暴露可公开展示的字段）。"""
    from app.services.settings_store import read_setting
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        title = await read_setting(db, "panel_title", "")
    return {
        "panel_title": str(title or "").strip() or "QBot 控制台",
        "version": APP_VERSION,
        "env": settings.env,
    }


@router.get("/info")
async def info(_: User = Depends(require("system:view"))):
    from app.services.scheduler import scheduler_service

    return {
        "name": settings.app_name,
        "env": settings.env,
        "version": APP_VERSION,
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


@router.get("/update")
async def update_info(channel: str | None = None, _: User = Depends(require("system:view"))):
    """检查 GitHub Releases；网络失败只返回诊断，不阻断管理台。"""
    from app.services.update_checker import check_for_update

    from app.services.update_installer import installer_state
    result = await check_for_update(channel)
    result["installer"] = await installer_state()
    native = f"qbot-ai-{result.get('latest_version')}-native.tar.gz"
    result["installable"] = bool(result["installer"]["available"] and result.get("update_available")
        and not result.get("prerelease") and any(a["name"] == native and a.get("sha256") for a in result["assets"]))
    return result


class InstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    request_id: UUID


@router.get("/update/install")
async def install_status(_: User = Depends(require("system:manage"))):
    from app.services.update_installer import installer_state
    return await installer_state()


@router.post("/update/install", status_code=202)
async def install_update(payload: InstallRequest, db: AsyncSession = Depends(get_db),
                         user: User = Depends(require("system:manage"))):
    from app.services.update_installer import installer_rpc, InstallerUnavailable
    try:
        state = await installer_rpc("POST", {"version": payload.version, "request_id": str(payload.request_id)})
    except InstallerUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit(db, user_id=user.id, username=user.username, action="install_update", target=payload.version,
                detail=f"job={payload.request_id}")
    return {"available": True, **state}


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
    new_value = payload.get("value")
    # 读取接口对 is_secret 行返回 "******"；若前端原样回传掩码，必须保留旧值，
    # 不能把掩码字符串当成真实密钥写库（否则下一次使用就会静默失败）。
    if row.is_secret and isinstance(new_value, str) and set(new_value) == {"*"}:
        pass
    else:
        row.value = {"value": new_value}
    await db.commit()
    await db.refresh(row)
    await audit(
        db,
        user_id=user.id,
        username=user.username,
        action="update_setting",
        target=key,
        detail=mask_text(str(payload))[:300],
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
    from app.services.alerting import _build_payload, _detect_channel, validate_webhook_url

    url = str(payload.get("webhook_url") or "").strip()
    channel_type = str(payload.get("channel_type") or "auto")
    if not url:
        raise HTTPException(status_code=400, detail="缺少 webhook_url")
    valid, reason = validate_webhook_url(url)
    if not valid:
        raise HTTPException(status_code=400, detail=reason)

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

