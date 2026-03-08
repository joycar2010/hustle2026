-- 修复单腿提醒的弹窗模板，使用正确的变量名
UPDATE notification_templates
SET
    popup_title_template = '单腿交易警告',
    popup_content_template = '{exchange} {direction}单腿持仓 {quantity} 手，持续 {duration} 秒'
WHERE template_key = 'single_leg_alert';
