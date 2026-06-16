"""add is_risky hard-block toggle + two-leg(futures) volume filter

global_rules.block_risky_open:       开启后 is_risky 的币也禁止开仓
global_rules.min_volume_24h_futures: 合约腿 24h 成交量门槛(双腿量过滤)
symbols.futures_volume_24h:          合约 24h 成交额采集列

Revision ID: z0f1a2b3c4d5
Revises: y9e0f1a2b3c4
Create Date: 2026-06-13
"""
from alembic import op

revision = "z0f1a2b3c4d5"
down_revision = "y9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS block_risky_open BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS min_volume_24h_futures NUMERIC(20,2) DEFAULT 0")
    op.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS futures_volume_24h NUMERIC(20,2)")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS block_risky_open")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS min_volume_24h_futures")
    op.execute("ALTER TABLE symbols DROP COLUMN IF EXISTS futures_volume_24h")
