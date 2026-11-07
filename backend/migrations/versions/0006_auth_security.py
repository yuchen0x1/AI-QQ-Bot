"""Add TOTP settings and revocable authentication sessions.

Revision ID: 0006_auth_security
Revises: 0005_github_oauth
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_auth_security"
down_revision = "0005_github_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {col["name"] for col in inspector.get_columns("users")}
    for name, column in (
        ("totp_secret_enc", sa.Column("totp_secret_enc", sa.Text(), nullable=True)),
        ("totp_enabled", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("totp_last_counter", sa.Column("totp_last_counter", sa.Integer(), nullable=True)),
        ("totp_challenge_nonce", sa.Column("totp_challenge_nonce", sa.String(64), nullable=True)),
    ):
        if name not in user_columns:
            op.add_column("users", column)

    if "auth_sessions" not in inspector.get_table_names():
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("jti", sa.String(64), nullable=False),
            sa.Column("ip", sa.String(64), nullable=True),
            sa.Column("user_agent", sa.String(500), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
        op.create_index("ix_auth_sessions_jti", "auth_sessions", ["jti"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "auth_sessions" in inspector.get_table_names():
        indexes = {idx["name"] for idx in inspector.get_indexes("auth_sessions")}
        for name in ("ix_auth_sessions_jti", "ix_auth_sessions_user_id"):
            if name in indexes:
                op.drop_index(name, table_name="auth_sessions")
        op.drop_table("auth_sessions")
    user_columns = {col["name"] for col in inspector.get_columns("users")}
    for name in ("totp_challenge_nonce", "totp_last_counter", "totp_enabled", "totp_secret_enc"):
        if name in user_columns:
            op.drop_column("users", name)
