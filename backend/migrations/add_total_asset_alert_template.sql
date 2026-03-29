-- Add total net asset alert template
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds,
    is_active
) VALUES (
    'total_net_asset_alert',
    '总资产提醒',
    'risk',
    '💰 总资产预警',
    '**总资产状况提醒**
当前总资产：{current_asset}元
预警阈值：{threshold}元

资产已{status}预警线
请及时关注资产变化',
    true,
    3,
    300,
    true
) ON CONFLICT (template_key) DO UPDATE SET
    template_name = EXCLUDED.template_name,
    category = EXCLUDED.category,
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    enable_feishu = EXCLUDED.enable_feishu,
    priority = EXCLUDED.priority,
    cooldown_seconds = EXCLUDED.cooldown_seconds,
    is_active = EXCLUDED.is_active;
