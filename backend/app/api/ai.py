"""AI 模型中心：供应商、模型、连通性测试、对话调试、调用记录。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.db.session import get_db
from app.models import AIMessage, AIModel, AIProvider, AIConversation, AIUsageLog, User
from app.schemas.ai import (
    AIMessageOut,
    ChatRequest,
    ChatResponse,
    ConversationOut,
    ModelCreate,
    ModelOut,
    ModelUpdate,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
    UsageLogOut,
)
from app.schemas.common import MessageOut, Page
from app.services.ai import service as ai_service
from app.services.ai.providers import PROVIDER_PRESETS, build_provider
from app.services.logs import audit

router = APIRouter(prefix="/ai", tags=["AI中心"])


def serialize_provider(provider: AIProvider, model_count: int = 0) -> ProviderOut:
    key = decrypt_secret(provider.api_key_enc)
    return ProviderOut(
        id=provider.id,
        name=provider.name,
        kind=provider.kind,
        base_url=provider.base_url,
        enabled=provider.enabled,
        remark=provider.remark,
        api_key_masked=mask_secret(key),
        has_api_key=bool(key),
        model_count=model_count,
    )


def serialize_model(model: AIModel) -> ModelOut:
    data = ModelOut.model_validate(model)
    data.provider_name = model.provider.name if model.provider else None
    data.provider_kind = model.provider.kind if model.provider else None
    return data


@router.get("/presets")
async def list_presets(_: User = Depends(require("ai:view"))):
    return PROVIDER_PRESETS


# ---------------------------------------------------------------------------
# 供应商
# ---------------------------------------------------------------------------
@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(db: AsyncSession = Depends(get_db), _: User = Depends(require("ai:view"))):
    providers = list(await db.scalars(select(AIProvider).order_by(AIProvider.id)))
    counts = {
        pid: count
        for pid, count in (
            await db.execute(select(AIModel.provider_id, func.count(AIModel.id)).group_by(AIModel.provider_id))
        ).all()
    }
    return [serialize_provider(p, counts.get(p.id, 0)) for p in providers]


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def create_provider(
    payload: ProviderCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require("ai:manage"))
):
    exists = await db.scalar(select(AIProvider).where(AIProvider.name == payload.name))
    if exists:
        raise HTTPException(status_code=409, detail="同名供应商已存在")
    provider = AIProvider(
        name=payload.name,
        kind=payload.kind,
        base_url=payload.base_url.rstrip("/"),
        api_key_enc=encrypt_secret(payload.api_key),
        enabled=payload.enabled,
        remark=payload.remark,
        extra_headers={},
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    await audit(db, user_id=user.id, username=user.username, action="create_ai_provider", target=provider.name)
    return serialize_provider(provider)


@router.put("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: int,
    payload: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("ai:manage")),
):
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")
    data = payload.model_dump(exclude_unset=True)
    api_key = data.pop("api_key", None)
    if api_key is not None:
        provider.api_key_enc = encrypt_secret(api_key) if api_key else None
    for field, value in data.items():
        if field == "base_url" and value:
            value = value.rstrip("/")
        setattr(provider, field, value)
    await db.commit()
    await db.refresh(provider)
    await audit(db, user_id=user.id, username=user.username, action="update_ai_provider", target=provider.name)
    return serialize_provider(provider)


@router.delete("/providers/{provider_id}", response_model=MessageOut)
async def delete_provider(
    provider_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("ai:manage"))
):
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")
    name = provider.name
    await db.delete(provider)
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="delete_ai_provider", target=name)
    return MessageOut(detail=f"供应商 {name} 及其模型已删除")


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: int,
    payload: dict | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("ai:manage")),
):
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")
    model_name = (payload or {}).get("model_name")
    if not model_name:
        model = await db.scalar(select(AIModel).where(AIModel.provider_id == provider.id).limit(1))
        if not model:
            raise HTTPException(status_code=400, detail="该供应商下还没有模型，请先添加模型并指定 Model ID")
        model_name = model.model_name
    try:
        client = build_provider(
            provider.kind,
            base_url=provider.base_url,
            api_key=decrypt_secret(provider.api_key_enc),
            model_name=model_name,
            timeout=30,
            max_tokens=32,
        )
        result = await client.chat([{"role": "user", "content": "只回复 OK"}])
        return {"ok": True, "message": f"连接成功：{(result.content or '').strip()[:50]}", "latency_ms": result.latency_ms}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"连接失败：{exc}"}


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------
@router.get("/models", response_model=list[ModelOut])
async def list_models(db: AsyncSession = Depends(get_db), _: User = Depends(require("ai:view"))):
    models = list(await db.scalars(select(AIModel).order_by(AIModel.priority, AIModel.id)))
    return [serialize_model(m) for m in models]


@router.post("/models", response_model=ModelOut, status_code=201)
async def create_model(
    payload: ModelCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require("ai:manage"))
):
    provider = await db.get(AIProvider, payload.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")
    exists = await db.scalar(
        select(AIModel).where(AIModel.provider_id == payload.provider_id, AIModel.model_name == payload.model_name)
    )
    if exists:
        raise HTTPException(status_code=409, detail="该供应商下已存在同名模型")
    model = AIModel(**payload.model_dump())
    db.add(model)
    await db.commit()
    await db.refresh(model)
    if payload.is_default:
        await _set_default(db, model.id)
        await db.refresh(model)
    await audit(db, user_id=user.id, username=user.username, action="create_ai_model", target=model.model_name)
    return serialize_model(model)


async def _set_default(db: AsyncSession, model_id: int) -> None:
    rows = await db.scalars(select(AIModel))
    for item in rows:
        item.is_default = item.id == model_id


@router.put("/models/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: int, payload: ModelUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(require("ai:manage"))
):
    model = await db.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if field == "is_default" and value:
            await _set_default(db, model.id)
            continue
        setattr(model, field, value)
    await db.commit()
    await db.refresh(model)
    await audit(db, user_id=user.id, username=user.username, action="update_ai_model", target=model.model_name)
    return serialize_model(model)


@router.delete("/models/{model_id}", response_model=MessageOut)
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("ai:manage"))):
    model = await db.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    name = model.model_name
    await db.delete(model)
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="delete_ai_model", target=name)
    return MessageOut(detail=f"模型 {name} 已删除")


@router.post("/models/{model_id}/test")
async def test_model(model_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("ai:manage"))):
    model = await db.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    result = await ai_service.test_model(db, model)
    return result


@router.post("/models/{model_id}/default", response_model=MessageOut)
async def set_default_model(
    model_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("ai:manage"))
):
    model = await db.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    await _set_default(db, model.id)
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="set_default_model", target=model.model_name)
    return MessageOut(detail=f"已将 {model.model_name} 设为默认模型")


# ---------------------------------------------------------------------------
# 对话调试
# ---------------------------------------------------------------------------
@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: AsyncSession = Depends(get_db), _: User = Depends(require("ai:view"))):
    model = await ai_service.resolve_model(
        db, model_id=payload.model_id, account_id=payload.account_id, group_number=payload.group_number
    )
    if not model:
        raise HTTPException(status_code=400, detail="没有可用的 AI 模型，请先在 AI 模型中心添加并测试")
    messages = payload.messages or []
    if not messages:
        raise HTTPException(status_code=400, detail="请提供 messages")
    result, error, used = await ai_service.chat_once(
        db, model, messages, system=payload.system_prompt, account_id=payload.account_id, group_number=payload.group_number
    )
    if not result:
        return ChatResponse(ok=False, content="", error=error, model_name=used.model_name)
    return ChatResponse(
        ok=True,
        content=result.content,
        model_name=used.model_name,
        usage={"prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens},
        latency_ms=result.latency_ms,
        fallback_used=used.id != model.id,
    )


@router.get("/conversations", response_model=Page[ConversationOut])
async def list_conversations(
    page: int = 1,
    page_size: int = 20,
    account_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("ai:view")),
):
    query = select(AIConversation)
    if account_id:
        query = query.where(AIConversation.account_id == account_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(
        query.order_by(AIConversation.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return Page(
        items=[ConversationOut.model_validate(c) for c in rows], total=total, page=page, page_size=page_size
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[AIMessageOut])
async def conversation_messages(
    conversation_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("ai:view"))
):
    conversation = await db.get(AIConversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    rows = await db.scalars(
        select(AIMessage).where(AIMessage.conversation_id == conversation_id).order_by(AIMessage.id)
    )
    return [AIMessageOut.model_validate(m) for m in rows]


@router.delete("/conversations/{conversation_id}", response_model=MessageOut)
async def delete_conversation(
    conversation_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("ai:manage"))
):
    conversation = await db.get(AIConversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.delete(conversation)
    await db.commit()
    return MessageOut(detail="会话已删除")


@router.get("/usage", response_model=Page[UsageLogOut])
async def usage_logs(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    model_id: int | None = None,
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("ai:view")),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = select(AIUsageLog).where(AIUsageLog.created_at >= since)
    if status:
        query = query.where(AIUsageLog.status == status)
    if model_id:
        query = query.where(AIUsageLog.model_id == model_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(query.order_by(AIUsageLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[UsageLogOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/usage/summary")
async def usage_summary(db: AsyncSession = Depends(get_db), _: User = Depends(require("ai:view"))):
    since = datetime.now(timezone.utc) - timedelta(days=7)
    total = await db.scalar(select(func.count()).select_from(AIUsageLog).where(AIUsageLog.created_at >= since)) or 0
    errors = await db.scalar(
        select(func.count()).select_from(AIUsageLog).where(AIUsageLog.created_at >= since, AIUsageLog.status == "error")
    ) or 0
    tokens = await db.scalar(
        select(func.sum(AIUsageLog.prompt_tokens + AIUsageLog.completion_tokens)).where(AIUsageLog.created_at >= since)
    ) or 0
    avg_latency = await db.scalar(
        select(func.avg(AIUsageLog.latency_ms)).where(AIUsageLog.created_at >= since, AIUsageLog.status == "success")
    ) or 0
    return {
        "calls_7d": total,
        "errors_7d": errors,
        "error_rate": round(errors / total * 100, 1) if total else 0.0,
        "tokens_7d": int(tokens),
        "avg_latency_ms": int(avg_latency),
    }
