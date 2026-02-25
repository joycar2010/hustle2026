-- 插入系统安全组件配置
-- 执行时间: 2026-02-25

-- 清空现有数据（可选，仅用于重新初始化）
-- TRUNCATE TABLE security_components CASCADE;

-- 1. JWT Token 认证 (已实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'jwt_auth',
    'JWT Token 认证',
    'middleware',
    'JSON Web Token 身份认证机制，用于API请求的用户身份验证',
    TRUE,
    '{"algorithm": "HS256", "expire_minutes": 30, "refresh_expire_days": 7}'::jsonb,
    100,
    'active'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 2. 密码 bcrypt 哈希 (已实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'bcrypt_hash',
    '密码 Bcrypt 哈希',
    'service',
    '使用 bcrypt 算法对用户密码进行安全哈希存储',
    TRUE,
    '{"rounds": 12, "salt_rounds": 12}'::jsonb,
    95,
    'active'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 3. API 密钥加密存储 (已实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'api_key_encryption',
    'API 密钥加密存储',
    'service',
    '对交易所 API 密钥进行加密存储，使用 AES-256 加密算法',
    TRUE,
    '{"algorithm": "AES-256-GCM", "key_rotation_days": 90}'::jsonb,
    90,
    'active'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 4. CORS 跨域限制 (已实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'cors_protection',
    'CORS 跨域保护',
    'middleware',
    '限制跨域请求来源，防止未授权的跨域访问',
    TRUE,
    '{"allowed_origins": ["http://localhost:3000", "http://13.115.21.77:3000"], "allow_credentials": true, "max_age": 3600}'::jsonb,
    85,
    'active'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 5. 速率限制 (已实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'rate_limiting',
    '速率限制',
    'middleware',
    'API 请求速率限制，防止暴力攻击和资源滥用',
    TRUE,
    '{"requests_per_minute": 100, "burst": 20, "by_ip": true}'::jsonb,
    80,
    'active'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 6. 输入验证 (已实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'input_validation',
    'Pydantic 输入验证',
    'service',
    '使用 Pydantic 进行请求数据验证和类型检查',
    TRUE,
    '{"strict_mode": true, "validate_assignment": true}'::jsonb,
    75,
    'active'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 7. 密钥管理机制 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'key_management',
    '密钥管理机制',
    'service',
    '集中管理系统密钥，支持密钥轮换和版本控制',
    FALSE,
    '{"rotation_enabled": false, "rotation_days": 90, "key_versions": 3}'::jsonb,
    70,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 8. SQL 查询安全审计 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'sql_audit',
    'SQL 查询安全审计',
    'protection',
    '审计和监控 SQL 查询，防止 SQL 注入攻击',
    FALSE,
    '{"log_queries": false, "detect_injection": true, "alert_threshold": 5}'::jsonb,
    65,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 9. CSRF 保护 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'csrf_protection',
    'CSRF 跨站请求伪造保护',
    'middleware',
    '防止跨站请求伪造攻击，验证请求来源',
    FALSE,
    '{"token_length": 32, "expire_minutes": 60, "cookie_secure": true}'::jsonb,
    60,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 10. WebSocket 认证 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'websocket_auth',
    'WebSocket 连接认证',
    'middleware',
    'WebSocket 连接的身份验证和授权机制',
    FALSE,
    '{"require_token": true, "heartbeat_interval": 30, "max_connections_per_user": 5}'::jsonb,
    55,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 11. 请求签名机制 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'request_signing',
    '请求签名验证',
    'middleware',
    'API 请求签名机制，防止请求篡改和重放攻击',
    FALSE,
    '{"algorithm": "HMAC-SHA256", "timestamp_tolerance": 300, "nonce_required": true}'::jsonb,
    50,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 12. 日志脱敏 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'log_sanitization',
    '日志脱敏处理',
    'service',
    '自动脱敏日志中的敏感信息（密码、密钥、个人信息等）',
    FALSE,
    '{"mask_patterns": ["password", "api_key", "secret", "token"], "mask_char": "*"}'::jsonb,
    45,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 13. IP 白名单 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'ip_whitelist',
    'IP 白名单控制',
    'protection',
    '限制只允许白名单内的 IP 地址访问敏感接口',
    FALSE,
    '{"whitelist": [], "enabled_paths": ["/api/v1/admin/*"], "block_mode": "deny"}'::jsonb,
    40,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 14. 请求追踪 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'request_tracking',
    '请求追踪系统',
    'middleware',
    '为每个请求生成唯一 ID，追踪请求链路和性能',
    FALSE,
    '{"header_name": "X-Request-ID", "log_requests": true, "track_performance": true}'::jsonb,
    35,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 15. 依赖扫描 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'dependency_scan',
    '依赖安全扫描',
    'service',
    '定期扫描项目依赖的安全漏洞',
    FALSE,
    '{"scan_interval_days": 7, "auto_update": false, "alert_on_vulnerability": true}'::jsonb,
    30,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 16. 备份恢复 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'backup_recovery',
    '数据备份恢复',
    'service',
    '自动备份数据库和关键配置文件，支持快速恢复',
    FALSE,
    '{"backup_interval_hours": 24, "retention_days": 30, "backup_location": "/backups", "encrypt_backup": true}'::jsonb,
    25,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 17. SECRET_KEY 管理 (待实现)
INSERT INTO security_components (
    component_code, component_name, component_type, description,
    is_enabled, config_json, priority, status
) VALUES (
    'secret_key_rotation',
    'SECRET_KEY 轮换',
    'service',
    '定期更换系统 SECRET_KEY，增强安全性',
    FALSE,
    '{"current_key_age_days": 0, "rotation_interval_days": 90, "key_strength": 256}'::jsonb,
    20,
    'inactive'
) ON CONFLICT (component_code) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    config_json = EXCLUDED.config_json,
    status = EXCLUDED.status;

-- 更新统计信息
SELECT
    COUNT(*) as total_components,
    SUM(CASE WHEN is_enabled THEN 1 ELSE 0 END) as enabled_components,
    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_components
FROM security_components;
