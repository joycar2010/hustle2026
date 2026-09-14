"""add global_rules.max_spread_pct (行情 glitch 护栏)

Revision ID: t4f5a6b7c8d9
Revises: s3e4f5a6b7c8
Create Date: 2026-06-12
"""
from alembic import op

revision = "t4f5a6b7c8d9"
down_revision = "s3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS max_spread_pct NUMERIC(10,4) DEFAULT 3.0")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS max_spread_pct")
