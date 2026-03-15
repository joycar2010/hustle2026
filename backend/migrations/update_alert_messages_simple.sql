-- 更新提醒消息为简洁格式
-- 执行时间：2026-03-13
-- 说明：根据用户要求更新所有提醒消息为简洁格式

-- ============================================================================
-- 点差提醒消息更新
-- ============================================================================

-- 1. 反向开仓提醒：反向已到货，请查收11111（带实时点差数据和阈值）
UPDATE notification_templates
SET
    title_template = '反向已到货',
    content_template = '反向已到货，请查收11111
当前点差：{spread}
您的阈值：{threshold}',
    popup_title_template = '反向已到货',
    popup_content_template = '反向已到货，请查收11111
当前点差：{spread}
您的阈值：{threshold}',
    updated_at = NOW()
WHERE template_key = 'reverse_open_spread_alert';

-- 2. 反向平仓提醒：反向需清货，请清货00000（带实时点差数据和阈值）
UPDATE notification_templates
SET
    title_template = '反向需清货',
    content_template = '反向需清货，请清货00000
当前点差：{spread}
您的阈值：{threshold}',
    popup_title_template = '反向需清货',
    popup_content_template = '反向需清货，请清货00000
当前点差：{spread}
您的阈值：{threshold}',
    updated_at = NOW()
WHERE template_key = 'reverse_close_spread_alert';

-- 3. 正向开仓提醒：正向已到货，请查收11111（带实时点差数据和阈值）
UPDATE notification_templates
SET
    title_template = '正向已到货',
    content_template = '正向已到货，请查收11111
当前点差：{spread}
您的阈值：{threshold}',
    popup_title_template = '正向已到货',
    popup_content_template = '正向已到货，请查收11111
当前点差：{spread}
您的阈值：{threshold}',
    updated_at = NOW()
WHERE template_key = 'forward_open_spread_alert';

-- 4. 正向平仓提醒：正向需清货，请清货00000（带实时点差数据和阈值）
UPDATE notification_templates
SET
    title_template = '正向需清货',
    content_template = '正向需清货，请清货00000
当前点差：{spread}
您的阈值：{threshold}',
    popup_title_template = '正向需清货',
    popup_content_template = '正向需清货，请清货00000
当前点差：{spread}
您的阈值：{threshold}',
    updated_at = NOW()
WHERE template_key = 'forward_close_spread_alert';

-- ============================================================================
-- 净资产提醒消息更新
-- ============================================================================

-- 5. Binance净资产提醒：*****A仓库需处理*****（带实时资产数据）
UPDATE notification_templates
SET
    title_template = 'A仓库需处理',
    content_template = '*****A仓库需处理*****（当前：{current_asset}，阈值：{threshold}）',
    popup_title_template = 'A仓库需处理',
    popup_content_template = '*****A仓库需处理*****
当前资产：{current_asset}
预警阈值：{threshold}',
    updated_at = NOW()
WHERE template_key = 'binance_net_asset_alert';

-- 6. Bybit净资产提醒：*****B仓库需处理*****（带实时资产数据）
UPDATE notification_templates
SET
    title_template = 'B仓库需处理',
    content_template = '*****B仓库需处理*****（当前：{current_asset}，阈值：{threshold}）',
    popup_title_template = 'B仓库需处理',
    popup_content_template = '*****B仓库需处理*****
当前资产：{current_asset}
预警阈值：{threshold}',
    updated_at = NOW()
WHERE template_key = 'bybit_net_asset_alert';

-- 7. 总资产提醒：*****紧急紧急货不足*****（带实时资产数据）
-- 注意：需要先创建total_net_asset_alert模板（如果不存在）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    popup_title_template,
    popup_content_template,
    enable_feishu,
    priority,
    cooldown_seconds,
    alert_sound_file,
    alert_sound_repeat
) VALUES (
    'total_net_asset_alert',
    '总资产提醒',
    'risk',
    '紧急紧急货不足',
    '*****紧急紧急货不足*****（当前：{current_asset}，阈值：{threshold}）',
    '紧急紧急货不足',
    '*****紧急紧急货不足*****
当前总资产：{current_asset}
预警阈值：{threshold}',
    true,
    4,
    60,
    '/sounds/hello-moto.mp3',
    3
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    popup_title_template = EXCLUDED.popup_title_template,
    popup_content_template = EXCLUDED.popup_content_template,
    updated_at = NOW();

-- ============================================================================
-- 单腿提醒消息更新
-- ============================================================================

-- 8. 单腿提醒：B队员已瘸腿B（带实时数据）
UPDATE notification_templates
SET
    title_template = 'B队员已瘸腿',
    content_template = 'B队员已瘸腿B（Binance：{binance_filled}，Bybit：{bybit_filled}）',
    popup_title_template = 'B队员已瘸腿',
    popup_content_template = 'B队员已瘸腿B
Binance成交：{binance_filled}
Bybit成交：{bybit_filled}
未成交量：{unfilled_qty}',
    updated_at = NOW()
WHERE template_key = 'single_leg_alert';

-- ============================================================================
-- 验证更新结果
-- ============================================================================
SELECT
    template_key,
    template_name,
    title_template,
    content_template,
    popup_title_template,
    popup_content_template
FROM notification_templates
WHERE template_key IN (
    'forward_open_spread_alert',
    'forward_close_spread_alert',
    'reverse_open_spread_alert',
    'reverse_close_spread_alert',
    'binance_net_asset_alert',
    'bybit_net_asset_alert',
    'total_net_asset_alert',
    'single_leg_alert'
)
ORDER BY template_key;
