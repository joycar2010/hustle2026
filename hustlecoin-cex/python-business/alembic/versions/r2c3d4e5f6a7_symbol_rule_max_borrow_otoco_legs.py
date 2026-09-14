"""add symbol_rules.max_borrow_amount + global_rules.otoco_legs

Revision ID: r2c3d4e5f6a7
Revises: q1b2c3d4e5f6
Create Date: 2026-06-12
"""
from alembic import op

revision = "r2c3d4e5f6a7"
down_revision = "q1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE symbol_rules ADD COLUMN IF NOT EXISTS max_borrow_amount NUMERIC(15,2)")
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS otoco_legs INTEGER DEFAULT 2")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS otoco_legs")
    op.execute("ALTER TABLE symbol_rules DROP COLUMN IF EXISTS max_borrow_amount")
