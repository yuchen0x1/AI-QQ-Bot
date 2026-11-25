"""AI 服务中心：模型解析、会话上下文、调用与降级、统计。"""

from __future__ import annotations

import logging
import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret
from app.core.config import settings
from app.models.ai import conversation_scope_key
from app.models import (
    Account,
    AIMessage,
    AIModel,
    AIProvider,
    AIConversation,
    AIUsageLog,
    Group,
    GroupSettings,
)
from app.services.ai.providers import BaseAIProvider, ChatResult, build_provider

logger = logging.getLogger("qbot.ai.service")

DEFAULT_SYSTEM_PROMPT = (
    "你是 QQ 群里的一位友好、简洁的智能助手。回答要口语化、有重点，避免长篇大论；"
    "涉及不确定的信息时如实说明，不要编造。"
)


def provider_to_client(
    model: AIModel,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseAIProvider:
    provider: AIProvider = model.provider
    return build_provider(
        provider.kind,
        base_url=provider.base_url,
        api_key=decrypt_secret(provider.api_key_enc),
        model_name=model.model_name,
        temperature=temperature if temperature is not None else model.temperature,
        max_tokens=max_tokens if max_tokens is not None else model.max_tokens,
        timeout=model.timeout_seconds,
        extra_headers=provider.extra_headers or None,
    )


def _parse_model_ids(value: Any) -> set[int]:
    if not isinstance(value, list):
        return set()
    return {int(item) for item in value if isinstance(item, int) and not isinstance(item, bool) and item > 0}


async def _allowed_model_ids(db: AsyncSession, account_id: int | None, group_number: int | None) -> set[int] | None:
    """An absent restriction retains the shared administrative model pool.

    An explicitly empty/invalid list denies all models. Group restrictions can
    only narrow the account restriction; they cannot broaden it.
    """
    if account_id is None:
        return None
    account = await db.get(Account, account_id)
    if not account:
        return set()
    features = account.features or {}
    allowed = _parse_model_ids(features["ai_allowed_model_ids"]) if "ai_allowed_model_ids" in features else None
    group_rules = features.get("ai_group_model_ids", {})
    if group_number is not None and isinstance(group_rules, dict) and str(group_number) in group_rules:
        group_allowed = _parse_model_ids(group_rules[str(group_number)])
        allowed = group_allowed if allowed is None else allowed & group_allowed
    return allowed


async def resolve_model(
    db: AsyncSession,
    *,
    model_id: int | None = None,
    account_id: int | None = None,
    group_number: int | None = None,
) -> AIModel | None:
    """Explicit routes fail closed; only an unconfigured route uses defaults."""
    allowed = await _allowed_model_ids(db, account_id, group_number)

    def usable(model: AIModel | None) -> bool:
        return bool(model and model.enabled and model.provider and model.provider.enabled
                    and (allowed is None or model.id in allowed))

    if model_id is not None:
        model = await db.get(AIModel, model_id)
        return model if usable(model) else None

    if account_id and group_number:
        group = await db.scalar(
            select(Group).where(Group.account_id == account_id, Group.group_number == group_number)
        )
        if group:
            settings = await db.scalar(select(GroupSettings).where(GroupSettings.group_id == group.id))
            if settings and settings.ai_model_id:
                model = await db.get(AIModel, settings.ai_model_id)
                return model if usable(model) else None

    if account_id:
        account = await db.get(Account, account_id)
        if account and account.features:
            candidate = account.features.get("ai_model_id")
            if candidate:
                try:
                    model = await db.get(AIModel, int(candidate))
                except (TypeError, ValueError):
                    model = None
                return model if usable(model) else None

    default = await db.scalar(
        select(AIModel)
        .join(AIProvider, AIModel.provider_id == AIProvider.id)
        .where(
            AIModel.is_default.is_(True),
            AIModel.enabled.is_(True),
            AIProvider.enabled.is_(True),
            *([AIModel.id.in_(allowed)] if allowed is not None else []),
        )
        .order_by(AIModel.priority.asc(), AIModel.id.asc())
        .limit(1)
    )
    if default:
        return default
    return await db.scalar(
        select(AIModel)
        .join(AIProvider, AIModel.provider_id == AIProvider.id)
        .where(AIModel.enabled.is_(True), AIProvider.enabled.is_(True),
               *([AIModel.id.in_(allowed)] if allowed is not None else []))
        .order_by(AIModel.priority.asc(), AIModel.id.asc())
        .limit(1)
    )


async def fallback_models(
    db: AsyncSession,
    exclude_id: int | None = None,
    *,
    primary_model: AIModel | None = None,
    account_id: int | None = None,
    group_number: int | None = None,
    allow_cross_provider: bool | None = None,
) -> list[AIModel]:
    primary = primary_model or (await db.get(AIModel, exclude_id) if exclude_id else None)
    if primary is None:
        return []
    cross_provider = bool(primary.allow_cross_provider_fallback) and allow_cross_provider is not False
    allowed = await _allowed_model_ids(db, account_id, group_number)
    if account_id is not None:
        account = await db.get(Account, account_id)
        if account and (account.features or {}).get("ai_allow_cross_provider_fallback") is False:
            cross_provider = False
    rows = await db.scalars(
        select(AIModel)
        .join(AIProvider, AIModel.provider_id == AIProvider.id)
        .where(
            AIModel.enabled.is_(True),
            AIProvider.enabled.is_(True),
            AIModel.is_fallback.is_(True),
            AIModel.id != (exclude_id or -1),
            *([AIModel.provider_id == primary.provider_id] if not cross_provider else []),
            *([AIModel.id.in_(allowed)] if allowed is not None else []),
        )
        .order_by(AIModel.is_fallback.desc(), AIModel.priority.asc())
    )
    return list(rows)


async def _log_usage(
    db: AsyncSession,
    *,
    model: AIModel | None,
    account_id: int | None,
    group_number: int | None,
    status: str,
    result: ChatResult | None = None,
    latency_ms: int = 0,
    error: str | None = None,
) -> None:
    db.add(
        AIUsageLog(
            model_id=model.id if model else None,
            model_name=model.model_name if model else None,
            account_id=account_id,
            group_number=group_number,
            status=status,
            prompt_tokens=result.prompt_tokens if result else 0,
            completion_tokens=result.completion_tokens if result else 0,
            latency_ms=latency_ms,
            error=error,
        )
    )
    await db.commit()


async def _chat_once(
    db: AsyncSession,
    model: AIModel,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    account_id: int | None = None,
    group_number: int | None = None,
    allow_fallback: bool = True,
    temperature: float | None = None,
    max_tokens: int | None = None,
    allow_cross_provider_fallback: bool | None = None,
) -> tuple[ChatResult | None, str | None, AIModel]:
    """调用模型，带重试与备用模型降级。返回 (结果, 错误, 实际使用的模型)。"""
    allowed = await _allowed_model_ids(db, account_id, group_number)
    if not model.enabled or not model.provider or not model.provider.enabled or (allowed is not None and model.id not in allowed):
        return None, "模型已停用或不在当前账号/群授权范围", model
    attempts = max(1, model.retries + 1)
    last_error: str | None = None
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            client = provider_to_client(model, temperature=temperature, max_tokens=max_tokens)
            result = await client.chat(messages, system=system)
            latency = int((time.perf_counter() - started) * 1000)
            model.total_calls += 1
            model.total_tokens += result.total_tokens
            await db.commit()
            await _log_usage(
                db,
                model=model,
                account_id=account_id,
                group_number=group_number,
                status="success",
                result=result,
                latency_ms=latency,
            )
            return result, None, model
        except Exception as exc:  # noqa: BLE001 - 上游异常记录后按已授权的链降级
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("AI 调用失败 model=%s attempt=%s/%s err=%s", model.model_name, attempt + 1, attempts, last_error)
            model.total_calls += 1
            model.total_errors += 1
            await db.commit()
            await _log_usage(
                db,
                model=model,
                account_id=account_id,
                group_number=group_number,
                status="error",
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=last_error,
            )

    if allow_fallback:
        for backup in await fallback_models(
            db, exclude_id=model.id, primary_model=model, account_id=account_id,
            group_number=group_number, allow_cross_provider=allow_cross_provider_fallback,
        ):
            try:
                client = provider_to_client(backup)
                started = time.perf_counter()
                result = await client.chat(messages, system=system)
                latency = int((time.perf_counter() - started) * 1000)
                backup.total_calls += 1
                backup.total_tokens += result.total_tokens
                await db.commit()
                await _log_usage(
                    db,
                    model=backup,
                    account_id=account_id,
                    group_number=group_number,
                    status="success",
                    result=result,
                    latency_ms=latency,
                )
                logger.info("AI 已降级到备用模型 %s", backup.model_name)
                return result, None, backup
            except Exception as exc:  # noqa: BLE001
                backup.total_calls += 1
                backup.total_errors += 1
                await db.commit()
                await _log_usage(
                    db,
                    model=backup,
                    account_id=account_id,
                    group_number=group_number,
                    status="error",
                    error=str(exc),
                )
                continue
    return None, last_error or "AI 调用失败", model


async def chat_once(
    db: AsyncSession,
    model: AIModel,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    account_id: int | None = None,
    group_number: int | None = None,
    user_id: int | None = None,
    allow_fallback: bool = True,
    temperature: float | None = None,
    max_tokens: int | None = None,
    allow_cross_provider_fallback: bool | None = None,
) -> tuple[ChatResult | None, str | None, AIModel]:
    """One deadline covers the complete retry/fallback chain, including I/O.

    External task cancellation is never translated into an upstream failure,
    so stopping an account cancels the actual HTTP request as well.
    """
    try:
        async with asyncio.timeout(max(0.01, settings.ai_call_deadline_seconds)):
            return await _chat_once(
                db, model, messages, system=system, account_id=account_id,
                group_number=group_number, allow_fallback=allow_fallback,
                temperature=temperature, max_tokens=max_tokens,
                allow_cross_provider_fallback=allow_cross_provider_fallback,
            )
    except TimeoutError:
        await db.rollback()
        await db.refresh(model)
        return None, "AI 调用超过整次执行期限，已取消", model


async def test_model(db: AsyncSession, model: AIModel) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        client = provider_to_client(model)
        async with asyncio.timeout(max(0.01, settings.ai_call_deadline_seconds)):
            result = await client.chat([{"role": "user", "content": "请只回复：OK"}], system="你是连通性测试助手。")
        latency = int((time.perf_counter() - started) * 1000)
        model.last_checked_at = datetime.now(timezone.utc)
        model.last_check_status = "ok"
        model.last_check_error = None
        model.last_latency_ms = latency
        await db.commit()
        return {
            "ok": True,
            "latency_ms": latency,
            "message": f"连接成功，响应：{(result.content or '').strip()[:80]}",
            "detail": {"model": model.model_name, "tokens": result.total_tokens},
        }
    except Exception as exc:  # noqa: BLE001
        latency = int((time.perf_counter() - started) * 1000)
        model.last_checked_at = datetime.now(timezone.utc)
        model.last_check_status = "error"
        model.last_check_error = str(exc)[:500]
        model.last_latency_ms = latency
        await db.commit()
        return {"ok": False, "latency_ms": latency, "message": f"连接失败：{exc}", "detail": None}


async def get_or_create_conversation(
    db: AsyncSession,
    *,
    account_id: int,
    scope: str,
    group_number: int | None = None,
    user_id: int | None = None,
    system_prompt: str | None = None,
) -> AIConversation:
    key = conversation_scope_key(scope, group_number, user_id)
    query = select(AIConversation).where(AIConversation.account_id == account_id, AIConversation.scope_key == key)
    conversation = await db.scalar(query)
    if conversation:
        if system_prompt and conversation.system_prompt != system_prompt:
            conversation.system_prompt = system_prompt
            await db.commit()
        return conversation
    conversation = AIConversation(
        account_id=account_id,
        scope=scope,
        group_number=group_number,
        user_id=user_id,
        scope_key=key,
        system_prompt=system_prompt,
        last_active_at=datetime.now(timezone.utc),
    )
    try:
        async with db.begin_nested():
            db.add(conversation)
            await db.flush()
        await db.commit()
        await db.refresh(conversation)
    except IntegrityError:
        conversation = await db.scalar(query)
        if conversation is None:
            raise
    return conversation


async def conversation_history(db: AsyncSession, conversation_id: int, limit: int = 10) -> list[dict[str, str]]:
    rows = await db.scalars(
        select(AIMessage)
        .where(AIMessage.conversation_id == conversation_id)
        .order_by(AIMessage.id.desc())
        .limit(limit)
    )
    messages = list(reversed(list(rows)))
    return [{"role": m.role, "content": m.content} for m in messages if m.role in {"user", "assistant"}]


async def append_message(
    db: AsyncSession,
    conversation: AIConversation,
    role: str,
    content: str,
    *,
    tokens: int = 0,
    model_name: str | None = None,
    latency_ms: int | None = None,
) -> AIMessage:
    message = AIMessage(
        conversation_id=conversation.id,
        role=role,
        content=content,
        tokens=tokens,
        model_name=model_name,
        latency_ms=latency_ms,
    )
    db.add(message)
    conversation.message_count += 1
    conversation.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(message)
    return message


async def trim_conversation(db: AsyncSession, conversation_id: int, keep: int) -> None:
    rows = await db.scalars(
        select(AIMessage).where(AIMessage.conversation_id == conversation_id).order_by(AIMessage.id.desc())
    )
    items = list(rows)
    for stale in items[keep:]:
        await db.delete(stale)
    await db.commit()


async def clear_conversation(db: AsyncSession, conversation_id: int) -> int:
    rows = await db.scalars(select(AIMessage).where(AIMessage.conversation_id == conversation_id))
    items = list(rows)
    for item in items:
        await db.delete(item)
    conversation = await db.get(AIConversation, conversation_id)
    if conversation:
        conversation.message_count = 0
    await db.commit()
    return len(items)


def build_system_prompt(group_settings: GroupSettings | None, custom: str | None = None) -> str:
    if custom:
        return custom
    if group_settings and group_settings.ai_prompt:
        return group_settings.ai_prompt
    return DEFAULT_SYSTEM_PROMPT
