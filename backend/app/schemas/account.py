"""账号 / 群聊 / 消息 / 命令 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel

# QQ 官方机器人默认只订阅群聊 @ / 单聊 / 好友与群变动事件（GROUP_AND_C2C_EVENT）。
DEFAULT_OFFICIAL_INTENTS = 1 << 25
OFFICIAL_PROTOCOL = "qq_official"


class AccountBase(BaseModel):
    name: str = Field(min_length=1, max_length=96)
    qq_number: int | None = None
    nickname: str | None = None
    protocol: Literal["onebot11", "qq_official", "mock"] = "qq_official"
    connection_mode: Literal["ws_client", "ws_server", "http", "official_ws", "official_webhook"] = "official_ws"
    api_base: str | None = None
    ws_url: str | None = None
    access_token: str | None = None
    # ---- QQ 官方机器人开放平台（bot.qq.com）----
    app_id: str | None = Field(default=None, max_length=64)
    app_secret: str | None = None
    official_sandbox: bool = False
    official_intents: int = Field(default=DEFAULT_OFFICIAL_INTENTS, ge=0, le=(1 << 31) - 1)
    official_allow_proactive: bool = True
    official_api_base: str | None = None
    enabled: bool = True
    auto_start: bool = False
    auto_reconnect: bool = True
    reconnect_base_seconds: int = Field(default=5, ge=1, le=600)
    reconnect_max_seconds: int = Field(default=300, ge=5, le=3600)
    remark: str | None = None

    @field_validator("api_base", "ws_url", "app_id", "official_api_base")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: str | None = None
    qq_number: int | None = None
    nickname: str | None = None
    protocol: Literal["onebot11", "qq_official", "mock"] | None = None
    connection_mode: Literal["ws_client", "ws_server", "http", "official_ws", "official_webhook"] | None = None
    api_base: str | None = None
    ws_url: str | None = None
    access_token: str | None = None
    app_id: str | None = Field(default=None, max_length=64)
    app_secret: str | None = None
    official_sandbox: bool | None = None
    official_intents: int | None = Field(default=None, ge=0, le=(1 << 31) - 1)
    official_allow_proactive: bool | None = None
    official_api_base: str | None = None
    enabled: bool | None = None
    auto_start: bool | None = None
    auto_reconnect: bool | None = None
    reconnect_base_seconds: int | None = Field(default=None, ge=1, le=600)
    reconnect_max_seconds: int | None = Field(default=None, ge=5, le=3600)
    remark: str | None = None


class ConnectionOut(ORMModel):
    status: str
    last_error: str | None = None
    connected_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_disconnect_at: datetime | None = None
    reconnect_attempts: int = 0
    sent_messages: int = 0
    received_messages: int = 0


class AccountOut(ORMModel):
    id: int
    account_id: str
    name: str
    qq_number: int | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    protocol: str
    connection_mode: str
    api_base: str | None = None
    ws_url: str | None = None
    self_id: int | None = None
    app_id: str | None = None
    bot_openid: str | None = None
    webhook_url: str | None = None
    has_token: bool = False
    has_secret: bool = False
    official_sandbox: bool = False
    official_intents: int = DEFAULT_OFFICIAL_INTENTS
    official_allow_proactive: bool = True
    official_api_base: str | None = None
    enabled: bool
    auto_start: bool
    auto_reconnect: bool
    remark: str | None = None
    created_at: datetime
    connection: ConnectionOut | None = None
    online_seconds: int = 0
    group_count: int = 0
    capabilities: dict[str, bool] = {}
    runtime_state: str = "stopped"


class AccountStatsOut(BaseModel):
    total: int
    online: int
    offline: int
    error: int
    today_sent: int
    today_received: int
    last_connected_at: datetime | None = None
    last_heartbeat_at: datetime | None = None


class GroupSettingsOut(ORMModel):
    ai_enabled: bool
    ai_model_id: int | None = None
    ai_prompt: str | None = None
    require_at_for_ai: bool
    ai_context_limit: int
    command_prefix: str
    welcome_enabled: bool
    welcome_template: str | None = None
    member_change_notify: bool
    moderation_mode: str
    banned_words: list[str] = []
    rate_limit_per_minute: int
    max_repeat_chars: int
    auto_warn_threshold: int
    auto_mute_seconds: int
    auto_kick: bool
    announcement: str | None = None


class GroupSettingsUpdate(BaseModel):
    ai_enabled: bool | None = None
    ai_model_id: int | None = None
    ai_prompt: str | None = None
    require_at_for_ai: bool | None = None
    ai_context_limit: int | None = Field(default=None, ge=1, le=50)
    command_prefix: str | None = Field(default=None, max_length=8)
    welcome_enabled: bool | None = None
    welcome_template: str | None = None
    member_change_notify: bool | None = None
    moderation_mode: Literal["off", "normal", "strict"] | None = None
    banned_words: list[str] | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=0, le=500)
    max_repeat_chars: int | None = None
    auto_warn_threshold: int | None = Field(default=None, ge=1, le=20)
    auto_mute_seconds: int | None = Field(default=None, ge=0, le=2592000)
    auto_kick: bool | None = None
    announcement: str | None = None


class GroupOut(ORMModel):
    id: int
    account_id: int
    group_number: int
    name: str | None = None
    member_count: int
    max_member_count: int
    owner_id: int | None = None
    last_synced_at: datetime | None = None
    settings: GroupSettingsOut | None = None
    account_name: str | None = None


class GroupMemberOut(ORMModel):
    id: int
    user_id: int
    nickname: str | None = None
    card: str | None = None
    role: str
    message_count: int
    warn_count: int
    is_blacklisted: bool
    is_whitelisted: bool
    last_active_at: datetime | None = None
    muted_until: datetime | None = None


class BotRequestOut(ORMModel):
    id: int
    account_id: int
    account_name: str | None = None
    request_type: Literal["group", "friend"]
    sub_type: str
    flag: str
    user_id: int
    group_id: int | None = None
    comment: str | None = None
    status: Literal["pending", "approved", "rejected"]
    handled_by: str | None = None
    handled_at: datetime | None = None
    decision_reason: str | None = None
    created_at: datetime


class BotRequestDecision(BaseModel):
    approve: bool
    reason: str = Field(default="", max_length=500)
    remark: str = Field(default="", max_length=100)


class GroupActionRequest(BaseModel):
    action: Literal[
        "mute",
        "unmute",
        "ban_all",
        "unban_all",
        "kick",
        "set_card",
        "set_group_name",
        "set_announcement",
        "recall",
        "set_admin",
        "unset_admin",
    ]
    user_id: int | None = None
    duration_seconds: int | None = Field(default=None, ge=0, le=2592000)
    enable: bool | None = None
    value: str | None = None
    message_id: int | None = None


class GroupActionOut(BaseModel):
    ok: bool
    action: str
    message: str
    provider_response: dict[str, Any] | None = None


class MessageOut(ORMModel):
    id: int
    account_id: int
    group_id: int | None = None
    qq_group: int | None = None
    message_id: int | None = None
    direction: str
    message_type: str
    sender_id: int | None = None
    sender_name: str | None = None
    content: str | None = None
    blocked: bool = False
    block_reason: str | None = None
    created_at: datetime


class SendMessageRequest(BaseModel):
    account_id: int
    qq_group: int | None = None
    user_id: int | None = None
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("qq_group", "user_id")
    @classmethod
    def _positive_target(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("目标 ID 必须为正整数")
        return value


class CommandOut(ORMModel):
    id: int
    name: str
    aliases: list[str] = []
    description: str | None = None
    usage: str | None = None
    min_role: str
    enabled: bool
    builtin: bool
    plugin_key: str | None = None


class CommandUpdate(BaseModel):
    description: str | None = None
    min_role: Literal["member", "admin", "owner", "super_admin"] | None = None
    enabled: bool | None = None
    aliases: list[str] | None = None
