"""add feishu_config.risk_alert_cooldown_sec

子账户「保证金水平」风险告警专属冷却(默认 1800s=30min)。低保证金会每个风控周期(30s)
持续命中 notify_risk → 之前仅受 5s 全局节流约束而刷屏。此列给该告警单独去抖,0=退回全局节流。

Revision ID: dd44ee55ff66
Revises: cc33dd44ee55
Create Date: 2026-06-23
"""
from alembic import op

revision = "dd44ee55ff66"
down_revision = "cc33dd44ee55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE feishu_config ADD COLUMN IF NOT EXISTS risk_alert_cooldown_sec INTEGER DEFAULT 1800")


def downgrade() -> None:
    op.execute("ALTER TABLE feishu_config DROP COLUMN IF EXISTS risk_alert_cooldown_sec")
