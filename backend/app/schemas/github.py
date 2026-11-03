"""GitHub 监控与推送 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel


class RepoCreate(BaseModel):
    provider: str = "github"
    url: str | None = None
    owner: str | None = None
    name: str | None = None
    token: str | None = None
    webhook_secret: str | None = None
    monitor_enabled: bool = True
    poll_interval_seconds: int = Field(default=900, ge=60, le=86400)
    notify_prerelease: bool = False

    @model_validator(mode="after")
    def _check(self) -> "RepoCreate":
        if not self.url and not (self.owner and self.name):
            raise ValueError("必须提供仓库地址，或同时提供 owner 与 name")
        return self


class RepoUpdate(BaseModel):
    token: str | None = None
    webhook_secret: str | None = None
    monitor_enabled: bool | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    notify_prerelease: bool | None = None


class RepoOut(ORMModel):
    id: int
    provider: str = "github"
    owner: str
    name: str
    full_name: str
    html_url: str
    description: str | None = None
    default_branch: str | None = None
    language: str | None = None
    stars: int
    forks: int
    monitor_enabled: bool
    poll_interval_seconds: int
    notify_prerelease: bool
    last_checked_at: datetime | None = None
    last_check_status: str | None = None
    last_check_error: str | None = None
    last_release_tag: str | None = None
    last_release_at: datetime | None = None
    last_webhook_at: datetime | None = None
    rule_count: int = 0
    release_count: int = 0
    has_token: bool = False
    has_webhook_secret: bool = False


class ReleaseOut(ORMModel):
    id: int
    repository_id: int
    tag_name: str
    name: str | None = None
    body: str | None = None
    html_url: str | None = None
    prerelease: bool
    draft: bool
    assets: list[dict[str, Any]] = []
    published_at: datetime | None = None
    detected_at: datetime
    summary: str | None = None
    summary_status: str | None = None
    notified: bool


class PushRuleCreate(BaseModel):
    repository_id: int
    account_id: int
    qq_group: int
    enabled: bool = True
    only_stable: bool = True
    include_changelog: bool = True
    include_downloads: bool = True
    ai_summary: bool = True
    mention_user_ids: list[int] = []
    template: str | None = None


class PushRuleUpdate(BaseModel):
    qq_group: int | None = None
    account_id: int | None = None
    enabled: bool | None = None
    only_stable: bool | None = None
    include_changelog: bool | None = None
    include_downloads: bool | None = None
    ai_summary: bool | None = None
    mention_user_ids: list[int] | None = None
    template: str | None = None


class PushRuleOut(ORMModel):
    id: int
    repository_id: int
    account_id: int
    qq_group: int
    enabled: bool
    only_stable: bool
    include_changelog: bool
    include_downloads: bool
    ai_summary: bool
    mention_user_ids: list[int] = []
    template: str | None = None
    last_pushed_at: datetime | None = None
    total_pushed: int
    repo_full_name: str | None = None
    account_name: str | None = None


class PushRecordOut(ORMModel):
    id: int
    repository_id: int
    rule_id: int
    release_id: int
    release_tag: str | None = None
    account_id: int
    qq_group: int
    content: str | None = None
    status: str
    error: str | None = None
    retries: int
    message_id: int | None = None
    sent_at: datetime | None = None
    created_at: datetime
    repo_full_name: str | None = None


class CheckResult(BaseModel):
    repository_id: int
    ok: bool
    new_releases: int = 0
    pushed: int = 0
    skipped: int = 0
    message: str = ""
    releases: list[str] = []
