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
from app.models import Account, BotCommand, Group, GroupMember, GroupSettings, GithubRepository
from app.services.bot_reply import BotReply

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
    raw_args: str = ""
    features: dict[str, Any] = field(default_factory=dict)
    started: float = field(default_factory=time.perf_counter)

    @property
    def prefix(self) -> str:
        return (self.settings.command_prefix if self.settings else "/") or "/"

    @property
    def api_session_key(self) -> tuple[int, int, int]:
        return (self.account_id, self.group_number or 0, self.sender_id)

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


CommandHandler = Callable[[CommandContext], Awaitable[str | BotReply]]


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
    {"name": "help", "aliases": ["帮助"], "description": "查看可用命令", "handler": "help", "min_role": "member"},
    {"name": "menu", "aliases": ["菜单", "功能菜单"], "description": "查看素颜 API 分页功能菜单", "handler": "menu", "min_role": "member", "usage": "/菜单 [页码]"},
    {"name": "api", "aliases": ["接口", "API"], "description": "选择并调用菜单中的 API", "handler": "api", "min_role": "member", "usage": "/接口 编号或ID [参数名=值]"},
    {"name": "api_search", "aliases": ["搜索接口"], "description": "按关键词查找 API", "handler": "api_search", "min_role": "member", "usage": "/搜索接口 关键词"},
    {"name": "api_cancel", "aliases": ["取消接口"], "description": "取消当前 API 参数填写", "handler": "api_cancel", "min_role": "member"},
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
    from app.services.settings_store import read_setting

    return await read_setting(db, key, default)


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
@command("help", ["帮助"])
async def cmd_help(ctx: CommandContext) -> str:
    rows = await ctx.db.scalars(select(BotCommand).where(BotCommand.enabled.is_(True)).order_by(BotCommand.id))
    lines = ["可用命令："]
    for item in rows:
        if ctx.rank < ROLE_RANK.get(item.min_role, 0):
            continue
        usage = item.usage or f"/{item.name}"
        lines.append(f"· {usage} — {item.description or ''}")
    return "\n".join(lines)


def _require_api_menu(ctx: CommandContext) -> None:
    if not ctx.features.get("official_api_menu_enabled", True):
        raise PermissionError("该账号已关闭 API 菜单，管理员可在账号设置中开启")


