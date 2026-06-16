"""add global_rules.spread_stale_sec (利差监控新鲜阈值, 系统全局)

/spreads 利差监控:ts 落后全表最新值超此秒数的币不显示(死币剔除)。系统全局,admin「系统后端规则」可配。

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-15
"""
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_rules ADD COLUMN IF NOT EXISTS spread_stale_sec INTEGER DEFAULT 300")


def downgrade() -> None:
    op.execute("ALTER TABLE global_rules DROP COLUMN IF EXISTS spread_stale_sec")
