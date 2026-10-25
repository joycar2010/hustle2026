"""notification v2: marquee, email, sound fields + seed 12 templates

Revision ID: i3a4b5c6d7e8
Revises: h2b3c4d5e6f7
"""
from alembic import op
import sqlalchemy as sa

revision = "i3a4b5c6d7e8"
down_revision = "h2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns to notification_templates
    op.add_column("notification_templates", sa.Column("enable_marquee", sa.Boolean(), server_default="true"))
    op.add_column("notification_templates", sa.Column("marquee_color", sa.String(20), server_default="'#3b82f6'"))
    op.add_column("notification_templates", sa.Column("marquee_blink", sa.Boolean(), server_default="false"))
    op.add_column("notification_templates", sa.Column("sound_key", sa.String(30), server_default="'none'"))

    # Create email_config table
    op.create_table(
        "email_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("smtp_host", sa.String(200), server_default="''"),
        sa.Column("smtp_port", sa.Integer(), server_default="465"),
        sa.Column("smtp_user", sa.String(200), server_default="''"),
        sa.Column("smtp_password", sa.String(200), server_default="''"),
        sa.Column("smtp_from", sa.String(200), server_default="''"),
        sa.Column("use_ssl", sa.Boolean(), server_default="true"),
        sa.Column("is_enabled", sa.Boolean(), server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Clear old 4 templates and re-seed with 12
    op.execute("DELETE FROM notification_templates")
    op.execute("""
    INSERT INTO notification_templates
        (template_name, category, title_template, content_template, enable_feishu, enable_email, enable_marquee, priority, cooldown_seconds, marquee_color, marquee_blink, sound_key, is_enabled)
    VALUES
        ('开仓通知',   'trade',  '新增借币',     '币对: {symbol}, 价差: {spread}%, 金额: {amount} USDT', true, false, true, 2, 5,  '#3b82f6', false, 'ding',    true),
        ('平仓通知',   'trade',  '平仓完成',     '币对: {symbol}, PnL: {pnl} USDT',                     true, false, true, 2, 5,  '#22c55e', false, 'success', true),
        ('风控告警',   'risk',   '风控预警',     '风控等级: {level}, 详情: {detail}',                    true, false, true, 1, 30, '#ef4444', true,  'alert',   true),
        ('爆仓率预警', 'risk',   '爆仓率预警',   '账户: {account}, 当前: {rate}%, 阈值: {threshold}%',   true, false, true, 1, 60, '#ef4444', true,  'alert',   true),
        ('杠杆风险预警','risk',  '杠杆风险',     '账户: {account}, 风险值: {risk}, 阈值: {threshold}',   true, false, true, 1, 60, '#f59e0b', true,  'alert',   true),
        ('划转失败',   'system', '划转失败',     '账户: {account}, 方向: {direction}, 金额: {amount}',   true, false, true, 1, 30, '#ef4444', true,  'error',   true),
        ('借币成功',   'trade',  '借币成功',     '账户: {account}, 币种: {symbol}, 数量: {qty}',         true, false, true, 3, 5,  '#3b82f6', false, 'ding',    true),
        ('还币成功',   'trade',  '还币完成',     '账户: {account}, 币种: {symbol}, 数量: {qty}',         true, false, true, 3, 5,  '#22c55e', false, 'success', true),
        ('异常仓位',   'risk',   '异常仓位',     '账户: {account}, 币种: {symbol}, 需人工介入',          true, false, true, 1, 0,  '#ef4444', true,  'alert',   true),
        ('系统通知',   'system', '系统消息',     '{message}',                                            true, false, true, 3, 60, '#6b7280', false, 'none',    true),
        ('引擎启停',   'system', '引擎状态变更', '引擎 {action}, 工人数: {count}',                       true, false, true, 2, 10, '#f59e0b', false, 'ding',    true),
        ('资金费结算', 'trade',  '资金费结算',   '结算: {count} 个仓位, 总计: {total} USDT',             false,false, true, 3, 300,'#8b5cf6', false, 'none',    true)
    """)


def downgrade() -> None:
    op.drop_table("email_config")
    op.drop_column("notification_templates", "sound_key")
    op.drop_column("notification_templates", "marquee_blink")
    op.drop_column("notification_templates", "marquee_color")
    op.drop_column("notification_templates", "enable_marquee")
