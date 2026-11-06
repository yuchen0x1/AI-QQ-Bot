"""Add durable OneBot request review records.

Revision ID: 0002_bot_requests
Revises: 0001_initial
Create Date: 2026-11-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_bot_requests"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_TABLE = "bot_requests"


def upgrade() -> None:
    bind = op.get_bind()
    # 兼容由旧版 create_all 建库、但未记录 alembic_version 的库在人工 stamp 后继续升级。
    if _TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("request_type", sa.String(length=16), nullable=False),
        sa.Column("sub_type", sa.String(length=24), nullable=False),
        sa.Column("flag", sa.String(length=256), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("handled_by", sa.String(length=64), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "request_type", "flag", name="uq_bot_request_account_type_flag"),
    )
    op.create_index("ix_bot_request_status_created", _TABLE, ["status", "created_at"], unique=False)
    op.create_index(op.f("ix_bot_requests_account_id"), _TABLE, ["account_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return
    op.drop_index(op.f("ix_bot_requests_account_id"), table_name=_TABLE)
    op.drop_index("ix_bot_request_status_created", table_name=_TABLE)
    op.drop_table(_TABLE)
