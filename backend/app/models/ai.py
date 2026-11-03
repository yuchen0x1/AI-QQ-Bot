"""AI 服务商、模型、会话、消息。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow

PROVIDER_KINDS = ("openai", "deepseek", "qwen", "moonshot", "gemini", "anthropic", "ollama", "custom")


class AIProvider(Base, TimestampMixin):
    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="openai", nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_enc: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    extra_headers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    remark: Mapped[str | None] = mapped_column(String(255))

    models: Mapped[list["AIModel"]] = relationship(back_populates="provider", cascade="all, delete-orphan")


class AIModel(Base, TimestampMixin):
    __tablename__ = "ai_models"
    __table_args__ = (UniqueConstraint("provider_id", "model_name", name="uq_model_provider_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128))
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    total_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_status: Mapped[str | None] = mapped_column(String(32))
    last_check_error: Mapped[str | None] = mapped_column(Text)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer)

    provider: Mapped[AIProvider] = relationship(back_populates="models", lazy="joined")


class AIConversation(Base, TimestampMixin):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        UniqueConstraint("account_id", "scope", "group_number", "user_id", name="uq_conversation_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="group", nullable=False)  # group/private
    group_number: Mapped[int | None] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(Integer)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("ai_models.id", ondelete="SET NULL"))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list["AIMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AIMessage.id"
    )


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")


class AIUsageLog(Base):
    """模型调用记录（用于 Token 统计、错误率）。"""

    __tablename__ = "ai_usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("ai_models.id", ondelete="SET NULL"), index=True)
    model_name: Mapped[str | None] = mapped_column(String(128))
    account_id: Mapped[int | None] = mapped_column(Integer)
    group_number: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
