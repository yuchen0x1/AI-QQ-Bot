"""Default data retention to 3 days.

v1.4.6 把数据保留默认值从 30 天改为 3 天；仍停留在旧默认 30 的存量安装一并翻转，
管理员显式设置过的其他值（1/7/45/0 等）不动。
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_retention_default_three"
down_revision = "0013_markdown_card_default_on"
branch_labels = None
depends_on = None


def upgrade():
    settings = sa.table(
        "system_settings",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String),
        sa.column("value", sa.JSON),
    )
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(settings.c.id, settings.c.value).where(settings.c.key == "data_retention_days")
    ).fetchall()
    for row_id, value in rows:
        if isinstance(value, dict):  # 设置页保存的是 {"value": x} 包装
            value = value.get("value")
        if value == 30:
            conn.execute(settings.update().where(settings.c.id == row_id).values(value=3))


def downgrade():
    pass  # 无法区分「旧默认 30」与「用户显式选择」，回滚不改动当前值
