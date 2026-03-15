-- 添加风险控制提醒模板（生鲜配送语）
-- 执行时间：2026-03-05
-- 说明：为已有的通知服务系统添加10个风险控制提醒模板
--       包括：4个点差值提醒 + 1个MT5状态 + 2个净资产 + 2个爆仓价 + 1个单腿提醒

-- ============================================================================
-- 插入风险控制提醒模板
-- ============================================================================

-- 1. 正向开仓点差值提醒（优惠价格提醒）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds
) VALUES (
    'forward_open_spread_alert',
    '优惠价格提醒',
    'risk',
    '💰 优惠价格机会提醒',
    '**价格优势通知**
当前价格差异：{spread}元/件
优惠阈值：{threshold}元/件
市场状态：{market_status}

建议操作：接收优惠订单
预计收益：{estimated_profit}元

这是一个不错的价格机会！',
    true,
    3,
    60
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    updated_at = NOW();

-- 2. 正向平仓点差值提醒（价格回归提醒）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds
) VALUES (
    'forward_close_spread_alert',
    '价格回归提醒',
    'risk',
    '📊 价格回归通知',
    '**价格变化提醒**
当前价格差异：{spread}元/件
回归阈值：{threshold}元/件
市场状态：{market_status}

建议操作：完成订单配送
当前收益：{current_profit}元

价格已回归正常区间，建议及时处理',
    true,
    3,
    60
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    updated_at = NOW();

-- 3. 反向开仓点差值提醒（反向优惠提醒）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds
) VALUES (
    'reverse_open_spread_alert',
    '反向优惠提醒',
    'risk',
    '💎 反向优惠机会',
    '**反向价格优势**
当前价格差异：{spread}元/件
优惠阈值：{threshold}元/件
市场状态：{market_status}

建议操作：接收反向订单
预计收益：{estimated_profit}元

反向配送优惠机会出现！',
    true,
    3,
    60
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    updated_at = NOW();

-- 4. 反向平仓点差值提醒（反向价格回归）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds
) VALUES (
    'reverse_close_spread_alert',
    '反向价格回归',
    'risk',
    '📈 反向价格回归',
    '**反向价格变化**
当前价格差异：{spread}元/件
回归阈值：{threshold}元/件
市场状态：{market_status}

建议操作：完成反向配送
当前收益：{current_profit}元

反向价格已回归正常，建议及时处理',
    true,
    3,
    60
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    updated_at = NOW();

-- 5. MT5卡顿提醒（配送系统延迟）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds
) VALUES (
    'mt5_lag_alert',
    '配送系统延迟',
    'risk',
    '⚠️ 配送系统延迟提醒',
    '**系统响应异常**
配送系统出现延迟

连接失败次数：{failure_count}次
最后响应时间：{last_response_time}

请检查系统连接状态，必要时重启配送系统',
    true,
    4,
    60
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    updated_at = NOW();

-- 6. Binance净资产提醒（A仓库资产提醒）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds
) VALUES (
    'binance_net_asset_alert',
    'A仓库资产提醒',
    'risk',
    '💰 A仓库资产预警',
    '**资产状况提醒**
当前A仓库净资产：{current_asset}元
预警阈值：{threshold}元

资产已{status}预警线
请及时关注资产变化',
    true,
    3,
    60
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    updated_at = NOW();

-- 7. Bybit净资产提醒（B仓库资产提醒）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds
) VALUES (
    'bybit_net_asset_alert',
    'B仓库资产提醒',
    'risk',
    '💰 B仓库资产预警',
    '**资产状况提醒**
当前B仓库净资产：{current_asset}元
预警阈值：{threshold}元

资产已{status}预警线
请及时关注资产变化',
    true,
    3,
    60
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    updated_at = NOW();

-- 8. Binance爆仓价提醒（A仓库安全线提醒）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds
) VALUES (
    'binance_liquidation_alert',
    'A仓库安全线提醒',
    'risk',
    '🚨 A仓库安全线预警',
    '**价格安全提醒**
当前价格：{current_price}元
安全线价格：{liquidation_price}元
距离安全线：{distance}元

{status}
请密切关注价格变化，必要时调整仓位',
    true,
    4,
    60
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    updated_at = NOW();

-- 9. Bybit爆仓价提醒（B仓库安全线提醒）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds
) VALUES (
    'bybit_liquidation_alert',
    'B仓库安全线提醒',
    'risk',
    '🚨 B仓库安全线预警',
    '**价格安全提醒**
当前价格：{current_price}元
安全线价格：{liquidation_price}元
距离安全线：{distance}元

{status}
请密切关注价格变化，必要时调整仓位',
    true,
    4,
    60
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    updated_at = NOW();

-- 10. 单腿提醒（单边配送提醒）
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority,
    cooldown_seconds
) VALUES (
    'single_leg_alert',
    '单边配送提醒',
    'risk',
    '⚡ 单边配送预警',
    '**配送不平衡提醒**
{exchange}仓库出现单边配送

单边数量：{quantity}件
持续时间：{duration}秒
配送方向：{direction}

请尽快完成对冲配送，避免价格风险',
    true,
    4,
    60
) ON CONFLICT (template_key) DO UPDATE SET
    title_template = EXCLUDED.title_template,
    content_template = EXCLUDED.content_template,
    updated_at = NOW();

