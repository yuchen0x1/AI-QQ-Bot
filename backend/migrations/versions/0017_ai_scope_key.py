"""Make nullable conversation scopes unique and cross-provider fallback opt-in.

Duplicate historical conversations are merged without dropping their messages.
The old nullable key is retained for schema compatibility; the normalized key
provides the actual uniqueness guarantee on both SQLite and PostgreSQL.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_ai_scope_key"
down_revision = "0016_repository_oauth_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    model_columns = {item["name"] for item in sa.inspect(bind).get_columns("ai_models")}
    if "allow_cross_provider_fallback" not in model_columns:
        op.add_column("ai_models", sa.Column("allow_cross_provider_fallback", sa.Boolean(), nullable=False, server_default=sa.false()))

    columns = {item["name"]: item for item in sa.inspect(bind).get_columns("ai_conversations")}
    if "scope_key" not in columns:
        op.add_column("ai_conversations", sa.Column("scope_key", sa.String(96), nullable=True))
    metadata = sa.MetaData()
    conversations = sa.Table("ai_conversations", metadata, autoload_with=bind)
    messages = sa.Table("ai_messages", metadata, autoload_with=bind)
    survivors: dict[tuple[int, str], dict] = {}
    for row in bind.execute(sa.select(conversations).order_by(conversations.c.id)).mappings():
        group = str(row["group_number"]) if row["group_number"] is not None else "-"
        user = str(row["user_id"]) if row["user_id"] is not None else "-"
        scope_key = f"{row['scope']}:{group}:{user}"
        key = (row["account_id"], scope_key)
        keeper = survivors.get(key)
        if keeper is None:
            survivors[key] = dict(row)
            bind.execute(conversations.update().where(conversations.c.id == row["id"]).values(scope_key=scope_key))
            continue
        bind.execute(messages.update().where(messages.c.conversation_id == row["id"]).values(conversation_id=keeper["id"]))
        if row["last_active_at"] and (not keeper["last_active_at"] or row["last_active_at"] > keeper["last_active_at"]):
            keeper["last_active_at"] = row["last_active_at"]
        if not keeper["system_prompt"] and row["system_prompt"]:
            keeper["system_prompt"] = row["system_prompt"]
        bind.execute(conversations.delete().where(conversations.c.id == row["id"]))
    for keeper in survivors.values():
        count = bind.scalar(sa.select(sa.func.count()).select_from(messages).where(messages.c.conversation_id == keeper["id"]))
        bind.execute(conversations.update().where(conversations.c.id == keeper["id"]).values(
            message_count=count,
            last_active_at=keeper["last_active_at"],
            system_prompt=keeper["system_prompt"],
        ))
    constraints = {item["name"] for item in sa.inspect(bind).get_unique_constraints("ai_conversations")}
    with op.batch_alter_table("ai_conversations") as batch:
        batch.alter_column("scope_key", existing_type=sa.String(96), nullable=False)
        if "uq_conversation_scope_key" not in constraints:
            batch.create_unique_constraint("uq_conversation_scope_key", ["account_id", "scope_key"])


def downgrade() -> None:
    with op.batch_alter_table("ai_conversations") as batch:
        batch.drop_constraint("uq_conversation_scope_key", type_="unique")
        batch.drop_column("scope_key")
    op.drop_column("ai_models", "allow_cross_provider_fallback")
