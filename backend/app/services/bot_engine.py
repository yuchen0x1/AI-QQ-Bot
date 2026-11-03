"""机器人事件引擎：消息落库、自动管理、命令分发、AI 对话、插件钩子。"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError, AdapterEvent, QQAdapter, UnsupportedAction
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


class BotEngine:
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
        self, db: AsyncSession, group: Group, event: AdapterEvent, *, count_message: bool = True
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
        await db.commit()
        return member

    # ------------------------------------------------------------------
    async def handle_message(self, db: AsyncSession, account: Account, adapter: QQAdapter, event: AdapterEvent) -> None:
        text = (event.raw_message or "").strip()
        group: Group | None = None
        settings: GroupSettings | None = None
        member: GroupMember | None = None
        if event.message_type == "group" and event.group_id:
            group, settings = await self._ensure_group(db, account, event.group_id, event)
            member = await self._upsert_member(db, group, event)

        record = Message(
            account_id=account.id,
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

        # 3) AI
        should_ai = handled_by_ai or await self._should_reply_with_ai(event, settings)
        if should_ai:
            await self._ai_reply(db, account, adapter, event, group, settings, text, forced=handled_by_ai)
            return

        # 4) 插件钩子
        await self._run_plugin_hooks(db, account, adapter, event, text)

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
                "尚未配置可用的 AI 模型，请管理员在后台「AI 模型中心」添加并测试。",
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
            db, model, messages, system=system_prompt, account_id=account.id, group_number=event.group_id
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

        blocked_words = (settings.banned_words if settings else []) or []
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
                member.muted_until = datetime.now(timezone.utc).replace(microsecond=0)
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
    ) -> None:
        from app.services.plugins import plugin_manager

        if not plugin_manager.loaded:
            return
        replies = await plugin_manager.dispatch_message(
            db,
            account_id=account.id,
            group_number=event.group_id,
            user_id=int(event.user_id or 0),
            text=text,
            sender_name=event.sender_name,
        )
        for reply in replies:
            await self.send_text(db, account, adapter, reply, group_number=event.group_id, user_id=event.user_id)


engine = BotEngine()
