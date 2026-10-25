"""净敞口自动收敛开关 + 现货腿下单模式(maker化)

global_rules.hedge_auto_converge: 检测到裸多(master实仓>在管对冲)时自动 reduceOnly 对齐(默认 FALSE,只告警)
global_rules.spot_order_mode:      现货腿下单模式 market(市价,现状)/maker(post-only限价,省手续费),默认 market

Revision ID: aa77bb88cc99
Revises: ff66aa77bb88
Create Date: 2026-07-07
"""
from alembic import op

revision = "aa77bb88cc99"
down_revision = "ff66aa77bb88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS hedge_auto_converge BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS spot_order_mode VARCHAR(10) DEFAULT 'market'")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS hedge_auto_converge")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS spot_order_mode")
