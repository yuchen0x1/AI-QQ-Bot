"""Retire nonofficial QQ runtimes without deleting historical records."""
from alembic import op
import sqlalchemy as sa

revision = "0011_official_only"
down_revision = "0010_guides_email_sync"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    accounts = sa.table("accounts", sa.column("id", sa.Integer()), sa.column("protocol", sa.String()),
                        sa.column("enabled", sa.Boolean()), sa.column("auto_start", sa.Boolean()), sa.column("connection_mode", sa.String()))
    bind.execute(accounts.update().where(accounts.c.protocol == "qq_official",
        accounts.c.connection_mode.not_in(["official_ws", "official_webhook"])).values(connection_mode="official_ws"))
    retired = list(bind.scalars(sa.select(accounts.c.id).where(accounts.c.protocol != "qq_official")))
    if not retired:
        return
    bind.execute(accounts.update().where(accounts.c.id.in_(retired)).values(enabled=False, auto_start=False))
    for name in ("push_rules", "github_notification_targets"):
        table = sa.table(name, sa.column("account_id", sa.Integer()), sa.column("enabled", sa.Boolean()))
        bind.execute(table.update().where(table.c.account_id.in_(retired)).values(enabled=False))
    connections = sa.table("account_connections", sa.column("account_id", sa.Integer()), sa.column("status", sa.String()),
                           sa.column("last_error", sa.Text()), sa.column("lease_owner", sa.String()),
                           sa.column("lease_id", sa.String()), sa.column("lease_expires_at", sa.DateTime(timezone=True)))
    bind.execute(connections.update().where(connections.c.account_id.in_(retired)).values(
        status="stopped", last_error="非官方接入已移除，请使用 QQ 官方机器人", lease_owner=None, lease_id=None, lease_expires_at=None))
    tasks = sa.table("scheduled_tasks", sa.column("id", sa.Integer()), sa.column("payload", sa.JSON()), sa.column("enabled", sa.Boolean()))
    for task_id, payload in bind.execute(sa.select(tasks.c.id, tasks.c.payload)):
        if isinstance(payload, dict) and str(payload.get("account_id")) in {str(i) for i in retired}:
            bind.execute(tasks.update().where(tasks.c.id == task_id).values(enabled=False))


def downgrade():
    # A downgrade cannot infer which previously retired accounts were intentionally disabled.
    pass
