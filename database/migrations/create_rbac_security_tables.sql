"""
RBAC权限管理、安全组件、SSL证书数据库表结构
执行顺序：按照文件中的顺序依次执行
"""

-- ============================================
-- 1. 角色表 (roles)
-- ============================================
CREATE TABLE IF NOT EXISTS roles (
    role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_name VARCHAR(50) NOT NULL UNIQUE,
    role_code VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    is_system BOOLEAN DEFAULT FALSE NOT NULL,  -- 系统内置角色不可删除
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by UUID REFERENCES users(user_id),
    updated_by UUID REFERENCES users(user_id)
);

CREATE INDEX idx_roles_code ON roles(role_code);
CREATE INDEX idx_roles_active ON roles(is_active);

COMMENT ON TABLE roles IS 'RBAC角色表';
COMMENT ON COLUMN roles.role_code IS '角色代码，用于程序判断';
COMMENT ON COLUMN roles.is_system IS '系统内置角色标识';

-- ============================================
-- 2. 权限表 (permissions)
-- ============================================
CREATE TABLE IF NOT EXISTS permissions (
    permission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    permission_name VARCHAR(100) NOT NULL,
    permission_code VARCHAR(100) NOT NULL UNIQUE,
    resource_type VARCHAR(50) NOT NULL,  -- api, menu, button
    resource_path VARCHAR(255),  -- API路径或菜单路径
    http_method VARCHAR(10),  -- GET, POST, PUT, DELETE
    description TEXT,
    parent_id UUID REFERENCES permissions(permission_id),
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX idx_permissions_code ON permissions(permission_code);
CREATE INDEX idx_permissions_type ON permissions(resource_type);
CREATE INDEX idx_permissions_parent ON permissions(parent_id);

COMMENT ON TABLE permissions IS 'RBAC权限表';
COMMENT ON COLUMN permissions.resource_type IS '资源类型：api-接口权限, menu-菜单权限, button-按钮权限';
COMMENT ON COLUMN permissions.resource_path IS 'API路径或菜单路径';

-- ============================================
-- 3. 用户-角色关联表 (user_roles)
-- ============================================
CREATE TABLE IF NOT EXISTS user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    assigned_by UUID REFERENCES users(user_id),
    expires_at TIMESTAMP,  -- 角色过期时间，NULL表示永久
    UNIQUE(user_id, role_id)
);

CREATE INDEX idx_user_roles_user ON user_roles(user_id);
CREATE INDEX idx_user_roles_role ON user_roles(role_id);

COMMENT ON TABLE user_roles IS '用户-角色关联表';
COMMENT ON COLUMN user_roles.expires_at IS '角色过期时间，NULL表示永久有效';

-- ============================================
-- 4. 角色-权限关联表 (role_permissions)
-- ============================================
CREATE TABLE IF NOT EXISTS role_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(permission_id) ON DELETE CASCADE,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    granted_by UUID REFERENCES users(user_id),
    UNIQUE(role_id, permission_id)
);

CREATE INDEX idx_role_permissions_role ON role_permissions(role_id);
CREATE INDEX idx_role_permissions_permission ON role_permissions(permission_id);

COMMENT ON TABLE role_permissions IS '角色-权限关联表';

-- ============================================
-- 5. 安全组件配置表 (security_components)
-- ============================================
CREATE TABLE IF NOT EXISTS security_components (
    component_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    component_code VARCHAR(50) NOT NULL UNIQUE,
    component_name VARCHAR(100) NOT NULL,
    component_type VARCHAR(50) NOT NULL,  -- middleware, service, protection
    description TEXT,
    is_enabled BOOLEAN DEFAULT FALSE NOT NULL,
    config_json JSONB,  -- 组件配置参数（JSON格式）
    priority INTEGER DEFAULT 0,  -- 执行优先级
    status VARCHAR(20) DEFAULT 'inactive',  -- active, inactive, error
    last_check_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by UUID REFERENCES users(user_id),
    updated_by UUID REFERENCES users(user_id)
);

