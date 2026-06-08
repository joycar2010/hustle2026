"""add missing aicoin_config columns: is_active, created_at (model/migration drift)

Revision ID: p0a1b2c3d4e5
Revises: o9a0b1c2d3e4
Create Date: 2026-06-08
"""
from alembic import op

revision = "p0a1b2c3d4e5"
down_revision = "o9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AiCoinConfig model declares is_active + created_at, but the table was created
    # without them -> /api/admin/system/aicoin-config 500s and market._get_aicoin()
    # silently swallows the DB error and falls back to env keys. Idempotent ADDs so
    # this is safe regardless of per-environment drift.
    op.execute("ALTER TABLE aicoin_config ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
    op.execute("ALTER TABLE aicoin_config ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()")


def downgrade() -> None:
    op.execute("ALTER TABLE aicoin_config DROP COLUMN IF EXISTS created_at")
    op.execute("ALTER TABLE aicoin_config DROP COLUMN IF EXISTS is_active")
