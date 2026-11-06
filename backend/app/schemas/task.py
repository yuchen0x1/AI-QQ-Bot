"""任务 / 插件 / 日志 / 系统 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel

TASK_TYPES = Literal[
    "github_check",
    "github_check_all",
    "group_announcement",
    "group_message",
    "online_check",
    "ai_summary",
    "health_check",
    "backup",
    "push_retry",
    "clean_expired_data",
]


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=190)
    task_type: TASK_TYPES
    schedule_kind: Literal["interval", "cron"] = "interval"
    interval_seconds: int | None = Field(default=None, ge=30, le=2592000)
    cron_expr: str | None = None
    payload: dict[str, Any] = {}
    enabled: bool = True
    max_retries: int = Field(default=2, ge=0, le=5)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)

    @model_validator(mode="after")
    def _check(self) -> "TaskCreate":
        if self.schedule_kind == "interval" and not self.interval_seconds:
            raise ValueError("interval 模式必须填写执行间隔（秒）")
        if self.schedule_kind == "cron" and not self.cron_expr:
            raise ValueError("cron 模式必须填写 cron 表达式")
        return self


class TaskUpdate(BaseModel):
    name: str | None = None
    schedule_kind: Literal["interval", "cron"] | None = None
    interval_seconds: int | None = Field(default=None, ge=30, le=2592000)
    cron_expr: str | None = None
    payload: dict[str, Any] | None = None
    enabled: bool | None = None
    max_retries: int | None = Field(default=None, ge=0, le=5)
    timeout_seconds: int | None = Field(default=None, ge=10, le=3600)


class TaskOut(ORMModel):
    id: int
    name: str
    task_type: str
    schedule_kind: str
    interval_seconds: int | None = None
    cron_expr: str | None = None
    payload: dict[str, Any] = {}
    enabled: bool
    max_retries: int
    timeout_seconds: int
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    next_run_at: datetime | None = None
    total_runs: int
    total_failures: int
    created_by: str | None = None


class TaskRecordOut(ORMModel):
    id: int
    task_id: int | None = None
    task_name: str | None = None
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    retries: int


class PluginOut(ORMModel):
    id: int
    plugin_id: str
    name: str
    version: str
    author: str | None = None
    description: str | None = None
    permissions: list[str] = []
    config: dict[str, Any] = {}
    enabled: bool
    builtin: bool
    path: str | None = None
    load_status: str | None = None
    load_error: str | None = None
    commands: list[str] = []
    binding_count: int = 0


class PluginUpdate(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class PluginBindingCreate(BaseModel):
    scope: Literal["account", "group"]
    target_id: str
    enabled: bool = True


class LogOut(ORMModel):
    id: int
    level: str
    category: str
    account_id: int | None = None
    message: str
    context: dict[str, Any] | None = None
    created_at: datetime


class SettingOut(ORMModel):
    key: str
    value: Any
    description: str | None = None
    is_secret: bool


class SettingUpdate(BaseModel):
    value: Any


class SystemStats(BaseModel):
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    load_average: list[float]
    python_version: str
    uptime_seconds: int
    db_ok: bool
    redis_ok: bool
    redis_enabled: bool
    scheduler_running: bool
    scheduler_jobs: int
    process_uptime_seconds: int


class DashboardOut(BaseModel):
    accounts_total: int
    accounts_online: int
    accounts_offline: int
    accounts_error: int
    messages_today: int
    messages_sent_today: int
    ai_calls_today: int
    repos_total: int
    releases_today: int
    pushes_today: int
    failed_tasks: int
    groups_total: int
    push_success_rate: float
    message_trend: list[dict[str, Any]]
    ai_trend: list[dict[str, Any]]
    account_status: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]
