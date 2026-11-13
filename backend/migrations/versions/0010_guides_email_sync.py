"""Track unavailable repositories without losing history and persist failure emails."""
from alembic import op
import sqlalchemy as sa

revision = "0010_guides_email_sync"
down_revision = "0009_notification_targets"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("github_repositories", sa.Column("remote_available", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table("email_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dedupe_key", sa.String(64), nullable=False, unique=True),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_email_alerts_status", "email_alerts", ["status"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM email_alerts")):
        raise RuntimeError("请先导出邮件告警记录，再进行会删除历史的降级")
    op.drop_index("ix_email_alerts_status", table_name="email_alerts")
    op.drop_table("email_alerts")
    op.drop_column("github_repositories", "remote_available")
