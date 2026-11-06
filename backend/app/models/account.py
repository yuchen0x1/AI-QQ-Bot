"""QQ 账号、连接状态、群聊、群成员、群配置、消息。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow

PROTOCOLS = ("onebot11", "qq_official", "mock")
CONNECTION_MODES = ("ws_client", "ws_server", "http", "official_ws", "official_webhook")


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    qq_number: Mapped[int | None] = mapped_column(BigInteger, index=True)
    nickname: Mapped[str | None] = mapped_column(String(96))
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    protocol: Mapped[str] = mapped_column(String(32), default="onebot11", nullable=False)
    connection_mode: Mapped[str] = mapped_column(String(32), default="ws_client", nullable=False)
    api_base: Mapped[str | None] = mapped_column(String(255))
    ws_url: Mapped[str | None] = mapped_column(String(255))
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    # QQ 官方机器人开放平台（bot.qq.com）凭据。AppID 非敏感，AppSecret 必须加密存储。
    app_id: Mapped[str | None] = mapped_column(String(64), index=True)
    app_secret_enc: Mapped[str | None] = mapped_column(Text)
    bot_openid: Mapped[str | None] = mapped_column(String(190))
    self_id: Mapped[int | None] = mapped_column(BigInteger)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_start: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_reconnect: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reconnect_base_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    reconnect_max_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    features: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    remark: Mapped[str | None] = mapped_column(String(255))

    connection: Mapped["AccountConnection | None"] = relationship(
        back_populates="account", uselist=False, cascade="all, delete-orphan", lazy="joined"
    )
    groups: Mapped[list["Group"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class AccountConnection(Base, TimestampMixin):
    __tablename__ = "account_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="offline", nullable=False)  # offline/connecting/online/error
    last_error: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_disconnect_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 跨进程运行租约：过期后允许其它 worker 接管，避免同一账号重复连接。
    lease_owner: Mapped[str | None] = mapped_column(String(96), index=True)
    lease_id: Mapped[str | None] = mapped_column(String(96), unique=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reconnect_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_messages: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    received_messages: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    account: Mapped[Account] = relationship(back_populates="connection")


class Group(Base, TimestampMixin):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("account_id", "group_number", name="uq_group_account_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    group_number: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(190))
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    owner_id: Mapped[int | None] = mapped_column(BigInteger)
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped[Account] = relationship(back_populates="groups")
    settings: Mapped["GroupSettings | None"] = relationship(
        back_populates="group", uselist=False, cascade="all, delete-orphan", lazy="joined"
    )
    members: Mapped[list["GroupMember"]] = relationship(back_populates="group", cascade="all, delete-orphan")


class GroupSettings(Base, TimestampMixin):
    __tablename__ = "group_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), unique=True, nullable=False)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ai_model_id: Mapped[int | None] = mapped_column(ForeignKey("ai_models.id", ondelete="SET NULL"))
    ai_prompt: Mapped[str | None] = mapped_column(Text)
    require_at_for_ai: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ai_context_limit: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    command_prefix: Mapped[str] = mapped_column(String(8), default="/", nullable=False)
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    welcome_template: Mapped[str | None] = mapped_column(Text)
    member_change_notify: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    moderation_mode: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)  # off/normal/strict
    banned_words: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    max_repeat_chars: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    auto_warn_threshold: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    auto_mute_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    auto_kick: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    announcement: Mapped[str | None] = mapped_column(Text)

    group: Mapped[Group] = relationship(back_populates="settings")


class GroupMember(Base, TimestampMixin):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_member_group_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(96))
    card: Mapped[str | None] = mapped_column(String(96))
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)  # owner/admin/member
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_whitelisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    group: Mapped[Group] = relationship(back_populates="members")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), index=True)
    qq_group: Mapped[int | None] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(String(8), default="in", nullable=False)  # in/out
    message_type: Mapped[str] = mapped_column(String(16), default="group", nullable=False)
    sender_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    sender_name: Mapped[str | None] = mapped_column(String(96))
    content: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSON)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    block_reason: Mapped[str | None] = mapped_column(String(190))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)


class QQOfficialIdentity(Base, TimestampMixin):
    """QQ 官方机器人 OpenID → 平台内部稳定整数 ID 映射。

    官方平台只提供字符串 OpenID（group_openid / user_openid / member_openid），
    而本平台历史数据模型统一使用整数 QQ 号 / 群号。这张表负责把两者双向映射，
    使 BotEngine、群管理、AI 会话、消息统计等上层逻辑无需感知 OpenID。

    kind:
      group  = 群 OpenID（发送群消息使用）
      user   = 单聊用户 OpenID（发送私聊消息使用）
      member = 群成员 OpenID（群内身份，和 user 不互通）
    scope:  member 所属群的 OpenID，用于按群查询成员；其它 kind 为空字符串。
    """

    __tablename__ = "qq_official_identities"
    __table_args__ = (
        UniqueConstraint("account_id", "kind", "scope", "openid", name="uq_qq_identity_account_kind_openid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(190), default="", server_default="", nullable=False)
    openid: Mapped[str] = mapped_column(String(190), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(190))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
