"""add global_rules.removed_cooldown_minutes (post-exit re-borrow cooldown)

同币平仓/移除退出后,此时长内禁止再借,抑制无人值守反复进出(0=不启用)。

Revision ID: y9e0f1a2b3c4
Revises: x8d9e0f1a2b3
Create Date: 2026-06-13
"""
from alembic import op

revision = "y9e0f1a2b3c4"
down_revision = "x8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS removed_cooldown_minutes INTEGER DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS removed_cooldown_minutes")