CREATE INDEX idx_security_components_code ON security_components(component_code);
CREATE INDEX idx_security_components_enabled ON security_components(is_enabled);
CREATE INDEX idx_security_components_type ON security_components(component_type);

COMMENT ON TABLE security_components IS '安全组件配置表';
COMMENT ON COLUMN security_components.component_type IS '组件类型：middleware-中间件, service-服务, protection-防护';
COMMENT ON COLUMN security_components.config_json IS '组件配置参数（JSON格式）';
COMMENT ON COLUMN security_components.status IS '运行状态：active-运行中, inactive-未启用, error-异常';

-- ============================================
-- 6. 安全组件日志表 (security_component_logs)
-- ============================================
CREATE TABLE IF NOT EXISTS security_component_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    component_id UUID NOT NULL REFERENCES security_components(component_id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,  -- enable, disable, config_update, error
    old_config JSONB,
    new_config JSONB,
    result VARCHAR(20) NOT NULL,  -- success, failure
    error_message TEXT,
    performed_by UUID REFERENCES users(user_id),
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ip_address VARCHAR(45)
);

CREATE INDEX idx_security_logs_component ON security_component_logs(component_id);
CREATE INDEX idx_security_logs_action ON security_component_logs(action);
CREATE INDEX idx_security_logs_time ON security_component_logs(performed_at DESC);

COMMENT ON TABLE security_component_logs IS '安全组件操作日志表';

-- ============================================
-- 7. SSL证书表 (ssl_certificates)
-- ============================================
CREATE TABLE IF NOT EXISTS ssl_certificates (
    cert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cert_name VARCHAR(100) NOT NULL,
    domain_name VARCHAR(255) NOT NULL,
    cert_type VARCHAR(20) NOT NULL,  -- self_signed, ca_signed, letsencrypt
    cert_file_path VARCHAR(500),  -- 证书文件路径
    key_file_path VARCHAR(500),  -- 私钥文件路径
    chain_file_path VARCHAR(500),  -- 证书链文件路径
    issuer VARCHAR(255),  -- 颁发机构
    subject VARCHAR(255),  -- 证书主体
    serial_number VARCHAR(100),
    issued_at TIMESTAMP,  -- 颁发时间
    expires_at TIMESTAMP NOT NULL,  -- 过期时间
    status VARCHAR(20) DEFAULT 'inactive',  -- active, inactive, expired, expiring_soon
    is_deployed BOOLEAN DEFAULT FALSE,  -- 是否已部署
    auto_renew BOOLEAN DEFAULT FALSE,  -- 是否自动续期
    days_before_expiry INTEGER,  -- 距离过期天数
    last_check_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    uploaded_by UUID REFERENCES users(user_id),
    UNIQUE(domain_name, cert_type)
);

CREATE INDEX idx_ssl_certs_domain ON ssl_certificates(domain_name);
CREATE INDEX idx_ssl_certs_status ON ssl_certificates(status);
CREATE INDEX idx_ssl_certs_expires ON ssl_certificates(expires_at);

COMMENT ON TABLE ssl_certificates IS 'SSL证书管理表';
COMMENT ON COLUMN ssl_certificates.cert_type IS '证书类型：self_signed-自签名, ca_signed-CA签名, letsencrypt-Let''s Encrypt';
COMMENT ON COLUMN ssl_certificates.status IS '证书状态：active-生效中, inactive-未启用, expired-已过期, expiring_soon-即将过期';
COMMENT ON COLUMN ssl_certificates.days_before_expiry IS '距离过期天数，用于提醒';

-- ============================================
-- 8. SSL证书操作日志表 (ssl_certificate_logs)
-- ============================================
CREATE TABLE IF NOT EXISTS ssl_certificate_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cert_id UUID NOT NULL REFERENCES ssl_certificates(cert_id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,  -- upload, deploy, renew, revoke, delete
    result VARCHAR(20) NOT NULL,  -- success, failure
    error_message TEXT,
    performed_by UUID REFERENCES users(user_id),
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ip_address VARCHAR(45)
);

