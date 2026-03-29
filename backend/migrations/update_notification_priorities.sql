-- 更新通知模板优先级
-- Priority 4（红色，最高优先级）：爆仓价、净资产、单腿提醒
-- Priority 3（橙色）：点差提醒、MT5卡顿

-- 更新爆仓价提醒为最高优先级
UPDATE notification_templates
SET priority = 4
WHERE template_key IN (
    'binance_liquidation_alert',
    'bybit_liquidation_alert'
);

-- 更新净资产提醒为最高优先级
UPDATE notification_templates
SET priority = 4
WHERE template_key IN (
    'binance_net_asset_alert',
    'bybit_net_asset_alert',
    'total_net_asset_alert'
);

-- 更新单腿提醒为最高优先级
UPDATE notification_templates
SET priority = 4
WHERE template_key = 'single_leg_alert';

-- 确保点差提醒为橙色优先级
UPDATE notification_templates
SET priority = 3
WHERE template_key IN (
    'forward_open_spread_alert',
    'forward_close_spread_alert',
    'reverse_open_spread_alert',
    'reverse_close_spread_alert'
);

-- 确保MT5卡顿为橙色优先级
UPDATE notification_templates
SET priority = 3
WHERE template_key = 'mt5_lag_alert';
