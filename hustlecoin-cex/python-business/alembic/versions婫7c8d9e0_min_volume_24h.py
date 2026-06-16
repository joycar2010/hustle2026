"""add global_rules.min_volume_24h (成交量交易护栏)

Revision ID: u5a6b7c8d9e0
Revises: t4f5a6b7c8d9
Create Date: 2026-06-13
"""
from alembic import op

revision = "u5a6b7c8d9e0"
down_revision = "t4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS min_volume_24h NUMERIC(20,2) DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS min_volume_24h")
