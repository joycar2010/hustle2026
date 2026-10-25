"""净期望收益闸 + 逐回路净损益记账 + 净期望闸模式开关

positions.expected_e:     开仓时算出的预期净收益 E(USDT,点差捕获−利息−4腿手续费−tick摩擦[+资金费预期])
positions.round_net_pnl:  平仓结算的本回路真实净损益(USDT = realized_pnl + 已结算资金费),事后校准 E 用
positions.e_breakdown:    E 各分项 JSON(存证/展示)
global_rules.net_gate_mode: 净期望闸模式 off/shadow/enforce(默认 shadow — 只评估记录不拦,先跑一周)

Revision ID: ff66aa77bb88
Revises: ee55ff66aa77
Create Date: 2026-07-07
"""
from alembic import op

revision = "ff66aa77bb88"
down_revision = "ee55ff66aa77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS expected_e NUMERIC(15,4)")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS round_net_pnl NUMERIC(15,4)")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS e_breakdown TEXT")
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS net_gate_mode VARCHAR(10) DEFAULT 'shadow'")


def downgrade() -> None:
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS expected_e")
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS round_net_pnl")
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS e_breakdown")
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS net_gate_mode")
