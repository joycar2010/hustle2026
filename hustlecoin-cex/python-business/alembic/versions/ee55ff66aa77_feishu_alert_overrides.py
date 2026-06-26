"""add feishu_config.alert_overrides (per-alert-type count/interval)

每种提醒(新增借币/借币成功/还币成功/划转失败/风险/爆仓率/错误/裸空)可单独设「提醒次数」「提醒间隔」,
存 JSON {alert_type:{count,interval}};留空回退全局 alert_count/alert_interval_sec。

Revision ID: ee55ff66aa77
Revises: dd44ee55ff66
Create Date: 2026-06-26
"""
from alembic import op

revision = "ee55ff66aa77"
down_revision = "dd44ee55ff66"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE feishu_config ADD COLUMN IF NOT EXISTS alert_overrides JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE feishu_config DROP COLUMN IF EXISTS alert_overrides")
