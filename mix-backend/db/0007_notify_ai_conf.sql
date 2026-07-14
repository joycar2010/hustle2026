-- AI 客服弹窗配置(通知中心新tab):重要通知经前端 AI 浮动球主动弹窗
ALTER TABLE notify_settings ADD COLUMN IF NOT EXISTS ai_conf jsonb NOT NULL DEFAULT '{}'::jsonb;