CREATE INDEX idx_ssl_logs_cert ON ssl_certificate_logs(cert_id);
CREATE INDEX idx_ssl_logs_action ON ssl_certificate_logs(action);
CREATE INDEX idx_ssl_logs_time ON ssl_certificate_logs(performed_at DESC);

COMMENT ON TABLE ssl_certificate_logs IS 'SSL证书操作日志表';

-- ============================================
-- 9. 初始化系统角色和权限
-- ============================================

-- 插入系统内置角色
INSERT INTO roles (role_name, role_code, description, is_system, is_active) VALUES
('超级管理员', 'super_admin', '系统超级管理员，拥有所有权限', TRUE, TRUE),
('系统管理员', 'system_admin', '系统管理员，负责系统配置和用户管理', TRUE, TRUE),
('安全管理员', 'security_admin', '安全管理员，负责安全组件和证书管理', TRUE, TRUE),
('交易员', 'trader', '交易员，负责交易操作', TRUE, TRUE),
('观察员', 'observer', '观察员，仅查看权限', TRUE, TRUE)
ON CONFLICT (role_code) DO NOTHING;

-- 插入系统权限（示例）
INSERT INTO permissions (permission_name, permission_code, resource_type, resource_path, http_method, description) VALUES
-- 用户管理权限
('用户列表', 'user:list', 'api', '/api/v1/users', 'GET', '查看用户列表'),
('用户详情', 'user:detail', 'api', '/api/v1/users/{id}', 'GET', '查看用户详情'),
('创建用户', 'user:create', 'api', '/api/v1/users', 'POST', '创建新用户'),
('编辑用户', 'user:update', 'api', '/api/v1/users/{id}', 'PUT', '编辑用户信息'),
('删除用户', 'user:delete', 'api', '/api/v1/users/{id}', 'DELETE', '删除用户'),

-- 角色管理权限
('角色列表', 'role:list', 'api', '/api/v1/roles', 'GET', '查看角色列表'),
('创建角色', 'role:create', 'api', '/api/v1/roles', 'POST', '创建新角色'),
('编辑角色', 'role:update', 'api', '/api/v1/roles/{id}', 'PUT', '编辑角色信息'),
('删除角色', 'role:delete', 'api', '/api/v1/roles/{id}', 'DELETE', '删除角色'),
('分配权限', 'role:assign_permission', 'api', '/api/v1/roles/{id}/permissions', 'POST', '为角色分配权限'),

-- 安全组件权限
('安全组件列表', 'security:list', 'api', '/api/v1/security/components', 'GET', '查看安全组件列表'),
('启用组件', 'security:enable', 'api', '/api/v1/security/components/{id}/enable', 'POST', '启用安全组件'),
('禁用组件', 'security:disable', 'api', '/api/v1/security/components/{id}/disable', 'POST', '禁用安全组件'),
('配置组件', 'security:config', 'api', '/api/v1/security/components/{id}/config', 'PUT', '配置安全组件'),

-- SSL证书权限
('证书列表', 'ssl:list', 'api', '/api/v1/ssl/certificates', 'GET', '查看SSL证书列表'),
('上传证书', 'ssl:upload', 'api', '/api/v1/ssl/certificates', 'POST', '上传SSL证书'),
('部署证书', 'ssl:deploy', 'api', '/api/v1/ssl/certificates/{id}/deploy', 'POST', '部署SSL证书'),
('删除证书', 'ssl:delete', 'api', '/api/v1/ssl/certificates/{id}', 'DELETE', '删除SSL证书'),

-- 交易权限
('交易列表', 'trading:list', 'api', '/api/v1/trading', 'GET', '查看交易列表'),
('执行交易', 'trading:execute', 'api', '/api/v1/trading/execute', 'POST', '执行交易操作')
ON CONFLICT (permission_code) DO NOTHING;

-- ============================================
-- 10. 更新触发器（自动更新 updated_at）
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_roles_updated_at BEFORE UPDATE ON roles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_permissions_updated_at BEFORE UPDATE ON permissions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_security_components_updated_at BEFORE UPDATE ON security_components
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_ssl_certificates_updated_at BEFORE UPDATE ON ssl_certificates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
