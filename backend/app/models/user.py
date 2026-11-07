"""后台用户、角色、审计日志。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(190), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64))
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_ip: Mapped[str | None] = mapped_column(String(64))
    totp_secret_enc: Mapped[str | None] = mapped_column(Text())
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    totp_last_counter: Mapped[int | None] = mapped_column(Integer)
    totp_challenge_nonce: Mapped[str | None] = mapped_column(String(64))

    role: Mapped[Role | None] = relationship(back_populates="users", lazy="joined")

    @property
    def is_locked(self) -> bool:
        if not self.locked_until:
            return False
        locked = self.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=utcnow().tzinfo)
        return locked > utcnow()

    @property
    def permission_set(self) -> set[str]:
        perms = set(self.role.permissions or []) if self.role else set()
        if self.role and self.role.name == "super_admin":
            perms.add("*")
        return perms


class AuthSession(Base, TimestampMixin):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    target: Mapped[str | None] = mapped_column(String(190))
    detail: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
