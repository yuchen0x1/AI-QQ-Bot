"""机器人事件引擎：消息落库、自动管理、命令分发、AI 对话、插件钩子。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, AdapterEvent, QQAdapter, UnsupportedAction
from app.core.config import settings as app_settings
from app.db.session import SessionLocal
from app.models import (
    Account,
    BotRequest,
    Group,
    GroupMember,
    GroupSettings,
    Message,
)
from app.services import commands as command_service
from app.services.ai import service as ai_service
from app.services.logs import write_log
from app.services.moderation import moderation, record_warning
from app.services.templates import render_template, truncate

logger = logging.getLogger("qbot.engine")

DEFAULT_WELCOME = "欢迎 {nickname} 加入 {group_name}！"
MAX_REPLY_CHARS = 1200


async def effective_blocked_words(db, group_settings: GroupSettings | None) -> list[str]:
    """AI 回复的过滤词：群配置违禁词 ∪ 系统设置 ai_blocked_words。

    系统设置这一项之前只写不读，管理员配了也不生效。这里合并去重后返回，
    任一来源为空都不影响另一来源。
    """
    from app.services.settings_store import read_setting

    words: list[str] = [w for w in ((group_settings.banned_words if group_settings else None) or []) if w]
    for item in await read_setting(db, "ai_blocked_words", []) or []:
        if isinstance(item, str) and item.strip():
            words.append(item.strip())
    # 去重但保留顺序
    return list(dict.fromkeys(words))


class BotEngine:
    """消息处理入口。

    AI 回复是整条链路里唯一的高延迟环节（上游模型通常 3~60 秒），因此它被放进
    后台任务执行：消息落库、自动管理、命令响应仍然在事件流里同步完成，保证顺序和
    即时性；只有 AI 生成被移到独立任务，并按账号限流、按会话串行。
    这样一条慢请求不会阻塞同账号其他群/私聊的消息处理。
    """

    def __init__(self) -> None:
        self._ai_tasks: set[asyncio.Task[None]] = set()
        # account_id -> (并发上限, 信号量)；上限调整后自动重建。
        self._ai_limits: dict[int, tuple[int, asyncio.Semaphore]] = {}
        # (account_id, scope, target) -> 会话锁，保证同一群/私聊内的消息按到达顺序处理。
        self._session_locks: dict[tuple[int, str, int], asyncio.Lock] = {}
        self._ai_pending: dict[int, dict[tuple[str, int], deque[tuple]]] = {}
        self._ai_order: dict[int, deque[tuple[str, int]]] = {}
        self._ai_runners: dict[int, asyncio.Task] = {}
        self._ai_account_tasks: dict[int, set[asyncio.Task]] = {}
        self._ai_wake: dict[int, asyncio.Event] = {}

    async def cancel_account(self, account_db_id: int) -> None:
        pending = self._ai_pending.pop(account_db_id, {})
        self._ai_order.pop(account_db_id, None)
        self._ai_wake.pop(account_db_id, None)
        for queue in pending.values():
            for entry in queue:
                await self._finish_inbox(entry[1], entry[2], error="account stopped before AI processing")
        tasks = list(self._ai_account_tasks.pop(account_db_id, set()))
        runner = self._ai_runners.pop(account_db_id, None)
        if runner:
            tasks.append(runner)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _finish_inbox(self, adapter: QQAdapter, event: AdapterEvent, *, error: str | None = None) -> None:
        inbox_id = int(event.raw.get("_inbox_id") or 0)
        token = event.raw.get("_inbox_claim")
        if inbox_id and token:
            from app.services import qq_inbox

            with contextlib.suppress(Exception):
                await qq_inbox.finish(inbox_id, token, error=error)
            underlying = getattr(adapter, "adapter", adapter)
            if hasattr(underlying, "release_inbox"):
                underlying.release_inbox(inbox_id)

    # ------------------------------------------------------------------
    def _ai_semaphore(self, account_db_id: int) -> asyncio.Semaphore:
        limit = max(1, int(app_settings.ai_max_concurrency))
        current = self._ai_limits.get(account_db_id)
        if current and current[0] == limit:
            return current[1]
        semaphore = asyncio.Semaphore(limit)
        self._ai_limits[account_db_id] = (limit, semaphore)
        return semaphore

    def _session_lock(self, account_db_id: int, event: AdapterEvent) -> asyncio.Lock:
        scope = "private" if event.message_type == "private" else "group"
        target = int(event.user_id or 0) if scope == "private" else int(event.group_id or 0)
        key = (account_db_id, scope, target)
        lock = self._session_locks.get(key)
        if lock is None:
            if len(self._session_locks) > 2000:
                # 只回收当前无人持有的锁；等待中的锁 locked() 为 True，不会被误删。
                for stale in [item for item, value in self._session_locks.items() if not value.locked()][:500]:
                    self._session_locks.pop(stale, None)
            lock = asyncio.Lock()
            self._session_locks[key] = lock
        return lock

    def schedule_ai_reply(
        self,
        account_db_id: int,
        adapter: QQAdapter,
        event: AdapterEvent,
        text: str,
        *,
        forced: bool = False,
    ) -> bool:
        """Admit a bounded request before creating any task; rotate scopes fairly."""
        scope = "private" if event.message_type == "private" else "group"
        target = int(event.user_id or 0) if scope == "private" else int(event.group_id or 0)
        key = (scope, target)
        queues = self._ai_pending.setdefault(account_db_id, {})
        total = sum(len(q) for groups in self._ai_pending.values() for q in groups.values())
        account_total = sum(len(q) for q in queues.values())
        per_scope = max(1, int(getattr(app_settings, "ai_queue_per_scope", 8)))
        limit = max(1, int(getattr(app_settings, "ai_queue_max_pending", 64)))
        user_pending = sum(1 for q in queues.values() for entry in q if entry[2].user_id == event.user_id)
        user_limit = max(1, per_scope // 2)
        if total >= limit * 4 or account_total >= limit or len(queues.get(key, [])) >= per_scope or user_pending >= user_limit:
            return False
        if key not in queues:
            queues[key] = deque()
            self._ai_order.setdefault(account_db_id, deque()).append(key)
        queues[key].append((time.monotonic(), adapter, event, text, forced))
        self._ai_wake.setdefault(account_db_id, asyncio.Event()).set()
        event.raw["_inbox_deferred"] = True
        runner = self._ai_runners.get(account_db_id)
        if runner is None or runner.done():
            runner = asyncio.create_task(self._run_ai_queue(account_db_id), name=f"qbot-ai-queue-{account_db_id}")
            self._ai_runners[account_db_id] = runner
            self._ai_tasks.add(runner)
            runner.add_done_callback(self._ai_tasks.discard)
        return True

    async def _run_ai_queue(self, account_db_id: int) -> None:
        active: dict[asyncio.Task, tuple[str, int]] = {}
        self._ai_account_tasks[account_db_id] = set()
        try:
            while True:
                queues = self._ai_pending.get(account_db_id, {})
                order = self._ai_order.get(account_db_id, deque())
                wait_limit = max(0.01, min(float(getattr(app_settings, "ai_queue_wait_seconds", 30)),
                                           float(getattr(app_settings, "ai_call_deadline_seconds", 120))))
                for key, queue in list(queues.items()):
                    while queue and time.monotonic() - queue[0][0] >= wait_limit:
                        _, stale_adapter, stale_event, _, _ = queue.popleft()
                        await self._finish_inbox(stale_adapter, stale_event, error="AI queue deadline exceeded")
                    if not queue:
                        queues.pop(key, None)
                        with contextlib.suppress(ValueError):
                            order.remove(key)
                concurrency = max(1, int(app_settings.ai_max_concurrency))
                searched = 0
                while order and len(active) < concurrency and searched < len(order):
                    key = order.popleft()
                    if key in active.values():
                        order.append(key)
                        searched += 1
                        continue
                    queue = queues[key]
                    queued_at, adapter, event, text, forced = queue.popleft()
                    if queue:
                        order.append(key)
                    else:
                        queues.pop(key)
                    if time.monotonic() - queued_at >= wait_limit:
                        await self._finish_inbox(adapter, event, error="AI queue deadline exceeded")
                        searched = 0
                        continue
                    task = asyncio.create_task(self._ai_reply_task(
                        account_db_id, adapter, event, text, forced=forced,
                        deadline=queued_at + float(getattr(app_settings, "ai_call_deadline_seconds", 120)),
                    ), name=f"qbot-ai-{account_db_id}")
                    active[task] = key
                    self._ai_account_tasks[account_db_id].add(task)
                    self._ai_tasks.add(task)
                    task.add_done_callback(self._ai_tasks.discard)
                    searched = 0
                if not active:
                    if not order:
                        return
                    continue
                wake = self._ai_wake.setdefault(account_db_id, asyncio.Event())
                wake.clear()
                waiter = asyncio.create_task(wake.wait())
                next_expiry = min((queue[0][0] + wait_limit for queue in queues.values() if queue), default=None)
                try:
                    done, _ = await asyncio.wait(
                        [*active, waiter], return_when=asyncio.FIRST_COMPLETED,
                        timeout=max(0.001, next_expiry - time.monotonic()) if next_expiry is not None else None,
                    )
                finally:
                    waiter.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await waiter
                for task in done:
                    if task is waiter:
                        continue
                    active.pop(task, None)
                    self._ai_account_tasks.get(account_db_id, set()).discard(task)
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        task.result()
        finally:
            for task in active:
                task.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)
            self._ai_account_tasks.pop(account_db_id, None)

    async def _ai_reply_task(
        self,
        account_db_id: int,
        adapter: QQAdapter,
        event: AdapterEvent,
        text: str,
        *,
        forced: bool = False,
        deadline: float | None = None,
    ) -> None:
        error: str | None = None
        try:
            remaining = deadline - time.monotonic() if deadline is not None else float(getattr(app_settings, "ai_call_deadline_seconds", 120))
            async with asyncio.timeout(max(0.01, remaining)):
                async with SessionLocal() as db:
                    account = await db.get(Account, account_db_id)
                    if not account or not account.enabled:
                        return
                    group: Group | None = None
                    group_settings: GroupSettings | None = None
                    if event.message_type == "group" and event.group_id:
                        group = await db.scalar(
                            select(Group).where(
                                Group.account_id == account.id,
                                Group.group_number == event.group_id,
                            )
                        )
                        if group:
                            group_settings = await db.scalar(
                                select(GroupSettings).where(GroupSettings.group_id == group.id)
                            )
                    await self._ai_reply(
                        db,
                        account,
                        adapter,
                        event,
                        group,
                        group_settings,
                        text,
                        forced=forced,
                    )
        except asyncio.CancelledError:
            error = "AI processing cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - 后台任务不能静默失败
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("AI 后台回复失败 account=%s: %s", account_db_id, exc)
            try:
                async with SessionLocal() as db:
                    await write_log(
                        db,
                        level="ERROR",
                        category="ai",
                        message=f"AI 后台回复异常：{type(exc).__name__}: {exc}",
                        account_id=account_db_id,
                    )
            except Exception:  # noqa: BLE001
                logger.warning("写入 AI 异常日志失败", exc_info=True)
        finally:
            await self._finish_inbox(adapter, event, error=error)

    # ------------------------------------------------------------------
    async def handle_event(self, db: AsyncSession, account_db_id: int, adapter: QQAdapter, event: AdapterEvent) -> None:
        account = await db.get(Account, account_db_id)
        if not account:
            return
        if event.post_type == "message":
            await self.handle_message(db, account, adapter, event)
        elif event.post_type == "notice":
            await self.handle_notice(db, account, adapter, event)
        elif event.post_type == "request":
            await self.handle_request(db, account, event)

    async def handle_request(self, db: AsyncSession, account: Account, event: AdapterEvent) -> None:
        raw = event.raw or {}
        request_type = raw.get("request_type")
        sub_type = str(event.sub_type or raw.get("sub_type") or "add")
        flag = str(raw.get("flag") or "").strip()
        user_id = int(event.user_id or raw.get("user_id") or 0)
        group_id = int(event.group_id or raw.get("group_id") or 0) or None
        if request_type not in {"group", "friend"} or not flag or not user_id:
            await write_log(
                db,
                level="WARNING",
                category="qq",
                message="收到字段不完整或类型未知的申请事件，未写入待审核队列",
                account_id=account.id,
                context=raw,
            )
            return
        existing = await db.scalar(
            select(BotRequest).where(
                BotRequest.account_id == account.id,
                BotRequest.request_type == request_type,
                BotRequest.flag == flag,
            )
        )
        if existing:
            return
        request = BotRequest(
            account_id=account.id,
            request_type=request_type,
            sub_type=sub_type,
            flag=flag,
            user_id=user_id,
            group_id=group_id,
            comment=raw.get("comment"),
            raw=raw,
        )
        db.add(request)
        await db.commit()
        await write_log(
            db,
            level="INFO",
            category="qq",
            message=f"收到{('加群' if request_type == 'group' else '好友')}{('邀请' if sub_type == 'invite' else '申请')}，等待管理员审核",
            account_id=account.id,
            context={"request_id": request.id, "user_id": user_id, "group_id": group_id},
        )

    # ------------------------------------------------------------------
    async def _ensure_group(
        self, db: AsyncSession, account: Account, group_number: int, event: AdapterEvent | None = None
    ) -> tuple[Group, GroupSettings]:
        group = await db.scalar(
            select(Group).where(Group.account_id == account.id, Group.group_number == group_number)
        )
        if not group:
            group = Group(
                account_id=account.id,
                group_number=group_number,
                name=(event.raw.get("group_name") if event else None) or f"群 {group_number}",
                member_count=0,
                max_member_count=0,
            )
            db.add(group)
            await db.commit()
            await db.refresh(group)
        settings = await db.scalar(select(GroupSettings).where(GroupSettings.group_id == group.id))
        if not settings:
            settings = GroupSettings(group_id=group.id)
            db.add(settings)
            await db.commit()
            await db.refresh(settings)
        return group, settings

    async def _upsert_member(
        self, db: AsyncSession, group: Group, event: AdapterEvent, *, count_message: bool = True,
        commit: bool = True,
    ) -> GroupMember | None:
        uid = int(event.user_id or 0)
        if not uid:
            return None
        member = await db.scalar(
            select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == uid)
        )
        if not member:
            member = GroupMember(group_id=group.id, user_id=uid, role=(event.sender or {}).get("role") or "member")
            db.add(member)
        member.nickname = event.sender.get("nickname") or member.nickname
        member.card = event.sender.get("card") or member.card
        member.role = (event.sender or {}).get("role") or member.role or "member"
        member.last_active_at = datetime.now(timezone.utc)
        if count_message:
            member.message_count = (member.message_count or 0) + 1
        if commit:
            await db.commit()
        return member

    # ------------------------------------------------------------------
    async def handle_message(self, db: AsyncSession, account: Account, adapter: QQAdapter, event: AdapterEvent) -> None:
        text = (event.raw_message or "").strip()
        group: Group | None = None
        settings: GroupSettings | None = None
        member: GroupMember | None = None
        inbox_id = int(event.raw.get("_inbox_id") or 0) or None
        record = await db.scalar(select(Message).where(Message.inbox_id == inbox_id)) if inbox_id else None
        if event.message_type == "group" and event.group_id:
            group, settings = await self._ensure_group(db, account, event.group_id, event)

            from app.services.github.automation import bind_from_message

            binding_reply = await bind_from_message(db, account.id, event.group_id, self._clean_text(event, text))
            if binding_reply:
                # Do not persist the one-time code in message history or send it to AI.
                await self.send_text(db, account, adapter, binding_reply, group_number=event.group_id, user_id=event.user_id)
                from app.services.scheduler import scheduler_service

                scheduler_service.request_activity_sync()
                return
            member = await self._upsert_member(db, group, event, count_message=record is None, commit=False)

        if record is None:
            record = Message(
                account_id=account.id, inbox_id=inbox_id,
                group_id=group.id if group else None,
                qq_group=event.group_id,
                message_id=event.message_id,
                direction="in",
                message_type=event.message_type or "group",
                sender_id=event.user_id,
                sender_name=event.sender_name,
                content=text,
                raw=event.raw,
            )
            db.add(record)
        await db.commit()
        await db.refresh(record)

        # 1) 自动管理
        if group and settings and member:
            verdict = await moderation.evaluate(
                db,
                account_id=account.id,
                group_number=group.group_number,
                user_id=int(event.user_id or 0),
                content=text,
                settings=settings,
                member=member,
                sender_role=member.role,
            )
            if verdict.action != "none":
                await record_warning(db, member)
                record.blocked = True
                record.block_reason = verdict.reason[:190]
                await db.commit()
                await self._apply_moderation(db, account, adapter, group, settings, member, verdict)
                if verdict.action in {"mute", "kick"}:
                    return

        # 2) 命令
        command_reply: str | None = None
        handled_by_ai = False
        if text:
            command_reply = await command_service.dispatch(
                db, account=account, adapter=adapter, event=event, settings=settings, group=group, text=text
            )
            if command_reply == "":
                handled_by_ai = True
                command_reply = None
        if command_reply:
            await self.send_text(db, account, adapter, command_reply, group_number=event.group_id, user_id=event.user_id)
            return

        # Explicit /ai wins; plugin commands and hooks run before implicit AI.
        if handled_by_ai:
            accepted = self.schedule_ai_reply(account.id, adapter, event, text, forced=True)
            if not accepted:
                await self.send_text(db, account, adapter, "AI 请求排队已满，请稍后再试。", group_number=event.group_id, user_id=event.user_id)
            return

        if await self._run_plugin_hooks(db, account, adapter, event, self._clean_text(event, text)):
            return
        if await self._should_reply_with_ai(event, settings):
            if not self.schedule_ai_reply(account.id, adapter, event, text):
                await self.send_text(db, account, adapter, "AI 请求排队已满，请稍后再试。", group_number=event.group_id, user_id=event.user_id)

    # ------------------------------------------------------------------
    async def _should_reply_with_ai(self, event: AdapterEvent, settings: GroupSettings | None) -> bool:
        if event.message_type == "private":
            return True
        if not settings or not settings.ai_enabled:
            return False
        if not settings.require_at_for_ai:
            return True
        return event.is_at_me

    def _clean_text(self, event: AdapterEvent, text: str) -> str:
        cleaned = text
        if event.self_id:
            cleaned = cleaned.replace(f"[CQ:at,qq={event.self_id}]", " ")
        message = event.raw.get("message")
        if isinstance(message, list):
            parts = []
            for seg in message:
                if seg.get("type") == "text":
                    parts.append(seg.get("data", {}).get("text", ""))
                elif seg.get("type") == "at" and str(seg.get("data", {}).get("qq")) != str(event.self_id):
                    parts.append("@" + str(seg["data"].get("qq")))
            cleaned = " ".join(parts) if parts else cleaned
        return cleaned.strip()

    async def _ai_reply(
        self,
        db: AsyncSession,
        account: Account,
        adapter: QQAdapter,
        event: AdapterEvent,
        group: Group | None,
        settings: GroupSettings | None,
        text: str,
        *,
        forced: bool = False,
    ) -> None:
        if event.message_type == "group" and settings and not settings.ai_enabled and not forced:
            return
        question = self._clean_text(event, text)
        if not question:
            await self.send_text(
                db, account, adapter, "你好，有什么可以帮你？", group_number=event.group_id, user_id=event.user_id
            )
            return
        if len(question) > 2000:
            question = question[:2000]

        model = await ai_service.resolve_model(
            db,
            account_id=account.id,
            group_number=event.group_id,
        )
        if not model:
            await self.send_text(
                db,
                account,
                adapter,
                "尚未配置 AI 模型。发送「菜单」查看可用指令；管理员可在后台「AI 模型中心」接入模型后开启智能对话。",
                group_number=event.group_id,
                user_id=event.user_id,
            )
            return

        scope = "private" if event.message_type == "private" else "group"
        system_prompt = ai_service.build_system_prompt(settings)
        conversation = await ai_service.get_or_create_conversation(
            db,
            account_id=account.id,
            scope=scope,
            group_number=event.group_id if scope == "group" else None,
            user_id=int(event.user_id or 0) if scope == "private" else None,
            system_prompt=system_prompt,
        )
        limit = settings.ai_context_limit if settings else 10
        history = await ai_service.conversation_history(db, conversation.id, limit=limit * 2)
        messages = [*history, {"role": "user", "content": question}]
        if scope == "group":
            messages[-1]["content"] = f"{event.sender_name}：{question}"

        started = time.perf_counter()
        result, error, used_model = await ai_service.chat_once(
            db, model, messages, system=system_prompt, account_id=account.id, group_number=event.group_id,
            user_id=event.user_id,
        )
        latency = int((time.perf_counter() - started) * 1000)
        if not result or not (result.content or "").strip():
            await write_log(
                db,
                level="ERROR",
                category="ai",
                message=f"AI 回复失败：{error}",
                account_id=account.id,
                context={"model": model.model_name, "group": event.group_id},
            )
            await self.send_text(
                db,
                account,
                adapter,
                "AI 暂时不可用，请稍后再试。",
                group_number=event.group_id,
                user_id=event.user_id,
            )
            return

        blocked_words = await effective_blocked_words(db, settings)
        answer = result.content.strip()
        if any(word and word in answer for word in blocked_words):
            answer = "（该回复触发内容安全过滤，已拦截）"
        answer = truncate(answer, MAX_REPLY_CHARS)

        await ai_service.append_message(
            db, conversation, "user", question, tokens=result.prompt_tokens, model_name=used_model.model_name
        )
        await ai_service.append_message(
            db,
            conversation,
            "assistant",
            answer,
            tokens=result.completion_tokens,
            model_name=used_model.model_name,
            latency_ms=latency,
        )
        await ai_service.trim_conversation(db, conversation.id, keep=max(2, limit * 2))
        await self.send_text(db, account, adapter, answer, group_number=event.group_id, user_id=event.user_id)

    # ------------------------------------------------------------------
    async def _apply_moderation(
        self,
        db: AsyncSession,
        account: Account,
        adapter: QQAdapter,
        group: Group,
        settings: GroupSettings,
        member: GroupMember,
        verdict,
    ) -> None:
        from app.services.logs import audit

        action_taken = "none"
        error: str | None = None
        try:
            if verdict.action == "mute" and adapter.supports("set_group_ban"):
                await adapter.set_group_ban(group.group_number, member.user_id, verdict.duration)
                member.muted_until = (
                    datetime.now(timezone.utc).replace(microsecond=0)
                    + timedelta(seconds=max(0, int(verdict.duration or 0)))
                )
                action_taken = "mute"
            elif verdict.action == "kick" and adapter.supports("set_group_kick"):
                await adapter.set_group_kick(group.group_number, member.user_id)
                action_taken = "kick"
            elif verdict.action == "warn":
                await self.send_text(
                    db,
                    account,
                    adapter,
                    f"@{member.user_id} 请注意：{verdict.reason}",
                    group_number=group.group_number,
                )
                action_taken = "warn"
            else:
                action_taken = "skipped" if verdict.action != "none" else "none"
                error = "协议端不支持对应管理操作" if verdict.action != "none" else None
        except (AdapterError, UnsupportedAction) as exc:
            error = str(exc)
            action_taken = "failed"
        await write_log(
            db,
            level="WARNING" if verdict.action in {"mute", "kick"} else "INFO",
            category="moderation",
            message=f"自动管理：{verdict.reason} | 处置={action_taken}{' | ' + error if error else ''}",
            account_id=account.id,
            context={
                "group": group.group_number,
                "user_id": member.user_id,
                "action": verdict.action,
                "result": action_taken,
                "error": error,
            },
        )
        await audit(
            db,
            user_id=None,
            username=f"bot:{account.name}",
            action=f"auto_moderation:{verdict.action}",
            target=f"group:{group.group_number}/user:{member.user_id}",
            detail=verdict.reason,
        )

    # ------------------------------------------------------------------
    async def handle_notice(self, db: AsyncSession, account: Account, adapter: QQAdapter, event: AdapterEvent) -> None:
        if not event.group_id:
            return
        group, settings = await self._ensure_group(db, account, event.group_id, event)
        sub = event.sub_type or ""
        if sub == "group_increase":
            text = settings.welcome_template or DEFAULT_WELCOME
            if settings.welcome_enabled and adapter.supports("send_group_message"):
                message = render_template(
                    text,
                    {
                        "nickname": event.sender_name or event.user_id,
                        "user_id": event.user_id,
                        "group_name": group.name or group.group_number,
                        "group_id": group.group_number,
                        "account_name": account.name,
                    },
                )
                await self.send_text(db, account, adapter, message, group_number=group.group_number)
            await write_log(
                db,
                level="INFO",
                category="group",
                message=f"群 {group.group_number} 有新成员加入：{event.user_id}",
                account_id=account.id,
            )
        elif sub == "group_decrease":
            if settings.member_change_notify and adapter.supports("send_group_message"):
                await self.send_text(
                    db,
                    account,
                    adapter,
                    f"成员 {event.user_id} 已退出或移出本群（{group.name or group.group_number}）",
                    group_number=group.group_number,
                )
        elif sub == "group_ban":
            await write_log(
                db,
                level="INFO",
                category="group",
                message=f"群 {group.group_number} 禁言事件：用户 {event.raw.get('user_id')} 时长 {event.raw.get('duration')}s",
                account_id=account.id,
                context=event.raw,
            )
        elif sub in {"group_admin", "group_card"}:
            await self._upsert_member(db, group, event, count_message=False)

    # ------------------------------------------------------------------
    async def send_text(
        self,
        db: AsyncSession,
        account: Account,
        adapter: QQAdapter,
        text: str,
        *,
        group_number: int | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        if not text:
            return None
        from app.services.account_manager import account_manager

        underlying = getattr(adapter, "adapter", adapter)
        if account_manager.adapter(account.id) is not underlying:
            raise AdapterError("账号连接已停止或已更换，取消旧连接的发送")
        payload = truncate(text, MAX_REPLY_CHARS)
        try:
            if group_number:
                if not adapter.supports("send_group_message"):
                    raise UnsupportedAction("当前协议端不支持发送群消息")
                result = await adapter.send_group_message(group_number, payload)
                direction_type = "group"
            elif user_id:
                if not adapter.supports("send_private_message"):
                    raise UnsupportedAction("当前协议端不支持发送私聊消息")
                result = await adapter.send_private_message(user_id, payload)
                direction_type = "private"
            else:
                return None
        except (AdapterError, UnsupportedAction) as exc:
            await write_log(
                db,
                level="ERROR",
                category="qq",
                message=f"消息发送失败：{exc}",
                account_id=account.id,
                context={"group": group_number, "user": user_id},
            )
            raise
        data = result.get("data") or {}
        group = None
        if group_number:
            group = await db.scalar(
                select(Group).where(Group.account_id == account.id, Group.group_number == group_number)
            )
        db.add(
            Message(
                account_id=account.id,
                group_id=group.id if group else None,
                qq_group=group_number,
                message_id=data.get("message_id"),
                direction="out",
                message_type=direction_type,
                sender_id=account.qq_number,
                sender_name=account.nickname or account.name,
                content=payload,
            )
        )
        await db.commit()
        return result

    # ------------------------------------------------------------------
    async def _run_plugin_hooks(
        self, db: AsyncSession, account: Account, adapter: QQAdapter, event: AdapterEvent, text: str
    ) -> bool:
        from app.services.plugins import plugin_manager

        if not plugin_manager.loaded:
            return False
        result = await plugin_manager.dispatch(
            db,
            account_id=account.id,
            group_number=event.group_id,
            user_id=int(event.user_id or 0),
            text=text,
            sender_name=event.sender_name,
        )
        for reply in result.replies:
            await self.send_text(db, account, adapter, reply, group_number=event.group_id, user_id=event.user_id)
        return result.handled


engine = BotEngine()
