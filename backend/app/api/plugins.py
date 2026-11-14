"""插件管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.db.session import get_db
from app.models import Plugin, PluginBinding, User
from app.schemas.common import MessageOut
from app.schemas.task import PluginBindingCreate, PluginOut, PluginUpdate
from app.services.logs import audit
from app.services.plugins import plugin_manager

router = APIRouter(prefix="/plugins", tags=["插件"])


async def serialize(db: AsyncSession, plugin: Plugin) -> PluginOut:
    data = PluginOut.model_validate(plugin)
    data.binding_count = int(
        await db.scalar(
            select(func.count()).select_from(PluginBinding).where(PluginBinding.plugin_id == plugin.id)
        )
        or 0
    )
    return data


@router.get("", response_model=list[PluginOut])
async def list_plugins(db: AsyncSession = Depends(get_db), _: User = Depends(require("plugin:view"))):
    plugins = list(await db.scalars(select(Plugin).order_by(Plugin.id)))
    return [await serialize(db, p) for p in plugins]


@router.post("/sync", response_model=list[PluginOut])
async def sync_plugins(db: AsyncSession = Depends(get_db), user: User = Depends(require("plugin:manage"))):
    await plugin_manager.sync_to_db(db)
    stats = await plugin_manager.load_all(db)
    await audit(db, user_id=user.id, username=user.username, action="sync_plugins", detail=str(stats))
    plugins = list(await db.scalars(select(Plugin).order_by(Plugin.id)))
    return [await serialize(db, p) for p in plugins]


@router.put("/{plugin_id}", response_model=PluginOut)
async def update_plugin(
    plugin_id: int, payload: PluginUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(require("plugin:manage"))
):
    plugin = await db.get(Plugin, plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")
    if payload.config is not None:
        plugin.config = payload.config
    if payload.enabled is not None:
        plugin.enabled = payload.enabled
    await db.commit()
    await db.refresh(plugin)
    await plugin_manager.reload(db, plugin)
    await db.refresh(plugin)
    await audit(
        db, user_id=user.id, username=user.username, action="update_plugin", target=plugin.plugin_id,
        detail=f"enabled={plugin.enabled} status={plugin.load_status}",
    )
    return await serialize(db, plugin)


@router.post("/{plugin_id}/reload", response_model=PluginOut)
async def reload_plugin(
    plugin_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("plugin:manage"))
):
    plugin = await db.get(Plugin, plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")
    await plugin_manager.reload(db, plugin)
    await db.refresh(plugin)
    return await serialize(db, plugin)


@router.get("/{plugin_id}/metrics")
async def get_plugin_metrics(
    plugin_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("plugin:view"))
):
    """插件运行指标与权限调用审计；插件代码受信执行，这里只提供可观测性，不宣称沙箱。"""
    plugin = await db.get(Plugin, plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")
    metrics = plugin_manager.metrics_for(plugin.plugin_id)
    checks = [
        entry for entry in reversed(plugin_manager.permission_audit_log) if entry["plugin_id"] == plugin.plugin_id
    ]
    return {
        "plugin_id": plugin.plugin_id,
        **metrics.as_dict(),
        "permission_checks": checks[:50],
    }


@router.get("/{plugin_id}/bindings")
async def list_bindings(plugin_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("plugin:view"))):
    plugin = await db.get(Plugin, plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")
    rows = await db.scalars(select(PluginBinding).where(PluginBinding.plugin_id == plugin_id))
    return [
        {"id": b.id, "scope": b.scope, "target_id": b.target_id, "enabled": b.enabled, "created_at": b.created_at}
        for b in rows
    ]


@router.post("/{plugin_id}/bindings", response_model=MessageOut)
async def add_binding(
    plugin_id: int,
    payload: PluginBindingCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("plugin:manage")),
):
    plugin = await db.get(Plugin, plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")
    existing = await db.scalar(
        select(PluginBinding).where(
            PluginBinding.plugin_id == plugin_id,
            PluginBinding.scope == payload.scope,
            PluginBinding.target_id == payload.target_id,
        )
    )
    if existing:
        existing.enabled = payload.enabled
    else:
        db.add(
            PluginBinding(
                plugin_id=plugin_id, scope=payload.scope, target_id=payload.target_id, enabled=payload.enabled
            )
        )
    await db.commit()
    await audit(
        db,
        user_id=user.id,
        username=user.username,
        action="bind_plugin",
        target=plugin.plugin_id,
        detail=f"{payload.scope}:{payload.target_id}={payload.enabled}",
    )
    return MessageOut(detail="绑定已保存")


@router.delete("/{plugin_id}/bindings/{binding_id}", response_model=MessageOut)
async def delete_binding(
    plugin_id: int, binding_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("plugin:manage"))
):
    binding = await db.get(PluginBinding, binding_id)
    if not binding or binding.plugin_id != plugin_id:
        raise HTTPException(status_code=404, detail="绑定不存在")
    await db.delete(binding)
    await db.commit()
    return MessageOut(detail="绑定已删除")
