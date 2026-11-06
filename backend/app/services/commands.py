"""机器人命令系统：服务端权限校验，协议能力校验，全部真实执行。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, AdapterEvent, QQAdapter, UnsupportedAction
from app.models import Account, BotCommand, Group, GroupMember, GroupSettings, GithubRepository, SystemSetting

logger = logging.getLogger("qbot.commands")

ROLE_RANK = {"member": 0, "admin": 1, "owner": 2, "super_admin": 3}
ROLE_LABEL = {"member": "普通成员", "admin": "群管理员", "owner": "群主", "super_admin": "超级管理员"}


@dataclass
class CommandContext:
    db: AsyncSession
    account_id: int
    account_name: str
    adapter: QQAdapter
    event: AdapterEvent
    group_number: int | None
    group: Group | None
    settings: GroupSettings | None
    is_private: bool
    sender_id: int
    sender_role: str
    args: list[str] = field(default_factory=list)
    at_targets: list[int] = field(default_factory=list)
    command_name: str = ""
    started: float = field(default_factory=time.perf_counter)

    @property
    def rank(self) -> int:
        return ROLE_RANK.get(self.sender_role, 0)

    def target_user(self) -> int | None:
        if self.at_targets:
            return self.at_targets[0]
        for arg in self.args:
            if arg.isdigit() and len(arg) >= 5:
                return int(arg)
        return None

    def duration_seconds(self, default: int = 600) -> int:
        for arg in reversed(self.args):
            if arg.isdigit() and len(arg) <= 6:
                value = int(arg)
                if value <= 0:
                    continue
                if value > 1000:  # 视为秒
                    return min(value, 2592000)
                return value * 60
        return default


CommandHandler = Callable[[CommandContext], Awaitable[str]]


class CommandRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}
        self._aliases: dict[str, str] = {}

    def register(self, name: str, handler: CommandHandler, aliases: list[str] | None = None) -> None:
        self._handlers[name] = handler
        for alias in aliases or []:
            self._aliases[alias] = name

    def resolve(self, token: str) -> tuple[str, CommandHandler] | None:
        name = self._aliases.get(token, token)
        handler = self._handlers.get(name)
        return (name, handler) if handler else None

    def names(self) -> list[str]:
        return list(self._handlers)


registry = CommandRegistry()


def command(name: str, aliases: list[str] | None = None) -> Callable[[CommandHandler], CommandHandler]:
    def decorator(func: CommandHandler) -> CommandHandler:
        registry.register(name, func, aliases)
        return func

    return decorator


BUILTIN_COMMANDS: list[dict[str, Any]] = [
    {"name": "help", "aliases": ["帮助", "菜单"], "description": "查看可用命令", "handler": "help", "min_role": "member"},
    {"name": "status", "aliases": ["状态"], "description": "查看机器人运行状态", "handler": "status", "min_role": "member"},
    {"name": "ping", "aliases": [], "description": "测试响应延迟", "handler": "ping", "min_role": "member"},
    {"name": "ai", "aliases": ["问"], "description": "向 AI 提问", "handler": "ai", "min_role": "member", "usage": "/ai 你的问题"},
    {"name": "mute", "aliases": ["禁言"], "description": "禁言群成员", "handler": "mute", "min_role": "admin", "usage": "/禁言 @成员 10"},
    {"name": "unmute", "aliases": ["解禁", "解除禁言"], "description": "解除成员禁言", "handler": "unmute", "min_role": "admin"},
    {"name": "ban_all", "aliases": ["全体禁言"], "description": "开启全体禁言", "handler": "ban_all", "min_role": "admin"},
    {"name": "unban_all", "aliases": ["解除全体禁言"], "description": "关闭全体禁言", "handler": "unban_all", "min_role": "admin"},
    {"name": "kick", "aliases": ["踢出", "踢人"], "description": "踢出群成员", "handler": "kick", "min_role": "admin"},
    {"name": "group_info", "aliases": ["群信息", "群管理"], "description": "查看群信息与配置", "handler": "group_info", "min_role": "member"},
    {"name": "repos", "aliases": ["仓库列表"], "description": "查看监控中的 GitHub 仓库", "handler": "repos", "min_role": "member"},
    {"name": "check_update", "aliases": ["版本检查"], "description": "立即检查仓库更新", "handler": "check_update", "min_role": "admin"},
    {"name": "clear_context", "aliases": ["清除上下文"], "description": "清除 AI 对话上下文", "handler": "clear_context", "min_role": "member"},
]


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
async def get_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    return row.value.get("value", default) if row else default


async def resolve_role(db: AsyncSession, account_id: int, event: AdapterEvent, user_id: int) -> str:
    if user_id in {int(x) for x in (await get_setting(db, "bot_super_admins", []) or []) if str(x).isdigit()}:
        return "super_admin"
    role = (event.sender or {}).get("role")
    if role in {"owner", "admin"}:
        return role
    group_id = event.group_id
    if group_id:
        group = await db.scalar(select(Group).where(Group.account_id == account_id, Group.group_number == group_id))
        if group:
            member = await db.scalar(
                select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == user_id)
            )
            if member and member.role in {"owner", "admin"}:
                return member.role
    return "member"


def _fmt_duration(seconds: int) -> str:
    if seconds >= 3600:
        hours = seconds / 3600
        return f"{hours:.1f} 小时" if hours % 1 else f"{int(hours)} 小时"
    if seconds >= 60:
        return f"{seconds // 60} 分钟"
    return f"{seconds} 秒"


async def _require_group(ctx: CommandContext) -> None:
    if ctx.is_private or not ctx.group_number:
        raise PermissionError("该命令只能在群聊中使用")


async def _require_capability(ctx: CommandContext, action: str) -> None:
    if not ctx.adapter.supports(action):
        raise UnsupportedAction(f"当前协议端不支持「{action}」，已取消操作")


# ---------------------------------------------------------------------------
# 处理器
# ---------------------------------------------------------------------------
@command("help", ["帮助", "菜单"])
async def cmd_help(ctx: CommandContext) -> str:
    rows = await ctx.db.scalars(select(BotCommand).where(BotCommand.enabled.is_(True)).order_by(BotCommand.id))
    lines = ["可用命令："]
    for item in rows:
        if ctx.rank < ROLE_RANK.get(item.min_role, 0):
            continue
        usage = item.usage or f"/{item.name}"
        lines.append(f"· {usage} — {item.description or ''}")
    return "\n".join(lines)


@command("status", ["状态"])
async def cmd_status(ctx: CommandContext) -> str:
    from app.services.account_manager import account_manager

    groups = await ctx.db.scalars(select(Group).where(Group.account_id == ctx.account_id))
    online = sum(1 for state in account_manager.all_states() if state.state == "online")
    return (
        f"机器人状态：在线\n账号：{ctx.account_name}\n"
        f"本账号已纳管群数：{len(list(groups))}\n"
        f"平台在线账号：{online}\n协议：{ctx.adapter.protocol}"
    )


@command("ping", [])
async def cmd_ping(ctx: CommandContext) -> str:
    latency = int((time.perf_counter() - ctx.started) * 1000)
    return f"pong（处理耗时 {latency} ms）"


@command("ai", ["问"])
async def cmd_ai(ctx: CommandContext) -> str:
    question = " ".join(ctx.args).strip()
    if not question:
        return "请提供问题内容，例如：/ai 今天天气怎么样"
    return ""  # 由引擎接管 AI 回复


@command("mute", ["禁言"])
async def cmd_mute(ctx: CommandContext) -> str:
    await _require_group(ctx)
    if ctx.rank < ROLE_RANK["admin"]:
        raise PermissionError("只有群管理员或以上权限才能禁言成员")
    target = ctx.target_user()
    if not target:
        return "请 @ 需要禁言的成员，例如：/禁言 @某人 10"
    duration = ctx.duration_seconds()
    await _require_capability(ctx, "set_group_ban")
    await ctx.adapter.set_group_ban(ctx.group_number, target, duration)
    return f"已禁言 {target}，时长 {_fmt_duration(duration)}"


@command("unmute", ["解禁", "解除禁言"])
async def cmd_unmute(ctx: CommandContext) -> str:
    await _require_group(ctx)
    if ctx.rank < ROLE_RANK["admin"]:
        raise PermissionError("只有群管理员或以上权限才能解除禁言")
    target = ctx.target_user()
    if not target:
        return "请 @ 需要解除禁言的成员"
    await _require_capability(ctx, "set_group_ban")
    await ctx.adapter.set_group_ban(ctx.group_number, target, 0)
    return f"已解除 {target} 的禁言"


@command("ban_all", ["全体禁言"])
async def cmd_ban_all(ctx: CommandContext) -> str:
    await _require_group(ctx)
    if ctx.rank < ROLE_RANK["admin"]:
        raise PermissionError("只有群管理员或以上权限才能开启全体禁言")
    await _require_capability(ctx, "set_group_whole_ban")
    await ctx.adapter.set_group_whole_ban(ctx.group_number, True)
    return "已开启全体禁言"


@command("unban_all", ["解除全体禁言"])
async def cmd_unban_all(ctx: CommandContext) -> str:
    await _require_group(ctx)
    if ctx.rank < ROLE_RANK["admin"]:
        raise PermissionError("只有群管理员或以上权限才能解除全体禁言")
    await _require_capability(ctx, "set_group_whole_ban")
    await ctx.adapter.set_group_whole_ban(ctx.group_number, False)
    return "已解除全体禁言"


@command("kick", ["踢出", "踢人"])
async def cmd_kick(ctx: CommandContext) -> str:
    await _require_group(ctx)
    if ctx.rank < ROLE_RANK["admin"]:
        raise PermissionError("只有群管理员或以上权限才能踢出成员")
    target = ctx.target_user()
    if not target:
        return "请 @ 需要踢出的成员"
    await _require_capability(ctx, "set_group_kick")
    await ctx.adapter.set_group_kick(ctx.group_number, target)
    return f"已踢出成员 {target}"


@command("group_info", ["群信息", "群管理"])
async def cmd_group_info(ctx: CommandContext) -> str:
    if not ctx.group or not ctx.settings:
        return "当前会话不在已纳管的群内"
    settings = ctx.settings
    return (
        f"群：{ctx.group.name or ctx.group.group_number}（{ctx.group.group_number}）\n"
        f"成员：{ctx.group.member_count} 人\n"
        f"AI：{'开启' if settings.ai_enabled else '关闭'}｜自动管理模式：{settings.moderation_mode}\n"
        f"命令前缀：{settings.command_prefix}"
    )


@command("repos", ["仓库列表"])
async def cmd_repos(ctx: CommandContext) -> str:
    rows = await ctx.db.scalars(select(GithubRepository).order_by(GithubRepository.id))
    items = list(rows)
    if not items:
        return "当前没有监控中的 GitHub 仓库"
    lines = ["监控中的仓库："]
    for repo in items:
        status = "监控中" if repo.monitor_enabled else "已暂停"
        lines.append(f"· {repo.full_name}｜最新版本 {repo.last_release_tag or '暂无'}｜{status}")
    return "\n".join(lines)


@command("check_update", ["版本检查"])
async def cmd_check_update(ctx: CommandContext) -> str:
    if ctx.rank < ROLE_RANK["admin"]:
        raise PermissionError("只有群管理员或以上权限才能触发版本检查")
    from app.services.github.monitor import check_all_repositories

    keyword = " ".join(ctx.args).strip().lower()
    results = await check_all_repositories(ctx.db, only_enabled=True)
    if keyword:
        results = [r for r in results if keyword in str(r.get("repository", "")).lower()]
    if not results:
        return "没有可检查的仓库（请先在后台添加仓库）"
    total_new = sum(int(r.get("new_releases") or 0) for r in results)
    total_pushed = sum(int(r.get("pushed") or 0) for r in results)
    return f"检查完成：{len(results)} 个仓库，发现 {total_new} 个新版本，已推送 {total_pushed} 条通知"


@command("clear_context", ["清除上下文"])
async def cmd_clear_context(ctx: CommandContext) -> str:
    from app.services.ai import service as ai_service

    scope = "private" if ctx.is_private else "group"
    conversation = await ai_service.get_or_create_conversation(
        ctx.db,
        account_id=ctx.account_id,
        scope=scope,
        group_number=ctx.group_number if not ctx.is_private else None,
        user_id=ctx.sender_id if ctx.is_private else None,
    )
    removed = await ai_service.clear_conversation(ctx.db, conversation.id)
    return f"已清除上下文（{removed} 条消息）"


async def seed_commands(db: AsyncSession) -> int:
    created = 0
    for item in BUILTIN_COMMANDS:
        exists = await db.scalar(select(BotCommand).where(BotCommand.name == item["name"]))
        if exists:
            exists.aliases = item.get("aliases", [])
            exists.description = item.get("description")
            exists.usage = item.get("usage")
            continue
        db.add(
            BotCommand(
                name=item["name"],
                aliases=item.get("aliases", []),
                description=item.get("description"),
                usage=item.get("usage"),
                handler=item["handler"],
                min_role=item.get("min_role", "member"),
                enabled=True,
                builtin=True,
            )
        )
        created += 1
    await db.commit()
    return created


async def dispatch(
    db: AsyncSession,
    *,
    account: Account,
    adapter: QQAdapter,
    event: AdapterEvent,
    settings: GroupSettings | None,
    group: Group | None,
    text: str,
) -> str | None:
    """解析并执行命令。返回要发送的文本（None 表示不处理）。"""
    prefix = (settings.command_prefix if settings else "/") or "/"
    body = text.strip()
    if body.startswith(prefix):
        body = body[len(prefix) :].strip()
    if not body:
        return None
    token, _, rest = body.partition(" ")
    resolved = registry.resolve(token)
    if not resolved:
        return None
    name, handler = resolved
    record = await db.scalar(select(BotCommand).where(BotCommand.name == name))
    if record and not record.enabled:
        return f"命令 /{name} 已被管理员禁用"
    sender_id = int(event.user_id or 0)
    role = await resolve_role(db, account.id, event, sender_id)
    required = record.min_role if record else "member"
    if ROLE_RANK.get(role, 0) < ROLE_RANK.get(required, 0):
        return f"权限不足：该命令需要「{ROLE_LABEL.get(required, required)}」权限"

    ats: list[int] = []
    message = event.raw.get("message")
    if isinstance(message, list):
        ats = [int(seg["data"]["qq"]) for seg in message if seg.get("type") == "at" and str(seg.get("data", {}).get("qq", "")).isdigit()]
    ctx = CommandContext(
        db=db,
        account_id=account.id,
        account_name=account.name,
        adapter=adapter,
        event=event,
        group_number=event.group_id,
        group=group,
        settings=settings,
        is_private=event.message_type == "private",
        sender_id=sender_id,
        sender_role=role,
        args=[a for a in rest.split(" ") if a.strip()],
        at_targets=ats,
        command_name=name,
    )
    try:
        result = await handler(ctx)
    except PermissionError as exc:
        return f"权限不足：{exc}"
    except UnsupportedAction as exc:
        return f"操作未执行：{exc}"
    except AdapterError as exc:
        return f"操作失败：{exc}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("命令执行异常 %s", name)
        return f"命令执行异常：{type(exc).__name__}: {exc}"
    finally:
        from app.services.logs import write_log

        await write_log(
            db,
            level="INFO",
            category="command",
            message=f"命令 /{name} 由 {sender_id}（{role}）在群 {event.group_id or '私聊'} 触发",
            account_id=account.id,
            context={"command": name, "args": rest, "role": role},
        )
    # 空字符串是有意义的返回值：表示「命令已接管，但回复交给 AI 生成」。
    # 这里不能用 `result or None`，否则空串会被吞成 None，/ai 永远不会触发回复。
    return result


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
