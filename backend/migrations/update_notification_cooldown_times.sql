-- 更新通知模板冷却时间
-- 净资产提醒：60秒（1分钟）
-- 点差提醒：10秒
-- MT5卡顿：10秒

-- 更新净资产提醒模板冷却时间为60秒
UPDATE notification_templates
SET cooldown_seconds = 60
WHERE template_key IN (
    'binance_net_asset_alert',
    'bybit_net_asset_alert',
    'total_net_asset_alert'
);

-- 更新点差提醒模板冷却时间为10秒
UPDATE notification_templates
SET cooldown_seconds = 10
WHERE template_key IN (
    'forward_open_spread_alert',
    'forward_close_spread_alert',
    'reverse_open_spread_alert',
    'reverse_close_spread_alert'
);

-- 更新MT5卡顿提醒模板冷却时间为10秒
UPDATE notification_templates
SET cooldown_seconds = 10
WHERE template_key = 'mt5_lag_alert';
