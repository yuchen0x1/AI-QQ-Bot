"""Add QQ official bot (bot.qq.com) credentials and OpenID identity mapping.

Revision ID: 0004_qq_official
Revises: 0003_runtime_leases
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_qq_official"
down_revision = "0003_runtime_leases"
branch_labels = None
depends_on = None

IDENTITY_TABLE = "qq_official_identities"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    account_columns = {col["name"] for col in inspector.get_columns("accounts")}
    for name, column in (
        ("app_id", sa.Column("app_id", sa.String(64), nullable=True)),
        ("app_secret_enc", sa.Column("app_secret_enc", sa.Text(), nullable=True)),
        ("bot_openid", sa.Column("bot_openid", sa.String(190), nullable=True)),
    ):
        if name not in account_columns:
            op.add_column("accounts", column)
    account_indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("accounts")}
    if "ix_accounts_app_id" not in account_indexes:
        op.create_index("ix_accounts_app_id", "accounts", ["app_id"])

    if IDENTITY_TABLE not in inspector.get_table_names():
        op.create_table(
            IDENTITY_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "account_id",
                sa.Integer(),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("scope", sa.String(190), nullable=False, server_default=""),
            sa.Column("openid", sa.String(190), nullable=False),
            sa.Column("display_name", sa.String(190), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "account_id", "kind", "scope", "openid", name="uq_qq_identity_account_kind_openid"
            ),
        )
        op.create_index("ix_qq_official_identities_account_id", IDENTITY_TABLE, ["account_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if IDENTITY_TABLE in inspector.get_table_names():
        op.drop_index("ix_qq_official_identities_account_id", table_name=IDENTITY_TABLE)
        op.drop_table(IDENTITY_TABLE)
    account_indexes = {idx["name"] for idx in inspector.get_indexes("accounts")}
    if "ix_accounts_app_id" in account_indexes:
        op.drop_index("ix_accounts_app_id", table_name="accounts")
    account_columns = {col["name"] for col in inspector.get_columns("accounts")}
    for name in ("bot_openid", "app_secret_enc", "app_id"):
        if name in account_columns:
            op.drop_column("accounts", name)
