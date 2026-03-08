-- 更新通知模板的弹窗配置，使用前端硬编码的内容
-- 将原来硬编码在前端的提醒内容移动到数据库模板中

-- 点差提醒模板（使用前端硬编码的内容）
UPDATE notification_templates
SET
    popup_title_template = '正向套利开仓机会',
    popup_content_template = '当前点差: {spread} USDT，达到开仓阈值 {threshold} USDT',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 3
WHERE template_key = 'forward_open_spread_alert';

UPDATE notification_templates
SET
    popup_title_template = '正向套利平仓机会',
    popup_content_template = '当前点差: {spread} USDT，达到平仓阈值 {threshold} USDT',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 3
WHERE template_key = 'forward_close_spread_alert';

UPDATE notification_templates
SET
    popup_title_template = '反向套利开仓机会',
    popup_content_template = '当前点差: {spread} USDT，达到开仓阈值 {threshold} USDT',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 3
WHERE template_key = 'reverse_open_spread_alert';

UPDATE notification_templates
SET
    popup_title_template = '反向套利平仓机会',
    popup_content_template = '当前点差: {spread} USDT，达到平仓阈值 {threshold} USDT',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 3
WHERE template_key = 'reverse_close_spread_alert';

-- 净资产提醒模板（使用前端硬编码的内容）
UPDATE notification_templates
SET
    popup_title_template = 'Binance净资产预警',
    popup_content_template = '当前净资产: {current_asset} USDT，低于阈值 {threshold} USDT',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 3
WHERE template_key = 'binance_net_asset_alert';

UPDATE notification_templates
SET
    popup_title_template = 'Bybit MT5净资产预警',
    popup_content_template = '当前净资产: {current_asset} USDT，低于阈值 {threshold} USDT',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 3
WHERE template_key = 'bybit_net_asset_alert';

UPDATE notification_templates
SET
    popup_title_template = '总资产预警',
    popup_content_template = '当前总资产: {current_asset} USDT，低于阈值 {threshold} USDT',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 3
WHERE template_key = 'total_net_asset_alert';

-- 爆仓价提醒模板（使用前端硬编码的内容）
UPDATE notification_templates
SET
    popup_title_template = 'Binance爆仓价预警',
    popup_content_template = '当前价格: {current_price}，爆仓价: {liquidation_price}，距离: {distance}',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 5
WHERE template_key = 'binance_liquidation_alert';

UPDATE notification_templates
SET
    popup_title_template = 'Bybit爆仓价预警',
    popup_content_template = '当前价格: {current_price}，爆仓价: {liquidation_price}，距离: {distance}',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 5
WHERE template_key = 'bybit_liquidation_alert';

-- MT5卡顿提醒模板（使用前端硬编码的内容）
UPDATE notification_templates
SET
    popup_title_template = 'MT5卡顿预警',
    popup_content_template = '当前卡顿次数: {lag_count}，达到阈值 {threshold}',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 3
WHERE template_key = 'mt5_lag_alert';

-- 单腿提醒模板（原来就是动态的，保持不变）
UPDATE notification_templates
SET
    popup_title_template = '单腿交易警告',
    popup_content_template = '{message}',
    alert_sound_file = '/sounds/hello-moto.mp3',
    alert_sound_repeat = 5
WHERE template_key = 'single_leg_alert';
