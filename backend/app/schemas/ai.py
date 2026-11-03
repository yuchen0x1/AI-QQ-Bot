"""AI 中心 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

ProviderKind = Literal["openai", "deepseek", "qwen", "moonshot", "gemini", "anthropic", "ollama", "custom"]


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=96)
    kind: ProviderKind = "openai"
    base_url: str = Field(min_length=4, max_length=255)
    api_key: str | None = None
    enabled: bool = True
    remark: str | None = None


class ProviderUpdate(BaseModel):
    name: str | None = None
    kind: ProviderKind | None = None
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    remark: str | None = None


class ProviderOut(ORMModel):
    id: int
    name: str
    kind: str
    base_url: str
    enabled: bool
    remark: str | None = None
    api_key_masked: str = ""
    has_api_key: bool = False
    model_count: int = 0


class ModelCreate(BaseModel):
    provider_id: int
    model_name: str = Field(min_length=1, max_length=128)
    display_name: str | None = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=16, le=200000)
    timeout_seconds: int = Field(default=60, ge=5, le=600)
    retries: int = Field(default=1, ge=0, le=5)
    priority: int = Field(default=100, ge=1, le=999)
    is_default: bool = False
    is_fallback: bool = False
    enabled: bool = True


class ModelUpdate(BaseModel):
    display_name: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=16, le=200000)
    timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    retries: int | None = Field(default=None, ge=0, le=5)
    priority: int | None = None
    is_default: bool | None = None
    is_fallback: bool | None = None
    enabled: bool | None = None


class ModelOut(ORMModel):
    id: int
    provider_id: int
    model_name: str
    display_name: str | None = None
    temperature: float
    max_tokens: int
    timeout_seconds: int
    retries: int
    priority: int
    is_default: bool
    is_fallback: bool
    enabled: bool
    total_calls: int
    total_errors: int
    total_tokens: int
    last_checked_at: datetime | None = None
    last_check_status: str | None = None
    last_check_error: str | None = None
    last_latency_ms: int | None = None
    provider_name: str | None = None
    provider_kind: str | None = None


class ConversationOut(ORMModel):
    id: int
    account_id: int
    scope: str
    group_number: int | None = None
    user_id: int | None = None
    model_id: int | None = None
    system_prompt: str | None = None
    message_count: int
    last_active_at: datetime | None = None


class AIMessageOut(ORMModel):
    id: int
    role: str
    content: str
    tokens: int
    model_name: str | None = None
    latency_ms: int | None = None
    created_at: datetime


class UsageLogOut(ORMModel):
    id: int
    model_id: int | None = None
    model_name: str | None = None
    account_id: int | None = None
    group_number: int | None = None
    status: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    error: str | None = None
    created_at: datetime


class ChatRequest(BaseModel):
    model_id: int | None = None
    messages: list[dict[str, str]] = Field(default_factory=list)
    system_prompt: str | None = None
    account_id: int | None = None
    group_number: int | None = None


class ChatResponse(BaseModel):
    ok: bool
    content: str
    model_name: str | None = None
    usage: dict[str, int] | None = None
    latency_ms: int | None = None
    fallback_used: bool = False
    error: str | None = None
