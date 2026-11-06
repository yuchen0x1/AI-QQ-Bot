"""Add account runtime leases and queue metadata.

Revision ID: 0003_runtime_leases
Revises: 0002_bot_requests
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_runtime_leases"
down_revision = "0002_bot_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    account_columns = {col["name"] for col in inspector.get_columns("account_connections")}
    for name, column in (
        ("lease_owner", sa.Column("lease_owner", sa.String(96))),
        ("lease_id", sa.Column("lease_id", sa.String(96))),
        ("lease_expires_at", sa.Column("lease_expires_at", sa.DateTime(timezone=True))),
    ):
        if name not in account_columns:
            op.add_column("account_connections", column)
    repo_columns = {col["name"] for col in inspector.get_columns("github_repositories")}
    if "provider" not in repo_columns:
        op.add_column("github_repositories", sa.Column("provider", sa.String(24), nullable=False, server_default="github"))
    repo_indexes = {idx["name"] for idx in inspector.get_indexes("github_repositories")}
    if "ix_github_repositories_provider" not in repo_indexes:
        op.create_index("ix_github_repositories_provider", "github_repositories", ["provider"])
    task_columns = {col["name"] for col in inspector.get_columns("scheduled_tasks")}
    for name, column in (
        ("queue_name", sa.Column("queue_name", sa.String(96))),
        ("job_key", sa.Column("job_key", sa.String(190))),
    ):
        if name not in task_columns:
            op.add_column("scheduled_tasks", column)
    indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("account_connections")}
    if "ix_account_connections_lease_owner" not in indexes:
        op.create_index("ix_account_connections_lease_owner", "account_connections", ["lease_owner"])
    if "ix_account_connections_lease_id" not in indexes:
        op.create_index("ix_account_connections_lease_id", "account_connections", ["lease_id"], unique=True)
    if "ix_account_connections_lease_expires_at" not in indexes:
        op.create_index("ix_account_connections_lease_expires_at", "account_connections", ["lease_expires_at"])
    task_indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("scheduled_tasks")}
    if "ix_scheduled_tasks_job_key" not in task_indexes:
        op.create_index("ix_scheduled_tasks_job_key", "scheduled_tasks", ["job_key"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ix_github_repositories_provider" in {idx["name"] for idx in inspector.get_indexes("github_repositories")}:
        op.drop_index("ix_github_repositories_provider", table_name="github_repositories")
    if "provider" in {col["name"] for col in inspector.get_columns("github_repositories")}:
        op.drop_column("github_repositories", "provider")
    if "ix_scheduled_tasks_job_key" in {idx["name"] for idx in inspector.get_indexes("scheduled_tasks")}:
        op.drop_index("ix_scheduled_tasks_job_key", table_name="scheduled_tasks")
    task_columns = {col["name"] for col in inspector.get_columns("scheduled_tasks")}
    if "job_key" in task_columns:
        op.drop_column("scheduled_tasks", "job_key")
    if "queue_name" in task_columns:
        op.drop_column("scheduled_tasks", "queue_name")
    account_indexes = {idx["name"] for idx in inspector.get_indexes("account_connections")}
    if "ix_account_connections_lease_expires_at" in account_indexes:
        op.drop_index("ix_account_connections_lease_expires_at", table_name="account_connections")
    if "ix_account_connections_lease_id" in account_indexes:
        op.drop_index("ix_account_connections_lease_id", table_name="account_connections")
    if "ix_account_connections_lease_owner" in account_indexes:
        op.drop_index("ix_account_connections_lease_owner", table_name="account_connections")
    account_columns = {col["name"] for col in inspector.get_columns("account_connections")}
    for name in ("lease_expires_at", "lease_id", "lease_owner"):
        if name in account_columns:
            op.drop_column("account_connections", name)
