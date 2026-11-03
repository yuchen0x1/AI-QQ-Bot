"""待处理的 QQ 好友与群聊申请事件。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BotRequest(Base, TimestampMixin):
    __tablename__ = "bot_requests"
    __table_args__ = (
        UniqueConstraint("account_id", "request_type", "flag", name="uq_bot_request_account_type_flag"),
        Index("ix_bot_request_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    request_type: Mapped[str] = mapped_column(String(16), nullable=False)  # group/friend
    sub_type: Mapped[str] = mapped_column(String(24), nullable=False)  # add/invite
    flag: Mapped[str] = mapped_column(String(256), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int | None] = mapped_column(BigInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)  # pending/approved/rejected
    raw: Mapped[dict | None] = mapped_column(JSON)
    handled_by: Mapped[str | None] = mapped_column(String(64))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
