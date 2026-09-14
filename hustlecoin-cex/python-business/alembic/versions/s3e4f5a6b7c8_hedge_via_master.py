"""add global_rules.hedge_via_master + positions.hedge_account

Revision ID: s3e4f5a6b7c8
Revises: r2c3d4e5f6a7
Create Date: 2026-06-12
"""
from alembic import op

revision = "s3e4f5a6b7c8"
down_revision = "r2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS hedge_via_master BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS hedge_account VARCHAR(10)")


def downgrade() -> None:
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS hedge_account")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS hedge_via_master")
