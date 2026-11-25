"""Durable runtime ownership, queue receipts and QQ input recovery."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_runtime_recovery"
down_revision = "0017_ai_scope_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "inbox_id" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("messages")}:
        op.add_column("messages", sa.Column("inbox_id", sa.Integer(), nullable=True))
        op.create_index("ix_messages_inbox_id", "messages", ["inbox_id"], unique=True)
    if "queue_job_id" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("task_records")}:
        op.add_column("task_records", sa.Column("queue_job_id", sa.String(64), nullable=True))
        op.create_index("ix_task_records_queue_job_id", "task_records", ["queue_job_id"])
    if "runtime_leases" not in tables:
        op.create_table(
            "runtime_leases", sa.Column("name", sa.String(96), primary_key=True),
            sa.Column("owner", sa.String(190), nullable=False), sa.Column("token", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_runtime_leases_expires_at", "runtime_leases", ["expires_at"])
    if "queue_executions" not in tables:
        op.create_table(
            "queue_executions", sa.Column("job_id", sa.String(64), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("scheduled_tasks.id", ondelete="SET NULL")),
            sa.Column("claim_id", sa.String(64), nullable=False), sa.Column("status", sa.String(24), nullable=False),
            sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
            sa.Column("record_id", sa.Integer(), sa.ForeignKey("task_records.id", ondelete="SET NULL")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "qq_event_inbox" not in tables:
        op.create_table(
            "qq_event_inbox", sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_key", sa.String(128), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False), sa.Column("claim_id", sa.String(64)),
            sa.Column("lease_until", sa.DateTime(timezone=True)), sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("side_effect_started", sa.Boolean(), nullable=False), sa.Column("last_error", sa.String(500)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("account_id", "event_key", name="uq_qq_inbox_account_event"),
        )
        for name in ("account_id", "status", "lease_until"):
            op.create_index(f"ix_qq_event_inbox_{name}", "qq_event_inbox", [name])


def downgrade() -> None:
    for name in ("qq_event_inbox", "queue_executions", "runtime_leases"):
        if name in sa.inspect(op.get_bind()).get_table_names():
            op.drop_table(name)
    for table, column in (("messages", "inbox_id"), ("task_records", "queue_job_id")):
        if column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)
