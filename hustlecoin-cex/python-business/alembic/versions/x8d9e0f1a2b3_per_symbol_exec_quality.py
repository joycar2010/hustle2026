"""add per-symbol execution-quality overrides (slippage_pct/follow_type/note)

每币种 / 每账户·每币种 可覆盖滑点、跟单方式、备注;null=跟随上层(单币种→全局)。

Revision ID: x8d9e0f1a2b3
Revises: w7c8d9e0f1a2
Create Date: 2026-06-13
"""
from alembic import op

revision = "x8d9e0f1a2b3"
down_revision = "w7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for tbl in ("symbol_rules", "account_symbol_rules"):
        op.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS slippage_pct NUMERIC(10,4)")
        op.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS follow_type VARCHAR(10)")
        op.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS note VARCHAR(120)")


def downgrade() -> None:
    for tbl in ("symbol_rules", "account_symbol_rules"):
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS slippage_pct")
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS follow_type")
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS note")
