"""Track WebSocket ticket consumption.

一次性 WebSocket 票据此前只做短时签名校验，同一张票在 60 秒内可重复握手。
新增消费记录表后，每次握手都会以唯一 jti 抢占一行，第二次使用直接失败。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_ws_tickets"
down_revision = "0014_retention_default_three"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ws_tickets" in inspector.get_table_names():
        return
    op.create_table(
        "ws_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ws_tickets_jti", "ws_tickets", ["jti"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ws_tickets" in inspector.get_table_names():
        indexes = {idx["name"] for idx in inspector.get_indexes("ws_tickets")}
        if "ix_ws_tickets_jti" in indexes:
            op.drop_index("ix_ws_tickets_jti", table_name="ws_tickets")
        op.drop_table("ws_tickets")
