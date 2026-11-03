"""Add durable OneBot request review records.

Revision ID: 0002_bot_requests
Revises: 0001_initial
Create Date: 2026-11-03
"""
from __future__ import annotations

from alembic import op
from app.models import BotRequest

revision = "0002_bot_requests"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The application startup path also creates metadata for fresh databases.
    # checkfirst keeps this revision safe for both fresh and previously migrated DBs.
    BotRequest.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    BotRequest.__table__.drop(bind=op.get_bind(), checkfirst=True)
