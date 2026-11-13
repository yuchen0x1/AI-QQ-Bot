"""Add repository activity monitoring without discarding release history."""

from alembic import op
import sqlalchemy as sa

revision = "0008_github_activity"
down_revision = "0007_runtime_lease_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("github_repositories", sa.Column("monitor_activity", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("github_repositories", sa.Column("activity_cursor", sa.String(96), nullable=True))
    op.add_column("github_repositories", sa.Column("activity_initialized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("push_rules", sa.Column("event_types", sa.JSON(), nullable=False, server_default='["release"]'))
    op.add_column("push_rules", sa.Column("managed_by_user_id", sa.Integer(), nullable=True))
    op.create_index("ix_push_rules_managed_by_user_id", "push_rules", ["managed_by_user_id"])
    with op.batch_alter_table("push_records") as batch:
        batch.alter_column("release_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("event_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_push_record_event", "github_events", ["event_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_push_records_event_id", ["event_id"])
        batch.create_unique_constraint("uq_push_rule_event", ["rule_id", "event_id"])


def downgrade() -> None:
    # Activity deliveries have no release counterpart. Refuse a destructive downgrade.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM push_records WHERE release_id IS NULL"))
    if count:
        raise RuntimeError("存在动态推送记录，请先导出并迁移这些记录后再降级")
    with op.batch_alter_table("push_records") as batch:
        batch.drop_constraint("uq_push_rule_event", type_="unique")
        batch.drop_index("ix_push_records_event_id")
        batch.drop_constraint("fk_push_record_event", type_="foreignkey")
        batch.drop_column("event_id")
        batch.alter_column("release_id", existing_type=sa.Integer(), nullable=False)
    op.drop_index("ix_push_rules_managed_by_user_id", table_name="push_rules")
    op.drop_column("push_rules", "managed_by_user_id")
    op.drop_column("push_rules", "event_types")
    for column in ("activity_initialized_at", "activity_cursor", "monitor_activity"):
        op.drop_column("github_repositories", column)
