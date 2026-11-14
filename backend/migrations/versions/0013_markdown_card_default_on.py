"""Default markdown card on for push rules.

v1.4.0 将卡片做成逐规则开关且默认关闭，自动创建的规则从未带过该开关，
导致生产从未真正发送过卡片。卡片发送失败时会自动降级纯文本，默认开启是安全的。
"""
from alembic import op

revision = "0013_markdown_card_default_on"
down_revision = "0012_push_rule_markdown_card"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE push_rules SET markdown_card = 1")


def downgrade():
    op.execute("UPDATE push_rules SET markdown_card = 0")
