"""插件系统：目录发现、动态加载、权限声明、按账号/群启用、命令与消息钩子。

安全边界：插件只能通过 ctx 提供的受限接口工作，不能直接访问数据库、协议适配器或系统命令。
"""

from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Plugin, PluginBinding

logger = logging.getLogger("qbot.plugins")

ALLOWED_PERMISSIONS = {
    "message:reply",  # 回复消息（默认必需）
    "storage:config",  # 读写自身配置
    "ai:request",  # 请求 AI（需平台显式授权）
    "http:request",  # 发起外部 HTTP 请求
}


@dataclass
class PluginMessage:
    account_id: int
    group_number: int | None
    user_id: int
    text: str
    args: list[str] = field(default_factory=list)
    sender_name: str = ""


PluginHandler = Callable[[PluginMessage], Awaitable[str | None]]


@dataclass
class PluginContext:
    plugin_id: str
    config: dict[str, Any]
    permissions: set[str]
    commands: dict[str, PluginHandler] = field(default_factory=dict)
    message_hooks: list[PluginHandler] = field(default_factory=list)
    command_meta: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_command(
        self, name: str, handler: PluginHandler, *, description: str = "", aliases: list[str] | None = None
    ) -> None:
        self.commands[name] = handler
        for alias in aliases or []:
            self.commands[alias] = handler
        self.command_meta[name] = {"description": description, "aliases": aliases or []}

    def on_message(self, handler: PluginHandler) -> None:
        self.message_hooks.append(handler)

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass
class LoadedPlugin:
    plugin_id: str
    ctx: PluginContext
    module: Any


