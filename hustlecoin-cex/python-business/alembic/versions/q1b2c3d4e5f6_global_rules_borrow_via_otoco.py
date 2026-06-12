"""add global_rules.borrow_via_otoco (IOC OTOCO borrow switch)

Revision ID: q1b2c3d4e5f6
Revises: p0a1b2c3d4e5
Create Date: 2026-06-12
"""
from alembic import op

revision = "q1b2c3d4e5f6"
down_revision = "p0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS borrow_via_otoco BOOLEAN DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS borrow_via_otoco")