-- ============================================================================
-- 验证插入结果
-- ============================================================================
SELECT
    template_key,
    template_name,
    category,
    priority,
    enable_feishu,
    cooldown_seconds
FROM notification_templates
WHERE template_key IN (
    'forward_open_spread_alert',
    'forward_close_spread_alert',
    'reverse_open_spread_alert',
    'reverse_close_spread_alert',
    'mt5_lag_alert',
    'binance_net_asset_alert',
    'bybit_net_asset_alert',
    'binance_liquidation_alert',
    'bybit_liquidation_alert',
    'single_leg_alert'
)
ORDER BY template_key;

-- ============================================================================
-- 使用说明
-- ============================================================================
/*
这10个模板对应风险控制中的各项提醒设置：

【点差值提醒】
1. forward_open_spread_alert - 正向开仓点差值提醒
   触发条件：forward_spread >= forwardOpenPrice
   变量：spread, threshold, market_status, estimated_profit

2. forward_close_spread_alert - 正向平仓点差值提醒
   触发条件：forward_spread <= forwardClosePrice
   变量：spread, threshold, market_status, current_profit

3. reverse_open_spread_alert - 反向开仓点差值提醒
   触发条件：reverse_spread >= reverseOpenPrice
   变量：spread, threshold, market_status, estimated_profit

4. reverse_close_spread_alert - 反向平仓点差值提醒
   触发条件：reverse_spread <= reverseClosePrice
   变量：spread, threshold, market_status, current_profit

【系统状态提醒】
5. mt5_lag_alert - MT5卡顿提醒
   触发条件：MT5连接失败或响应超时
   变量：failure_count, last_response_time

【资产提醒】
6. binance_net_asset_alert - Binance净资产提醒
   触发条件：根据风险控制中的Binance净资产阈值设置
   变量：current_asset, threshold, status

7. bybit_net_asset_alert - Bybit净资产提醒
   触发条件：根据风险控制中的Bybit净资产阈值设置
   变量：current_asset, threshold, status

【爆仓价提醒】
8. binance_liquidation_alert - Binance爆仓价提醒
   触发条件：根据风险控制中的Binance爆仓价设置
   变量：current_price, liquidation_price, distance, status

9. bybit_liquidation_alert - Bybit爆仓价提醒
   触发条件：根据风险控制中的Bybit爆仓价设置
   变量：current_price, liquidation_price, distance, status

【单腿提醒】
10. single_leg_alert - 单腿提醒
    触发条件：根据风险控制中的单腿提醒开关
    变量：exchange, quantity, duration, direction

所有模板：
- 冷却时间：60秒（避免频繁通知）
- 优先级：3或4（高优先级/紧急）
- 默认启用飞书通知
- 使用"生鲜配送语"避免敏感词
*/

