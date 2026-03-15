-- 通知服务数据库迁移脚本
-- 执行时间：2026-03-05

-- ============================================================================
-- 1. 创建通知配置表
-- ============================================================================
CREATE TABLE IF NOT EXISTS notification_configs (
    config_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_type VARCHAR(50) UNIQUE NOT NULL,
    is_enabled BOOLEAN DEFAULT FALSE NOT NULL,
    config_data JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

COMMENT ON TABLE notification_configs IS '通知服务配置表';
COMMENT ON COLUMN notification_configs.service_type IS '服务类型：email, sms, feishu';
COMMENT ON COLUMN notification_configs.config_data IS '服务配置JSON';

-- ============================================================================
-- 2. 创建通知模板表
-- ============================================================================
CREATE TABLE IF NOT EXISTS notification_templates (
    template_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_key VARCHAR(100) UNIQUE NOT NULL,
    template_name VARCHAR(200) NOT NULL,
    category VARCHAR(50) NOT NULL,
    title_template VARCHAR(500) NOT NULL,
    content_template TEXT NOT NULL,
    enable_email BOOLEAN DEFAULT FALSE,
    enable_sms BOOLEAN DEFAULT FALSE,
    enable_feishu BOOLEAN DEFAULT FALSE,
    priority INTEGER DEFAULT 1,
    cooldown_seconds INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

COMMENT ON TABLE notification_templates IS '通知模板表（生鲜配送语）';
COMMENT ON COLUMN notification_templates.category IS '分类：trading, risk, system';
COMMENT ON COLUMN notification_templates.priority IS '优先级：1=low, 2=medium, 3=high, 4=urgent';

CREATE INDEX idx_notification_templates_category ON notification_templates(category);
CREATE INDEX idx_notification_templates_active ON notification_templates(is_active);

-- ============================================================================
-- 3. 创建通知日志表
-- ============================================================================
CREATE TABLE IF NOT EXISTS notification_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id),
    template_key VARCHAR(100) NOT NULL,
    service_type VARCHAR(50) NOT NULL,
    recipient VARCHAR(500) NOT NULL,
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(50) NOT NULL,
    error_message TEXT,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL
);

COMMENT ON TABLE notification_logs IS '通知发送日志';
COMMENT ON COLUMN notification_logs.status IS '状态：pending, sent, failed';

CREATE INDEX idx_notification_logs_user ON notification_logs(user_id);
CREATE INDEX idx_notification_logs_created ON notification_logs(created_at DESC);
CREATE INDEX idx_notification_logs_status ON notification_logs(status);

-- ============================================================================
-- 4. 插入初始配置
-- ============================================================================
INSERT INTO notification_configs (service_type, is_enabled, config_data) VALUES
('feishu', false, '{"app_id": "cli_a9235819f078dcbd", "app_secret": ""}'),
('email', false, '{"smtp_host": "smtp.gmail.com", "smtp_port": 587, "username": "", "password": "", "from_email": ""}'),
('sms', false, '{"provider": "aliyun", "access_key": "", "access_secret": "", "sign_name": ""}')
ON CONFLICT (service_type) DO NOTHING;

-- ============================================================================
-- 5. 插入通知模板（生鲜配送语）
-- ============================================================================
INSERT INTO notification_templates (template_key, template_name, category, title_template, content_template, enable_feishu, priority) VALUES

-- 交易类通知
('trade_executed', '订单配送完成', 'trading',
 '🚚 您的订单已配送完成',
 '**订单详情**\n订单编号：{order_id}\n商品名称：{product_name}\n配送数量：{quantity}件\n配送时间：{time}\n配送状态：✅ 已签收',
 true, 2),

('position_opened', '新订单已接收', 'trading',
 '📦 新订单已接收',
 '**订单信息**\n订单类型：{order_type}\n商品规格：{specification}\n订单数量：{quantity}件\n预计配送时间：{estimated_time}',
 true, 2),

('position_closed', '订单已完成', 'trading',
 '✅ 订单配送完成',
 '**配送结果**\n订单编号：{order_id}\n配送结果：{result}\n实际数量：{actual_quantity}件\n客户评价：{feedback}',
 true, 2),

-- 风险类通知
('balance_alert', '账户余额提醒', 'risk',
 '⚠️ 账户余额不足提醒',
 '**余额预警**\n尊敬的客户，您的账户余额已低于安全线\n\n当前余额：{balance}元\n建议充值：{recommend_amount}元\n\n请及时处理，避免影响配送服务',
 true, 3),

('risk_warning', '库存预警', 'risk',
 '⚠️ 库存预警通知',
 '**库存状态**\n商品名称：{product_name}\n当前库存：{current_stock}件\n预警阈值：{threshold}件\n建议补货：{recommend_restock}件',
 true, 4),

('margin_call', '预付款不足', 'risk',
 '🔴 预付款不足警告',
 '**紧急通知**\n您的预付款余额不足\n\n当前预付款：{margin}元\n所需预付款：{required_margin}元\n缺口金额：{shortage}元\n\n请立即充值，避免订单被取消',
 true, 4),

-- 点差值提醒（生鲜配送语：价格差异提醒）
('forward_open_spread_alert', '优惠价格提醒', 'risk',
 '💰 优惠价格机会提醒',
 '**价格优势通知**\n当前价格差异：{spread}元/件\n优惠阈值：{threshold}元/件\n\n建议操作：接收优惠订单\n预计收益：{estimated_profit}元\n\n这是一个不错的价格机会！',
 true, 3),

