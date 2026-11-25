"""Archive deleted owners' repositories and persist browser-bound OAuth state."""

import sqlalchemy as sa
from alembic import op

revision = "0016_repository_oauth_scope"
down_revision = "0015_ws_tickets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("github_repositories")}
    if "archived_at" not in columns:
        op.add_column("github_repositories", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    # Preserve historical owner=NULL rows. Only orphaned non-NULL owners are private tombstones.
    bind.execute(sa.text("""
        UPDATE github_repositories SET archived_at=CURRENT_TIMESTAMP, monitor_enabled=FALSE,
          remote_available=FALSE, token_enc=NULL, webhook_secret_enc=NULL
        WHERE owner_user_id IS NOT NULL AND NOT EXISTS
          (SELECT 1 FROM users WHERE users.id=github_repositories.owner_user_id)
    """))
    bind.execute(sa.text("""
        UPDATE push_rules SET enabled=FALSE WHERE repository_id IN
          (SELECT id FROM github_repositories WHERE archived_at IS NOT NULL)
    """))
    if "github_oauth_states" not in inspector.get_table_names():
        op.create_table(
            "github_oauth_states",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("browser_hash", sa.String(64), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("auth_session_id", sa.Integer(), sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("code_verifier_enc", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("github_oauth_states")
    op.drop_column("github_repositories", "archived_at")
