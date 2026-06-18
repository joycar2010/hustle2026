"""borrow_mode enum + multi-account parallel borrow cap

global_rules.borrow_mode:                    借币方式枚举 repay/otoco/single/multi(null=回退 borrow_via_otoco)
global_rules.multi_max_accounts_per_symbol:  多账户并联同一币的账户数上限(borrow_mode=multi)

Additive only. borrow_mode 留空时引擎按旧 borrow_via_otoco 推导 → 零行为变动。

Revision ID: bb22cc33dd44
Revises: aa11bb22cc33
Create Date: 2026-06-18
"""
from alembic import op

revision = "bb22cc33dd44"
down_revision = "aa11bb22cc33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS borrow_mode VARCHAR(20) DEFAULT NULL")
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS multi_max_accounts_per_symbol INTEGER DEFAULT 3")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS borrow_mode")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS multi_max_accounts_per_symbol")
