"""Operational notification templates and supported voice personas."""
from alembic import op
import sqlalchemy as sa

revision = "cc99dd00ee11"
down_revision = "bb88cc99dd00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalize legacy sound keys to the browser-supported sweet/royal presets.
    op.execute("UPDATE notification_templates SET sound_key='ding' WHERE id=3")
    op.execute("UPDATE notification_templates SET sound_key='success' WHERE id=4")
    op.execute("UPDATE notification_templates SET sound_key='alert' WHERE category='risk' AND id NOT IN (8,9)")
    op.execute("UPDATE notification_templates SET sound_key='error' WHERE id IN (1,8,9,12)")
    op.execute("UPDATE notification_templates SET sound_key='chime' WHERE id=2 OR id=11")
    rows = [
        ('BNB残留清理','system','BNB残留清理结果','账户 {account} 的 {asset} 残留已完成 {action}，处理数量 {amount}，结果：{status}。','success','#22c55e',False,2,1800),
        ('行情未到','market','行情未到','币对 {symbol} 的现货和合约行情在 {age} 秒内未同步，请检查行情通道后再进行交易。','alert','#f59e0b',True,1,300),
        ('GitHub备份完成','system','GitHub备份完成','前端、后端及数据库备份已推送到 coin 分支，提交 {commit}，时间 {time}。','chime','#3b82f6',False,2,300),
        ('GitHub备份失败','system','GitHub备份失败','备份推送失败：{error}。请检查磁盘空间、网络和仓库冲突状态。','error','#ef4444',True,1,300),
    ]
    for name, cat, title, content, sound, color, blink, priority, cooldown in rows:
        op.execute(sa.text("""INSERT INTO notification_templates
            (template_name, category, title_template, content_template, enable_feishu, enable_email, enable_marquee, priority, cooldown_seconds, marquee_color, marquee_blink, sound_key, is_enabled)
            SELECT :name,:cat,:title,:content,true,false,true,:priority,:cooldown,:color,:blink,:sound,true
            WHERE NOT EXISTS (SELECT 1 FROM notification_templates WHERE template_name=:name)""").bindparams(name=name,cat=cat,title=title,content=content,priority=priority,cooldown=cooldown,color=color,blink=blink,sound=sound))


def downgrade() -> None:
    op.execute("DELETE FROM notification_templates WHERE template_name IN ('BNB残留清理','行情未到','GitHub备份完成','GitHub备份失败')")
