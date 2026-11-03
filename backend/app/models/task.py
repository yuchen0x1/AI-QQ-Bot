"""定时任务、任务执行记录、插件、插件绑定、命令、系统日志、系统配置。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
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


class ScheduledTask(Base, TimestampMixin):
    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(190), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_kind: Mapped[str] = mapped_column(String(16), default="interval", nullable=False)  # interval/cron
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    cron_expr: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64))
    # 可选 Redis 队列执行；默认仍由 APScheduler 直接调用保持兼容。
    queue_name: Mapped[str | None] = mapped_column(String(96))
    job_key: Mapped[str | None] = mapped_column(String(190), unique=True, index=True)


class TaskRecord(Base):
    __tablename__ = "task_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), index=True)
    task_name: Mapped[str | None] = mapped_column(String(190))
    trigger: Mapped[str] = mapped_column(String(16), default="schedule", nullable=False)  # schedule/manual
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)  # running/success/failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Plugin(Base, TimestampMixin):
    __tablename__ = "plugins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plugin_id: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(190), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    author: Mapped[str | None] = mapped_column(String(96))
    description: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    path: Mapped[str | None] = mapped_column(String(400))
    load_status: Mapped[str | None] = mapped_column(String(32))
    load_error: Mapped[str | None] = mapped_column(Text)
    commands: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    bindings: Mapped[list["PluginBinding"]] = relationship(back_populates="plugin", cascade="all, delete-orphan")


class PluginBinding(Base, TimestampMixin):
    __tablename__ = "plugin_bindings"
    __table_args__ = (UniqueConstraint("plugin_id", "scope", "target_id", name="uq_plugin_binding"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plugin_id: Mapped[int] = mapped_column(ForeignKey("plugins.id", ondelete="CASCADE"), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)  # account/group
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    plugin: Mapped[Plugin] = relationship(back_populates="bindings")


class BotCommand(Base, TimestampMixin):
    __tablename__ = "commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    usage: Mapped[str | None] = mapped_column(String(255))
    handler: Mapped[str] = mapped_column(String(96), nullable=False)
    plugin_key: Mapped[str | None] = mapped_column(String(96))
    min_role: Mapped[str] = mapped_column(String(24), default="member", nullable=False)  # member/admin/owner/super_admin
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    builtin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="system", index=True, nullable=False)
    account_id: Mapped[int | None] = mapped_column(Integer, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)


class SystemSetting(Base, TimestampMixin):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class LoginAttempt(Base):
    """登录失败限流记录（按用户名 + IP）。"""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
