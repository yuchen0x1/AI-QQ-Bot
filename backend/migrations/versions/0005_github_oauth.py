"""Add GitHub OAuth bindings and repository ownership.

Revision ID: 0005_github_oauth
Revises: 0004_qq_official
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_github_oauth"
down_revision = "0004_qq_official"
branch_labels = None
depends_on = None

TOKEN_TABLE = "user_github_tokens"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    repo_columns = {col["name"] for col in inspector.get_columns("github_repositories")}
    if "owner_user_id" not in repo_columns:
        # 与模型保持一致：软引用（SQLite 的 ALTER TABLE 无法追加外键），删除用户时由应用层置空。
        op.add_column("github_repositories", sa.Column("owner_user_id", sa.Integer(), nullable=True))
    repo_indexes = {idx["name"] for idx in inspector.get_indexes("github_repositories")}
    if "ix_github_repositories_owner_user_id" not in repo_indexes:
        op.create_index("ix_github_repositories_owner_user_id", "github_repositories", ["owner_user_id"])

    if TOKEN_TABLE not in inspector.get_table_names():
        op.create_table(
            TOKEN_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("github_id", sa.BigInteger(), nullable=False),
            sa.Column("login", sa.String(190), nullable=False),
            sa.Column("name", sa.String(190), nullable=True),
            sa.Column("avatar_url", sa.String(400), nullable=True),
            sa.Column("email", sa.String(190), nullable=True),
            sa.Column("scopes", sa.String(400), nullable=False, server_default=""),
            sa.Column("token_type", sa.String(32), nullable=False, server_default="bearer"),
            sa.Column("access_token_enc", sa.Text(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", name="uq_user_github_token_user"),
        )
        op.create_index("ix_user_github_tokens_user_id", TOKEN_TABLE, ["user_id"])
        op.create_index("ix_user_github_tokens_github_id", TOKEN_TABLE, ["github_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TOKEN_TABLE in inspector.get_table_names():
        token_indexes = {idx["name"] for idx in inspector.get_indexes(TOKEN_TABLE)}
        for name in ("ix_user_github_tokens_github_id", "ix_user_github_tokens_user_id"):
            if name in token_indexes:
                op.drop_index(name, table_name=TOKEN_TABLE)
        op.drop_table(TOKEN_TABLE)

    repo_indexes = {idx["name"] for idx in inspector.get_indexes("github_repositories")}
    if "ix_github_repositories_owner_user_id" in repo_indexes:
        op.drop_index("ix_github_repositories_owner_user_id", table_name="github_repositories")
    repo_columns = {col["name"] for col in inspector.get_columns("github_repositories")}
    if "owner_user_id" in repo_columns:
        op.drop_column("github_repositories", "owner_user_id")
