-- 飞书服务配置快速修复脚本
-- 执行此脚本可立即启用飞书服务

-- 更新或插入飞书配置
INSERT INTO notification_config (config_id, service_type, is_enabled, config_data, created_at, updated_at)
VALUES (
  '3ba11638-7585-4fc8-ad3c-e12ed070501a'::uuid,
  'feishu',
  true,
  '{"app_id": "cli_a9235819f078dcbd", "app_secret": "KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE"}'::jsonb,
  NOW(),
  NOW()
)
ON CONFLICT (service_type) DO UPDATE
SET
  is_enabled = true,
  config_data = '{"app_id": "cli_a9235819f078dcbd", "app_secret": "KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE"}'::jsonb,
  updated_at = NOW();

-- 验证配置
SELECT
  service_type,
  is_enabled,
  config_data,
  updated_at
FROM notification_config
WHERE service_type = 'feishu';
