"""Preserve the existing destination while enabling multiple notification groups."""

from alembic import op
import sqlalchemy as sa

revision = "0009_notification_targets"
down_revision = "0008_github_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("groups", sa.Column("display_number", sa.String(32), nullable=True))
    op.create_index("ix_groups_display_number", "groups", ["display_number"])
    op.create_table(
        "github_notification_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_label", sa.String(80), nullable=False),
        sa.Column("qq_group", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "account_id", "group_label", name="uq_notification_target_user_account_group"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_github_notification_targets_user_id", "github_notification_targets", ["user_id"])
    with op.batch_alter_table("push_rules") as batch:
        batch.add_column(sa.Column("notification_target_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_rule_notification_target", "github_notification_targets", ["notification_target_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_push_rules_notification_target_id", ["notification_target_id"])
        batch.create_unique_constraint("uq_push_rule_notification_target", ["repository_id", "notification_target_id"])
    bind = op.get_bind()
    config = sa.table("system_settings", sa.column("key", sa.String()), sa.column("value", sa.JSON()))
    target = sa.table("github_notification_targets", sa.column("id", sa.Integer()), sa.column("user_id", sa.Integer()),
                      sa.column("account_id", sa.Integer()), sa.column("group_label", sa.String()), sa.column("qq_group", sa.BigInteger()), sa.column("enabled", sa.Boolean()))
    for key, value in bind.execute(sa.select(config).where(config.c.key.startswith("github_notifications:"))).all():
        if not isinstance(value, dict) or not value.get("account_id"):
            continue
        user_id = int(key.split(":", 1)[1])
        account_id = value["account_id"]
        if not bind.scalar(sa.text("SELECT id FROM users WHERE id=:id"), {"id": user_id}) or not bind.scalar(sa.text("SELECT id FROM accounts WHERE id=:id"), {"id": account_id}):
            continue
        label = str(value.get("group_label") or "未标注群号")
        new_id = bind.execute(target.insert().values(user_id=user_id, account_id=account_id, group_label=label,
                                                     qq_group=value.get("qq_group"), enabled=True).returning(target.c.id)).scalar_one()
        bind.execute(sa.text("UPDATE push_rules SET notification_target_id=:target WHERE managed_by_user_id=:owner"), {"target": new_id, "owner": user_id})
        if label.isdigit() and value.get("qq_group"):
            bind.execute(sa.text("UPDATE groups SET display_number=:label WHERE account_id=:account AND group_number=:internal"),
                         {"label": label, "account": account_id, "internal": value["qq_group"]})


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT user_id FROM github_notification_targets GROUP BY user_id HAVING count(*) > 1")).first():
        raise RuntimeError("存在多个通知群，请先导出并处理多群配置后再降级")
    with op.batch_alter_table("push_rules") as batch:
        batch.drop_constraint("uq_push_rule_notification_target", type_="unique")
        batch.drop_index("ix_push_rules_notification_target_id")
        batch.drop_constraint("fk_rule_notification_target", type_="foreignkey")
        batch.drop_column("notification_target_id")
    op.drop_index("ix_github_notification_targets_user_id", table_name="github_notification_targets")
    op.drop_table("github_notification_targets")
    op.drop_index("ix_groups_display_number", table_name="groups")
    op.drop_column("groups", "display_number")
