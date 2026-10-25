"""Seed engine alert templates and bind them to QH-style personas.

Rows are inserted only when an administrator has not already created a
template with the same name.  This makes the catalog useful on a fresh Coin
installation without overwriting existing notification policy.
"""

from alembic import op
import sqlalchemy as sa


revision = "a0b1c2d3e4f5"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    templates = [
        ("\u501f\u5e01\u6210\u529f", "trade", "\u501f\u5e01\u6210\u529f", "\u8d26\u6237: {account}, \u5e01\u79cd: {symbol}, \u6570\u91cf: {qty}", True, True, 2, 5, "#3b82f6", False, "tpl_entryspread"),
        ("\u8fd8\u5e01\u6210\u529f", "trade", "\u8fd8\u5e01\u6210\u529f", "\u8d26\u6237: {account}, \u5e01\u79cd: {symbol}, PnL: {pnl} USDT", True, True, 2, 5, "#22c55e", False, "tpl_takeprofit"),
        ("\u98ce\u63a7\u544a\u8b66", "risk", "\u98ce\u63a7\u544a\u8b66", "\u8d26\u6237: {account}, \u4fdd\u8bc1\u91d1\u6c34\u5e73: {level}", True, True, 1, 1800, "#ef4444", True, "tpl_naked"),
        ("\u5f02\u5e38\u4ed3\u4f4d", "risk", "\u5f02\u5e38\u4ed3\u4f4d", "\u8d26\u6237: {account}, \u5e01\u79cd: {symbol}, \u9700\u4eba\u5de5\u4ecb\u5165", True, True, 1, 300, "#ef4444", True, "tpl_singleleg"),
        ("\u7206\u4ed3\u7387\u9884\u8b66", "risk", "\u5408\u7ea6\u7206\u4ed3\u9884\u8b66", "\u8d26\u6237: {account}, \u5f53\u524d: {rate}%, \u9608\u503c: {threshold}%", True, True, 1, 600, "#ef4444", True, "tpl_margin"),
        ("\u5212\u8f6c\u5931\u8d25", "risk", "\u5212\u8f6c\u5931\u8d25", "\u8d26\u6237: {account}, \u91d1\u989d: {amount} USDT", True, True, 1, 300, "#ef4444", True, "tpl_capacity"),
        ("\u9519\u8bef\u544a\u8b66", "system", "\u4ea4\u6613\u9519\u8bef\u544a\u8b66", "\u8d26\u6237: {account}, \u64cd\u4f5c: {action}, \u9519\u8bef: {error}", True, True, 1, 120, "#f59e0b", True, "tpl_ratelimit"),
        ("Worker\u5065\u5eb7\u544a\u8b66", "system", "Worker\u5065\u5eb7\u544a\u8b66", "{message}", True, True, 1, 300, "#ef4444", True, "tpl_announce"),
        ("\u7cfb\u7edf\u901a\u77e5", "system", "\u7cfb\u7edf\u6d88\u606f", "{message}", True, True, 2, 60, "#6b7280", False, "none"),
    ]
    for row in templates:
        (name, category, title, content, feishu, marquee, priority, cooldown,
         color, blink, sound) = row
        op.get_bind().execute(
            sa.text(
                """
            INSERT INTO notification_templates
              (template_name, category, title_template, content_template,
               enable_feishu, enable_email, enable_marquee, priority,
               cooldown_seconds, marquee_color, marquee_blink, sound_key, is_enabled)
            SELECT :name, :category, :title, :content,
                   :feishu, FALSE, :marquee, :priority, :cooldown,
                   :color, :blink, :sound, TRUE
            WHERE NOT EXISTS (
              SELECT 1 FROM notification_templates WHERE template_name = :name
            )
            """
            ),
            {
                "name": name, "category": category, "title": title,
                "content": content, "feishu": feishu, "marquee": marquee,
                "priority": priority, "cooldown": cooldown, "color": color,
                "blink": blink, "sound": sound,
            },
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM notification_templates WHERE template_name IN "
        "('借币成功','还币成功','风控告警','异常仓位','爆仓率预警','划转失败',"
        "'错误告警','Worker健康告警','系统通知')"
    )
