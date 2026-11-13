"""Ensure the runtime lease id index exists on upgraded databases.

Revision ID: 0007_runtime_lease_index
Revises: 0006_auth_security
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_runtime_lease_index"
down_revision = "0006_auth_security"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_account_connections_lease_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("account_connections")}
    if INDEX_NAME not in indexes:
        op.create_index(INDEX_NAME, "account_connections", ["lease_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("account_connections")}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name="account_connections")
