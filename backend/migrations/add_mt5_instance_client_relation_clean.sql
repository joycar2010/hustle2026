-- 添加 client_id 外键列
ALTER TABLE mt5_instances
ADD COLUMN client_id INTEGER REFERENCES mt5_clients(client_id) ON DELETE CASCADE;

-- 添加 instance_type 列
ALTER TABLE mt5_instances
ADD COLUMN instance_type VARCHAR(20) NOT NULL DEFAULT 'primary';

-- 添加约束：instance_type 只能是 primary 或 backup
ALTER TABLE mt5_instances
ADD CONSTRAINT check_instance_type CHECK (instance_type IN ('primary', 'backup'));

-- 修改 is_active 默认值为 false
ALTER TABLE mt5_instances
ALTER COLUMN is_active SET DEFAULT FALSE;

-- 创建索引提高查询性能
CREATE INDEX idx_mt5_instances_client_id ON mt5_instances(client_id);
CREATE INDEX idx_mt5_instances_type ON mt5_instances(instance_type);
CREATE INDEX idx_mt5_instances_active ON mt5_instances(is_active);

-- 创建唯一索引：同一客户端的同一类型实例只能有一个
CREATE UNIQUE INDEX idx_mt5_instances_client_type ON mt5_instances(client_id, instance_type)
WHERE client_id IS NOT NULL;

-- 添加注释
COMMENT ON COLUMN mt5_instances.client_id IS '关联的MT5客户端';
COMMENT ON COLUMN mt5_instances.instance_type IS '实例类型: primary/backup';
COMMENT ON COLUMN mt5_instances.is_active IS '是否启用（同一客户端只能有一个启用）';
