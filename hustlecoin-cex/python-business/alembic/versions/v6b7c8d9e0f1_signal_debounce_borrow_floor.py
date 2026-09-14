"""add global_rules signal-debounce + borrow floor + collateral ratio

filter_duration_ms: 信号级防抖(coinmini 同款),点差需持续超阈 N ms 才触发借币
min_borrow_usdt:    单笔借币名义下限,过滤尘埃单
collateral_ratio:   OTOCO 借币按 maxBorrowable×此比例封顶(抵押率安全垫)

Revision ID: v6b7c8d9e0f1
Revises: u5a6b7c8d9e0
Create Date: 2026-06-13
"""
from alembic import op

revision = "v6b7c8d9e0f1"
down_revision = "u5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS filter_duration_ms INTEGER DEFAULT 0")
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS min_borrow_usdt NUMERIC(15,2) DEFAULT 0")
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS collateral_ratio NUMERIC(6,4) DEFAULT 1")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS filter_duration_ms")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS min_borrow_usdt")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS collateral_ratio")