class PluginManager:
    def __init__(self) -> None:
        self.loaded: dict[str, LoadedPlugin] = {}

    # ------------------------------------------------------------------
    def discover(self) -> list[dict[str, Any]]:
        root = Path(settings.plugin_dir)
        found: list[dict[str, Any]] = []
        if not root.exists():
            return found
        for entry in sorted(root.iterdir()):
            manifest_path = entry / "plugin.json"
            if not entry.is_dir() or not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("插件清单解析失败 %s: %s", entry.name, exc)
                continue
            manifest.setdefault("id", entry.name)
            manifest["_path"] = str(entry)
            found.append(manifest)
        return found

    async def sync_to_db(self, db: AsyncSession) -> int:
        count = 0
        for manifest in self.discover():
            plugin = await db.scalar(select(Plugin).where(Plugin.plugin_id == manifest["id"]))
            if not plugin:
                plugin = Plugin(
                    plugin_id=manifest["id"],
                    name=manifest.get("name") or manifest["id"],
                    version=manifest.get("version") or "1.0.0",
                    author=manifest.get("author"),
                    description=manifest.get("description"),
                    permissions=manifest.get("permissions") or ["message:reply"],
                    config=manifest.get("config") or {},
                    enabled=bool(manifest.get("enabled_by_default", False)),
                    builtin=bool(manifest.get("builtin", False)),
                    path=manifest["_path"],
                    commands=[c.get("name") for c in manifest.get("commands", []) if isinstance(c, dict)],
                )
                db.add(plugin)
            else:
                plugin.name = manifest.get("name") or plugin.name
                plugin.version = manifest.get("version") or plugin.version
                plugin.author = manifest.get("author") or plugin.author
                plugin.description = manifest.get("description") or plugin.description
                plugin.permissions = manifest.get("permissions") or plugin.permissions
                plugin.path = manifest["_path"]
                plugin.commands = [c.get("name") for c in manifest.get("commands", []) if isinstance(c, dict)]
            count += 1
        await db.commit()
        return count

    # ------------------------------------------------------------------
    def load_one(self, plugin: Plugin) -> LoadedPlugin | None:
        path = Path(plugin.path or "") / "main.py"
        if not path.exists():
            plugin.load_status = "missing"
            plugin.load_error = "未找到 main.py"
            return None
        module_name = f"qbot_plugin_{plugin.plugin_id}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if not spec or not spec.loader:
                raise ImportError("无法创建模块规格")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if not callable(register):
                raise AttributeError("插件必须实现 register(ctx) 函数")
            permissions = set(plugin.permissions or [])
            ctx = PluginContext(plugin_id=plugin.plugin_id, config=dict(plugin.config or {}), permissions=permissions)
            register(ctx)
            loaded = LoadedPlugin(plugin_id=plugin.plugin_id, ctx=ctx, module=module)
            self.loaded[plugin.plugin_id] = loaded
            plugin.load_status = "loaded"
            plugin.load_error = None
            plugin.commands = list({k for k, _ in ctx.commands.items()})
            logger.info("插件已加载：%s（命令 %s 个）", plugin.plugin_id, len(ctx.commands))
            return loaded
        except Exception as exc:  # noqa: BLE001
            plugin.load_status = "error"
            plugin.load_error = f"{type(exc).__name__}: {exc}"
            logger.exception("插件加载失败 %s", plugin.plugin_id)
            return None

    async def load_all(self, db: AsyncSession) -> dict[str, int]:
        stats = {"loaded": 0, "failed": 0, "disabled": 0}
        self.loaded.clear()
        rows = list(await db.scalars(select(Plugin)))
        for plugin in rows:
            if not plugin.enabled:
                plugin.load_status = "disabled"
                stats["disabled"] += 1
                continue
            loaded = self.load_one(plugin)
            if loaded:
                stats["loaded"] += 1
            else:
                stats["failed"] += 1
        await db.commit()
        return stats

    async def reload(self, db: AsyncSession, plugin: Plugin) -> LoadedPlugin | None:
        self.loaded.pop(plugin.plugin_id, None)
        if not plugin.enabled:
            plugin.load_status = "disabled"
            await db.commit()
            return None
        loaded = self.load_one(plugin)
        await db.commit()
        return loaded

    # ------------------------------------------------------------------
    async def _is_allowed(self, db: AsyncSession, plugin: Plugin, account_id: int, group_number: int | None) -> bool:
        bindings = list(await db.scalars(select(PluginBinding).where(PluginBinding.plugin_id == plugin.id)))
        account_bindings = [b for b in bindings if b.scope == "account"]
        if account_bindings:
            match = next((b for b in account_bindings if b.target_id == str(account_id)), None)
            if not match or not match.enabled:
                return False
        if group_number:
            group_bindings = [b for b in bindings if b.scope == "group"]
            match = next((b for b in group_bindings if b.target_id == str(group_number)), None)
            if match and not match.enabled:
                return False
        return True

    async def dispatch_message(
        self,
        db: AsyncSession,
        *,
        account_id: int,
        group_number: int | None,
        user_id: int,
        text: str,
        sender_name: str = "",
    ) -> list[str]:
        if not text or not self.loaded:
            return []
        rows = {p.plugin_id: p for p in await db.scalars(select(Plugin).where(Plugin.enabled.is_(True)))}
        replies: list[str] = []
        body = text.strip()
        if body.startswith("/"):
            body = body[1:]
        token, _, rest = body.partition(" ")
        for plugin_id, loaded in self.loaded.items():
            plugin = rows.get(plugin_id)
            if not plugin:
                continue
            if not await self._is_allowed(db, plugin, account_id, group_number):
                continue
            if not loaded.ctx.has_permission("message:reply"):
                continue
            message = PluginMessage(
                account_id=account_id,
                group_number=group_number,
                user_id=user_id,
                text=text,
                args=[a for a in rest.split(" ") if a.strip()] if rest else [],
                sender_name=sender_name,
            )
            handler = loaded.ctx.commands.get(token)
            if handler:
                try:
                    reply = await handler(message)
                    if reply:
                        replies.append(reply)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("插件命令执行失败 %s", plugin_id)
                    replies.append(f"插件 {plugin_id} 执行出错：{type(exc).__name__}")
                continue
            for hook in loaded.ctx.message_hooks:
                try:
                    reply = await hook(message)
                    if reply:
                        replies.append(reply)
                except Exception:  # noqa: BLE001
                    logger.exception("插件消息钩子执行失败 %s", plugin_id)
        return replies


plugin_manager = PluginManager()
