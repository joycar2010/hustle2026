"""add global_rules taker fees + bnb_burn toggle + optimistic-lock version

taker_fee_spot/taker_fee_futures: 可配双腿吃单费率(仅用于 PnL 口径)
bnb_burn_enabled:                  BNB 抵扣开关(每用户,作用于本用户各子账户)
version:                           乐观锁版本号(保存事务化用)

Revision ID: w7c8d9e0f1a2
Revises: v6b7c8d9e0f1
Create Date: 2026-06-13
"""
from alembic import op

revision = "w7c8d9e0f1a2"
down_revision = "v6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS taker_fee_spot NUMERIC(10,6) DEFAULT 0.00075")
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS taker_fee_futures NUMERIC(10,6) DEFAULT 0.00075")
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS bnb_burn_enabled BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0")
    op.execute("ALTER TABLE fund_rules ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS taker_fee_spot")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS taker_fee_futures")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS bnb_burn_enabled")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS version")
    op.execute("ALTER TABLE fund_rules DROP COLUMN IF EXISTS version")
