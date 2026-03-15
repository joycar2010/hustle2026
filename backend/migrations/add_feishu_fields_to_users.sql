-- 为用户表添加飞书相关字段
-- 执行时间: 2026-03-05

-- 添加飞书open_id字段
ALTER TABLE users ADD COLUMN IF NOT EXISTS feishu_open_id VARCHAR(100);

-- 添加飞书手机号字段（可能与主手机号不同）
ALTER TABLE users ADD COLUMN IF NOT EXISTS feishu_mobile VARCHAR(20);

-- 添加飞书union_id字段（用于跨应用识别用户）
ALTER TABLE users ADD COLUMN IF NOT EXISTS feishu_union_id VARCHAR(100);

-- 为飞书open_id创建索引，提高查询效率
CREATE INDEX IF NOT EXISTS idx_users_feishu_open_id ON users(feishu_open_id);

-- 为admin用户添加飞书信息（根据之前查询到的信息）
UPDATE users
SET
    feishu_open_id = 'ou_613cc2eabae277733bdee67edb3d8cc5',
    feishu_mobile = '+8613957717158',
    feishu_union_id = 'on_6b14703ea5d68e82f990f07c58bae466'
WHERE username = 'admin';

-- 添加注释
COMMENT ON COLUMN users.feishu_open_id IS '飞书Open ID，用于发送飞书通知';
COMMENT ON COLUMN users.feishu_mobile IS '飞书绑定的手机号';
COMMENT ON COLUMN users.feishu_union_id IS '飞书Union ID，跨应用唯一标识';
