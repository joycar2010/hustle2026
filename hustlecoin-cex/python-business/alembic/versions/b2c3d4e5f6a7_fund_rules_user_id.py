"""add fund_rules.user_id (per-user isolation of fund/资金 rules)

资金规则(BNB/还债/划转顺序/base_margin_amount/risk_value_threshold/single_transfer_amount 等)
改为按登录用户隔离;legacy 行 user_id=NULL。引擎 config_loader 按 worker 的 user_id 读。

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-14
"""
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE fund_rules ADD COLUMN IF NOT EXISTS user_id INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE fund_rules DROP COLUMN IF EXISTS user_id")