def _split_command(body: str) -> tuple[str, str]:
    """Split a command and accept compact Chinese page commands such as 菜单2."""
    parts = body.split(maxsplit=1)
    token = parts[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""
    for alias in ("菜单", "功能菜单", "menu"):
        if not token.startswith(alias):
            continue
        suffix = token[len(alias):]
        if suffix.isdecimal():
            token = alias
            rest = f"{suffix} {rest}".strip()
            break
    return token, rest


@command("menu", ["菜单", "功能菜单"])
async def cmd_menu(ctx: CommandContext) -> BotReply:
    from app.services.suyan import suyan_service

    _require_api_menu(ctx)
    suyan_service.cancel_session(ctx.api_session_key)
    argument = ctx.raw_args.strip()
    if not argument:
        return suyan_service.build_menu(prefix=ctx.prefix)
    page_or_query, query = argument.split(maxsplit=1) if " " in argument else (argument, "")
    if page_or_query.isdecimal():
        return suyan_service.build_menu(page=page_or_query, query=query, prefix=ctx.prefix)
    return suyan_service.build_menu(query=argument, prefix=ctx.prefix)


@command("api", ["接口", "API"])
async def cmd_api(ctx: CommandContext) -> BotReply:
    from app.services.suyan import suyan_service

    _require_api_menu(ctx)
    parts = ctx.raw_args.strip().split(maxsplit=1)
    key = parts[0] if parts else ""
    arguments = parts[1] if len(parts) > 1 else ""
    if not key:
        return BotReply(f"用法：{ctx.prefix}接口 编号或ID 参数名=值\n发送「菜单」查看功能；需要填写的参数会逐项提示。")
    return await suyan_service.execute(key, arguments, ctx.api_session_key, prefix=ctx.prefix)


@command("api_search", ["搜索接口"])
async def cmd_api_search(ctx: CommandContext) -> BotReply:
    from app.services.suyan import suyan_service

    _require_api_menu(ctx)
    suyan_service.cancel_session(ctx.api_session_key)
    if not ctx.raw_args.strip():
        return BotReply(f"用法：{ctx.prefix}搜索接口 天气")
    return suyan_service.build_menu(query=ctx.raw_args.strip(), prefix=ctx.prefix)


@command("api_cancel", ["取消接口"])
async def cmd_api_cancel(ctx: CommandContext) -> BotReply:
    from app.services.suyan import suyan_service

    return suyan_service.cancel_session(ctx.api_session_key)


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
    from app.services.github.access import command_repository_scope

    rows = await ctx.db.scalars(select(GithubRepository).where(command_repository_scope(
        ctx.account_id, ctx.group_number, is_private=ctx.is_private,
    )).order_by(GithubRepository.id))
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
    from app.services.github.access import command_repository_scope, notification_scope
    from app.services.github.monitor import check_repository

    keyword = " ".join(ctx.args).strip().lower()
    query = select(GithubRepository).where(
        command_repository_scope(ctx.account_id, ctx.group_number, is_private=ctx.is_private),
        GithubRepository.monitor_enabled.is_(True),
    )
    if keyword:
        query = query.where(GithubRepository.full_name.ilike(f"%{keyword}%"))
    repos = list(await ctx.db.scalars(query.order_by(GithubRepository.id)))
    results = []
    scope_token = notification_scope.set((ctx.account_id, ctx.group_number or 0))
    try:
        for repo in repos:
            results.append(await check_repository(ctx.db, repo))
    finally:
        notification_scope.reset(scope_token)
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


def is_api_request(account_id: int, event: AdapterEvent, settings: GroupSettings | None, text: str) -> bool:
    from app.services.suyan import suyan_service

    prefix = (settings.command_prefix if settings else "/") or "/"
    body = text.strip()
    if body.startswith(prefix):
        body = body[len(prefix):].strip()
    if not body:
        return False
    parts = body.split(maxsplit=1)
    resolved = registry.resolve(parts[0]) if parts else None
    if resolved:
        return resolved[0] == "api"
    return suyan_service.has_session((account_id, event.group_id or 0, int(event.user_id or 0)))


async def _continue_api_session(
    db: AsyncSession,
    *,
    account: Account,
    event: AdapterEvent,
    settings: GroupSettings | None,
    text: str,
    prefix: str,
) -> BotReply | str | None:
    from app.services.suyan import suyan_service

    key = (account.id, event.group_id or 0, int(event.user_id or 0))
    if not suyan_service.has_session(key):
        return None
    if not (account.features or {}).get("official_api_menu_enabled", True):
        suyan_service.cancel_session(key)
        return "该账号已关闭 API 菜单，当前参数填写已取消。"
    record = await db.scalar(select(BotCommand).where(BotCommand.name == "api"))
    role = await resolve_role(db, account.id, event, int(event.user_id or 0))
    if record and (not record.enabled or ROLE_RANK.get(role, 0) < ROLE_RANK.get(record.min_role, 0)):
        suyan_service.cancel_session(key)
        return "接口命令已被禁用或权限发生变化，当前参数填写已取消。"
    return await suyan_service.continue_session(text.strip(), key, prefix=prefix)


async def dispatch(
    db: AsyncSession,
    *,
    account: Account,
    adapter: QQAdapter,
    event: AdapterEvent,
    settings: GroupSettings | None,
    group: Group | None,
    text: str,
) -> str | BotReply | None:
    """解析并执行命令。None 表示未处理，空字符串仅用于显式 AI。"""
    prefix = (settings.command_prefix if settings else "/") or "/"
    body = text.strip()
    if body.startswith(prefix):
        body = body[len(prefix) :].strip()
    if not body:
        return None
    token, rest = _split_command(body)
    resolved = registry.resolve(token)
    if not resolved:
        return await _continue_api_session(
            db, account=account, event=event, settings=settings, text=text, prefix=prefix
        )
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
        raw_args=rest,
        features=account.features or {},
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
            context={"command": name, "args": "[API 参数已隐藏]" if name == "api" else rest, "role": role},
        )
    # 空字符串是有意义的返回值：表示「命令已接管，但回复交给 AI 生成」。
    # 这里不能用 `result or None`，否则空串会被吞成 None，/ai 永远不会触发回复。
    return result


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
