-- 修改 email 字段为可空，并移除唯一约束
-- 注意：如果有唯一约束的名称，需要先删除

-- 删除 email 字段的唯一约束（如果存在）
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'users_email_key'
    ) THEN
        ALTER TABLE users DROP CONSTRAINT users_email_key;
    END IF;
END $$;

-- 修改 email 字段为可空
ALTER TABLE users ALTER COLUMN email DROP NOT NULL;

-- 为空的 email 字段设置默认值（可选）
-- UPDATE users SET email = NULL WHERE email = '';
