"""插件系统：目录发现、动态加载、权限声明、按账号/群启用、命令与消息钩子。

安全边界：插件只能通过 ctx 提供的受限接口工作，不能直接访问数据库、协议适配器或系统命令。
"""

from __future__ import annotations

import importlib.util
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

# 权限调用审计环形缓冲长度；仅保留最近记录，避免高频插件撑爆内存。
_PERMISSION_AUDIT_MAXLEN = 300


@dataclass
class PluginMetrics:
    """单插件运行指标：调用次数、错误率与执行耗时。"""

    invocations: int = 0
    errors: int = 0
    total_duration_ms: float = 0.0
    last_duration_ms: float | None = None
    last_error: str | None = None
    last_error_at: str | None = None
    last_run_at: str | None = None
    permission_denied: int = 0

    def record(self, duration_ms: float, error: str | None) -> None:
        self.invocations += 1
        self.total_duration_ms += duration_ms
        self.last_duration_ms = round(duration_ms, 2)
        self.last_run_at = datetime.now(timezone.utc).isoformat()
        if error is not None:
            self.errors += 1
            self.last_error = error
            self.last_error_at = self.last_run_at

    @property
    def error_rate(self) -> float:
        return round(self.errors / self.invocations, 4) if self.invocations else 0.0

    @property
    def avg_duration_ms(self) -> float:
        return round(self.total_duration_ms / self.invocations, 2) if self.invocations else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "invocations": self.invocations,
            "errors": self.errors,
            "error_rate": self.error_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "last_duration_ms": self.last_duration_ms,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "last_run_at": self.last_run_at,
            "permission_denied": self.permission_denied,
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
    # 由 PluginManager 在加载时注入；has_permission 的每次判定都会进入权限审计。
    permission_audit: Callable[[str, bool], None] | None = field(default=None, repr=False, compare=False)

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
        allowed = permission in self.permissions
        if self.permission_audit is not None:
            self.permission_audit(permission, allowed)
        return allowed


@dataclass
class LoadedPlugin:
    plugin_id: str
    ctx: PluginContext
    module: Any


class PluginManager:
    def __init__(self) -> None:
        self.loaded: dict[str, LoadedPlugin] = {}
        self.metrics: dict[str, PluginMetrics] = {}
        # 权限调用审计：最近的判定记录（plugin_id/permission/allowed/time）。
        self.permission_audit_log: deque[dict[str, Any]] = deque(maxlen=_PERMISSION_AUDIT_MAXLEN)

    def metrics_for(self, plugin_id: str) -> PluginMetrics:
        return self.metrics.setdefault(plugin_id, PluginMetrics())

    def record_permission_check(self, plugin_id: str, permission: str, allowed: bool) -> None:
        if not allowed:
            self.metrics_for(plugin_id).permission_denied += 1
        self.permission_audit_log.append(
            {
                "plugin_id": plugin_id,
                "permission": permission,
                "allowed": allowed,
                "time": datetime.now(timezone.utc).isoformat(),
            }
        )

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
            ctx.permission_audit = lambda permission, allowed, plugin_id=plugin.plugin_id: self.record_permission_check(
                plugin_id, permission, allowed
            )
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
                metrics = self.metrics_for(plugin_id)
                started = time.perf_counter()
                try:
                    reply = await handler(message)
                    if reply:
                        replies.append(reply)
                    metrics.record((time.perf_counter() - started) * 1000, None)
                except Exception as exc:  # noqa: BLE001
                    metrics.record((time.perf_counter() - started) * 1000, f"{type(exc).__name__}: {exc}")
                    logger.exception("插件命令执行失败 %s", plugin_id)
                    replies.append(f"插件 {plugin_id} 执行出错：{type(exc).__name__}")
                continue
            for hook in loaded.ctx.message_hooks:
                metrics = self.metrics_for(plugin_id)
                started = time.perf_counter()
                try:
                    reply = await hook(message)
                    if reply:
                        replies.append(reply)
                    metrics.record((time.perf_counter() - started) * 1000, None)
                except Exception as exc:  # noqa: BLE001
                    metrics.record((time.perf_counter() - started) * 1000, f"{type(exc).__name__}: {exc}")
                    logger.exception("插件消息钩子执行失败 %s", plugin_id)
        return replies


plugin_manager = PluginManager()
