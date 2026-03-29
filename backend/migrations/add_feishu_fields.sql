-- Add Feishu fields to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS feishu_open_id VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS feishu_mobile VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS feishu_union_id VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_users_feishu_open_id ON users(feishu_open_id);

UPDATE users SET feishu_open_id = 'ou_613cc2eabae277733bdee67edb3d8cc5', feishu_mobile = '+8613957717158', feishu_union_id = 'on_6b14703ea5d68e82f990f07c58bae466' WHERE username = 'admin';