('forward_close_spread_alert', '价格回归提醒', 'risk',
 '📊 价格回归通知',
 '**价格变化提醒**\n当前价格差异：{spread}元/件\n回归阈值：{threshold}元/件\n\n建议操作：完成订单配送\n当前收益：{current_profit}元\n\n价格已回归正常区间',
 true, 3),

('reverse_open_spread_alert', '反向优惠提醒', 'risk',
 '💎 反向优惠机会',
 '**反向价格优势**\n当前价格差异：{spread}元/件\n优惠阈值：{threshold}元/件\n\n建议操作：接收反向订单\n预计收益：{estimated_profit}元\n\n反向配送优惠机会出现！',
 true, 3),

('reverse_close_spread_alert', '反向价格回归', 'risk',
 '📈 反向价格回归',
 '**反向价格变化**\n当前价格差异：{spread}元/件\n回归阈值：{threshold}元/件\n\n建议操作：完成反向配送\n当前收益：{current_profit}元\n\n反向价格已回归正常',
 true, 3),

-- MT5连接状态提醒（生鲜配送语：配送系统延迟）
('mt5_lag_alert', '配送系统延迟', 'risk',
 '⚠️ 配送系统延迟提醒',
 '**系统响应异常**\n配送系统出现延迟\n\n连接失败次数：{failure_count}次\n最后响应时间：{last_response_time}\n\n请检查系统连接状态，必要时重启配送系统',
 true, 4),

-- 净资产提醒（生鲜配送语：仓库资产提醒）
('binance_net_asset_alert', 'A仓库资产提醒', 'risk',
 '💰 A仓库资产预警',
 '**资产状况提醒**\n当前A仓库净资产：{current_asset}元\n预警阈值：{threshold}元\n\n资产已{status}预警线\n请及时关注资产变化',
 true, 3),

('bybit_net_asset_alert', 'B仓库资产提醒', 'risk',
 '💰 B仓库资产预警',
 '**资产状况提醒**\n当前B仓库净资产：{current_asset}元\n预警阈值：{threshold}元\n\n资产已{status}预警线\n请及时关注资产变化',
 true, 3),

-- 爆仓价提醒（生鲜配送语：安全线价格提醒）
('binance_liquidation_alert', 'A仓库安全线提醒', 'risk',
 '🚨 A仓库安全线预警',
 '**价格安全提醒**\n当前价格：{current_price}元\n安全线价格：{liquidation_price}元\n距离安全线：{distance}元\n\n{status}\n请密切关注价格变化，必要时调整仓位',
 true, 4),

('bybit_liquidation_alert', 'B仓库安全线提醒', 'risk',
 '🚨 B仓库安全线预警',
 '**价格安全提醒**\n当前价格：{current_price}元\n安全线价格：{liquidation_price}元\n距离安全线：{distance}元\n\n{status}\n请密切关注价格变化，必要时调整仓位',
 true, 4),

-- 单腿提醒（生鲜配送语：单边配送提醒）
('single_leg_alert', '单边配送提醒', 'risk',
 '⚡ 单边配送预警',
 '**配送不平衡提醒**\n{exchange}仓库出现单边配送\n\n单边数量：{quantity}件\n持续时间：{duration}秒\n配送方向：{direction}\n\n请尽快完成对冲配送，避免价格风险',
 true, 4),

-- 系统类通知
('system_maintenance', '系统维护通知', 'system',
 '🔧 系统维护通知',
 '**维护公告**\n维护时间：{maintenance_time}\n维护内容：{maintenance_content}\n预计恢复：{estimated_recovery}\n\n如有疑问请联系客服',
 true, 3),

('account_verified', '账户认证成功', 'system',
 '✅ 账户认证成功',
 '**认证通过**\n恭喜您，账户认证已通过！\n\n账户名称：{account_name}\n认证时间：{verify_time}\n\n您现在可以开始使用配送服务',
 true, 2),

('order_cancelled', '订单已取消', 'trading',
 '❌ 订单已取消',
 '**取消通知**\n订单编号：{order_id}\n取消原因：{reason}\n取消时间：{cancel_time}\n\n如有疑问请联系客服',
 true, 2)

ON CONFLICT (template_key) DO NOTHING;

-- ============================================================================
-- 6. 创建用户通知设置表（可选）
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_notification_settings (
    setting_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) UNIQUE NOT NULL,
    feishu_user_id VARCHAR(200),
    feishu_enabled BOOLEAN DEFAULT TRUE,
    email VARCHAR(200),
    email_enabled BOOLEAN DEFAULT FALSE,
    phone VARCHAR(50),
    sms_enabled BOOLEAN DEFAULT FALSE,
    enable_trade_notifications BOOLEAN DEFAULT TRUE,
    enable_risk_notifications BOOLEAN DEFAULT TRUE,
    enable_system_notifications BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

COMMENT ON TABLE user_notification_settings IS '用户通知偏好设置';

CREATE INDEX idx_user_notification_settings_user ON user_notification_settings(user_id);

-- ============================================================================
-- 7. 验证数据
-- ============================================================================
SELECT 'notification_configs' as table_name, COUNT(*) as count FROM notification_configs
UNION ALL
SELECT 'notification_templates', COUNT(*) FROM notification_templates
UNION ALL
SELECT 'notification_logs', COUNT(*) FROM notification_logs;
