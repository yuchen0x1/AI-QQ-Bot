"""GitHub 仓库、Release、事件、推送规则、推送记录。"""

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


class GithubRepository(Base, TimestampMixin):
    __tablename__ = "github_repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(24), default="github", nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(190), nullable=False)
    full_name: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    html_url: Mapped[str] = mapped_column(String(400), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str | None] = mapped_column(String(96))
    language: Mapped[str | None] = mapped_column(String(64))
    stars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    forks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_enc: Mapped[str | None] = mapped_column(Text)
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text)
    monitor_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    notify_prerelease: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_status: Mapped[str | None] = mapped_column(String(32))
    last_check_error: Mapped[str | None] = mapped_column(Text)
    last_release_tag: Mapped[str | None] = mapped_column(String(128))
    last_release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    releases: Mapped[list["GithubRelease"]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    rules: Mapped[list["PushRule"]] = relationship(back_populates="repository", cascade="all, delete-orphan")


class GithubRelease(Base, TimestampMixin):
    __tablename__ = "github_releases"
    __table_args__ = (UniqueConstraint("repository_id", "tag_name", name="uq_release_repo_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("github_repositories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tag_name: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    html_url: Mapped[str | None] = mapped_column(String(400))
    prerelease: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    draft: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assets: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    summary_status: Mapped[str | None] = mapped_column(String(32))
    notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    repository: Mapped[GithubRepository] = relationship(back_populates="releases")


class GithubEvent(Base, TimestampMixin):
    __tablename__ = "github_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int | None] = mapped_column(
        ForeignKey("github_repositories.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str | None] = mapped_column(String(64))
    dedupe_key: Mapped[str] = mapped_column(String(400), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="poll", nullable=False)  # poll/webhook
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("github_releases.id", ondelete="SET NULL"))
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PushRule(Base, TimestampMixin):
    __tablename__ = "push_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("github_repositories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    qq_group: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    only_stable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_changelog: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_downloads: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ai_summary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mention_user_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    template: Mapped[str | None] = mapped_column(Text)
    last_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_pushed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    repository: Mapped[GithubRepository] = relationship(back_populates="rules")


class PushRecord(Base, TimestampMixin):
    __tablename__ = "push_records"
    __table_args__ = (UniqueConstraint("rule_id", "release_id", name="uq_push_rule_release"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("github_repositories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rule_id: Mapped[int] = mapped_column(ForeignKey("push_rules.id", ondelete="CASCADE"), index=True, nullable=False)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("github_releases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    release_tag: Mapped[str | None] = mapped_column(String(128))
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    qq_group: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)  # pending/success/failed
    error: Mapped[str | None] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
