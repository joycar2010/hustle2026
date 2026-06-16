"""add global_rules.open_spread_buffer (anti-latency open threshold buffer)

实际借币要求 spread_short >= borrow_spread + open_spread_buffer,吸收腿间滑点 / ~160ms 借币延迟。0=不留(旧行为)。

Revision ID: a1b2c3d4e5f6
Revises: z0f1a2b3c4d5
Create Date: 2026-06-14
"""
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "z0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS open_spread_buffer NUMERIC(10,4) DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS open_spread_buffer")
