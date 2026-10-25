"""add feishu_config.enable_borrow_success_alert / enable_repay_success_alert

借币成功(开仓/对冲完成)、还币成功(平仓/还币完成)飞书提醒开关。

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-14
"""
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE feishu_config ADD COLUMN IF NOT EXISTS enable_borrow_success_alert BOOLEAN DEFAULT TRUE")
    op.execute("ALTER TABLE feishu_config ADD COLUMN IF NOT EXISTS enable_repay_success_alert BOOLEAN DEFAULT TRUE")


def downgrade() -> None:
    op.execute("ALTER TABLE feishu_config DROP COLUMN IF EXISTS enable_borrow_success_alert")
    op.execute("ALTER TABLE feishu_config DROP COLUMN IF EXISTS enable_repay_success_alert")
