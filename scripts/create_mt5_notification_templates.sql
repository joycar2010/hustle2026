-- 创建 MT5 监控通知模板
-- 用于健康监控系统发送警报

-- 检查模板是否已存在，如果存在则更新，否则插入
DO $$
BEGIN
    -- MT5 客户端错误模板（严重故障）
    IF NOT EXISTS (SELECT 1 FROM notification_templates WHERE template_key = 'mt5_client_error') THEN
        INSERT INTO notification_templates (
            template_key, template_name, category,
            title_template, content_template,
            enable_email, enable_sms, enable_feishu,
            priority, cooldown_seconds,
            is_active, created_at, updated_at
        ) VALUES (
            'mt5_client_error',
            'MT5 客户端错误',
            'system',
            '🚨 {title}',
            '{content}',
            false, false, true,
            4, 300,
            true, NOW(), NOW()
        );
        RAISE NOTICE 'Created template: mt5_client_error';
    ELSE
        UPDATE notification_templates
        SET
            template_name = 'MT5 客户端错误',
            category = 'system',
            title_template = '🚨 {title}',
            content_template = '{content}',
            enable_feishu = true,
            priority = 4,
            cooldown_seconds = 300,
            is_active = true,
            updated_at = NOW()
        WHERE template_key = 'mt5_client_error';
        RAISE NOTICE 'Updated template: mt5_client_error';
    END IF;

    -- MT5 客户端警告模板（一般异常）
    IF NOT EXISTS (SELECT 1 FROM notification_templates WHERE template_key = 'mt5_client_warning') THEN
        INSERT INTO notification_templates (
            template_key, template_name, category,
            title_template, content_template,
            enable_email, enable_sms, enable_feishu,
            priority, cooldown_seconds,
            is_active, created_at, updated_at
        ) VALUES (
            'mt5_client_warning',
            'MT5 客户端警告',
            'system',
            '⚠️ {title}',
            '{content}',
            false, false, true,
            3, 600,
            true, NOW(), NOW()
        );
        RAISE NOTICE 'Created template: mt5_client_warning';
    ELSE
        UPDATE notification_templates
        SET
            template_name = 'MT5 客户端警告',
            category = 'system',
            title_template = '⚠️ {title}',
            content_template = '{content}',
            enable_feishu = true,
            priority = 3,
            cooldown_seconds = 600,
            is_active = true,
            updated_at = NOW()
        WHERE template_key = 'mt5_client_warning';
        RAISE NOTICE 'Updated template: mt5_client_warning';
    END IF;

    -- MT5 客户端信息模板（恢复通知）
    IF NOT EXISTS (SELECT 1 FROM notification_templates WHERE template_key = 'mt5_client_info') THEN
        INSERT INTO notification_templates (
            template_key, template_name, category,
            title_template, content_template,
            enable_email, enable_sms, enable_feishu,
            priority, cooldown_seconds,
            is_active, created_at, updated_at
        ) VALUES (
            'mt5_client_info',
            'MT5 客户端信息',
            'system',
            'ℹ️ {title}',
            '{content}',
            false, false, true,
            2, 1800,
            true, NOW(), NOW()
        );
        RAISE NOTICE 'Created template: mt5_client_info';
    ELSE
        UPDATE notification_templates
        SET
            template_name = 'MT5 客户端信息',
            category = 'system',
            title_template = 'ℹ️ {title}',
            content_template = '{content}',
            enable_feishu = true,
            priority = 2,
            cooldown_seconds = 1800,
            is_active = true,
            updated_at = NOW()
        WHERE template_key = 'mt5_client_info';
        RAISE NOTICE 'Updated template: mt5_client_info';
    END IF;

END $$;

-- 查询创建的模板
SELECT
    template_key,
    template_name,
    category,
    priority,
    cooldown_seconds,
    enable_feishu,
    is_active
FROM notification_templates
WHERE template_key IN ('mt5_client_error', 'mt5_client_warning', 'mt5_client_info')
ORDER BY priority DESC;
