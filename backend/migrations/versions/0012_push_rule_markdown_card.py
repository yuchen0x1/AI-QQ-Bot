"""Add markdown card switch to push rules."""
from alembic import op
import sqlalchemy as sa

revision = "0012_push_rule_markdown_card"
down_revision = "0011_official_only"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "push_rules",
        sa.Column("markdown_card", sa.Boolean(), nullable=False, server_default=sa.false(), default=False),
    )
    op.add_column("push_records", sa.Column("card_payload", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("push_records", "card_payload")
    op.drop_column("push_rules", "markdown_card")
