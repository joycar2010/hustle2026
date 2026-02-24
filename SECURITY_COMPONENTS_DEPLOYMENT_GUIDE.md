# 安全组件管理模块 - 快速部署指南

**更新时间**: 2026-02-24
**模块**: 安全组件管理API

---

## ✅ 已完成的新增文件

### 1. API路由
- `backend/app/api/v1/security_components.py` - 安全组件管理API（7个接口）

### 2. Pydantic Schemas
- `backend/app/schemas/security.py` - 安全组件相关数据验证模型

### 3. 初始化脚本
- `scripts/init_security_components.py` - 初始化12个预定义安全组件

---

## 🚀 立即部署步骤

### 第一步：注册API路由

编辑 `backend/app/main.py`，添加安全组件路由：

```python
from app.api.v1 import security_components  # 添加导入

# 在现有路由后添加
app.include_router(
    security_components.router,
    prefix="/api/v1/security",
    tags=["安全组件管理"]
)
```

### 第二步：初始化安全组件数据

```bash
cd /var/www/hustle
python scripts/init_security_components.py
```

**预定义的12个安全组件**：

| 组件代码 | 组件名称 | 类型 | 默认状态 | 优先级 |
|---------|---------|------|---------|--------|
| csrf_protection | CSRF保护 | middleware | 禁用 | 90 |
| request_signature | 请求签名验证 | middleware | 禁用 | 85 |
| ip_whitelist | IP白名单 | middleware | 禁用 | 95 |
| rate_limiting | API速率限制 | middleware | **启用** | 80 |
| log_sanitizer | 日志脱敏 | service | **启用** | 100 |
| encryption_service | 数据加密服务 | service | **启用** | 100 |
| sql_injection_protection | SQL注入防护 | protection | **启用** | 100 |
| xss_protection | XSS防护 | protection | **启用** | 90 |
| brute_force_protection | 暴力破解防护 | protection | **启用** | 95 |
| session_management | 会话管理 | service | **启用** | 85 |
| audit_logging | 审计日志 | service | **启用** | 75 |
| websocket_auth | WebSocket认证 | middleware | **启用** | 100 |

### 第三步：启动服务

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 📡 API接口测试

### 1. 获取安全组件列表

```bash
curl -X GET "http://localhost:8000/api/v1/security/components" \
  -H "Authorization: Bearer <your_token>"
```

**响应示例**：
```json
[
  {
    "component_id": "uuid",
    "component_code": "csrf_protection",
    "component_name": "CSRF保护",
    "component_type": "middleware",
    "description": "防止跨站请求伪造攻击",
    "is_enabled": false,
    "config_json": {
      "enabled_methods": ["POST", "PUT", "DELETE"],
      "token_header": "X-CSRF-Token"
    },
    "priority": 90,
    "status": "inactive",
    "created_at": "2026-02-24T10:00:00Z"
  }
]
```

### 2. 获取组件详情

```bash
curl -X GET "http://localhost:8000/api/v1/security/components/{component_id}" \
  -H "Authorization: Bearer <your_token>"
```

### 3. 启用安全组件

```bash
curl -X POST "http://localhost:8000/api/v1/security/components/{component_id}/enable" \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "force": false
  }'
```

**响应示例**：
```json
{
  "message": "安全组件已启用",
  "component_code": "csrf_protection"
}
```

### 4. 禁用安全组件

```bash
curl -X POST "http://localhost:8000/api/v1/security/components/{component_id}/disable" \
  -H "Authorization: Bearer <your_token>"
```

### 5. 更新组件配置

```bash
curl -X PUT "http://localhost:8000/api/v1/security/components/{component_id}/config" \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "config_json": {
      "enabled_methods": ["POST", "PUT", "DELETE", "PATCH"],
      "token_header": "X-CSRF-Token",
      "token_expiry": 7200
    },
    "priority": 95
  }'
```

### 6. 获取组件运行状态

```bash
curl -X GET "http://localhost:8000/api/v1/security/components/{component_id}/status" \
  -H "Authorization: Bearer <your_token>"
```

**响应示例**：
```json
{
  "component_id": "uuid",
  "component_code": "csrf_protection",
  "component_name": "CSRF保护",
  "is_enabled": true,
  "status": "active",
  "last_check_at": "2026-02-24T10:30:00Z",
  "error_message": null,
  "cached_status": {
    "is_enabled": true,
    "status": "active",
    "config": {...}
  }
}
```

### 7. 获取操作日志

```bash
curl -X GET "http://localhost:8000/api/v1/security/components/{component_id}/logs?limit=20" \
  -H "Authorization: Bearer <your_token>"
```

**响应示例**：
```json
[
  {
    "log_id": "uuid",
    "component_id": "uuid",
    "action": "enable",
    "old_config": {...},
    "new_config": {...},
    "result": "success",
    "error_message": null,
    "performed_by": "user_uuid",
    "performed_at": "2026-02-24T10:30:00Z",
    "ip_address": "192.168.1.100"
  }
]
```

---

## 🔍 功能验证

### 1. 验证组件初始化

```bash
# 查看数据库中的组件
psql -h localhost -U hustle_user -d hustle_db -c "SELECT component_code, component_name, is_enabled, status FROM security_components ORDER BY priority DESC;"
```

### 2. 验证Redis缓存

```bash
# 启用一个组件后，检查Redis缓存
redis-cli GET "security_component:csrf_protection"
```

### 3. 验证操作日志

```sql
-- 查看最近的操作日志
SELECT
    sc.component_name,
    scl.action,
    scl.result,
    scl.performed_at,
    scl.ip_address
FROM security_component_logs scl
JOIN security_components sc ON scl.component_id = sc.component_id
ORDER BY scl.performed_at DESC
LIMIT 10;
```

---

## 📊 API接口清单

| 方法 | 路径 | 功能 | 权限要求 |
|------|------|------|----------|
| GET | `/api/v1/security/components` | 获取组件列表 | security:list |
| GET | `/api/v1/security/components/{id}` | 获取组件详情 | security:detail |
| POST | `/api/v1/security/components/{id}/enable` | 启用组件 | security:enable |
| POST | `/api/v1/security/components/{id}/disable` | 禁用组件 | security:disable |
| PUT | `/api/v1/security/components/{id}/config` | 更新配置 | security:config |
| GET | `/api/v1/security/components/{id}/status` | 获取状态 | security:status |
| GET | `/api/v1/security/components/{id}/logs` | 获取日志 | security:logs |

---

## 🎯 使用场景

### 场景1：启用CSRF保护

```bash
# 1. 获取CSRF组件ID
curl -X GET "http://localhost:8000/api/v1/security/components?component_type=middleware" \
  -H "Authorization: Bearer <token>" | jq '.[] | select(.component_code=="csrf_protection")'

# 2. 启用CSRF保护
curl -X POST "http://localhost:8000/api/v1/security/components/{csrf_component_id}/enable" \
  -H "Authorization: Bearer <token>" \
  -d '{"force": false}'

# 3. 验证状态
curl -X GET "http://localhost:8000/api/v1/security/components/{csrf_component_id}/status" \
  -H "Authorization: Bearer <token>"
```

### 场景2：配置IP白名单

```bash
# 1. 更新IP白名单配置
curl -X PUT "http://localhost:8000/api/v1/security/components/{ip_whitelist_id}/config" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "config_json": {
      "whitelist": ["127.0.0.1", "192.168.1.0/24", "10.0.0.100"],
      "protected_paths": ["/api/v1/users", "/api/v1/system"],
      "enabled": true
    }
  }'

# 2. 启用IP白名单
curl -X POST "http://localhost:8000/api/v1/security/components/{ip_whitelist_id}/enable" \
  -H "Authorization: Bearer <token>"
```

### 场景3：调整速率限制

```bash
# 更新速率限制配置
curl -X PUT "http://localhost:8000/api/v1/security/components/{rate_limiting_id}/config" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "config_json": {
      "default_limit": "200/minute",
      "auth_limit": "20/minute",
      "trading_limit": "100/minute",
      "burst_size": 20
    }
  }'
```

---

## ⚠️ 注意事项

1. **组件依赖关系**
   - 某些组件可能依赖其他组件
   - 启用前检查依赖是否满足

2. **配置验证**
   - 更新配置前验证JSON格式
   - 确保配置参数符合组件要求

3. **操作审计**
   - 所有启用/禁用/配置操作都会记录日志
   - 包含操作人、IP地址、时间戳

4. **Redis缓存**
   - 组件状态缓存5分钟
   - 修改后自动更新缓存

5. **优先级**
   - 数值越大优先级越高
   - 中间件按优先级顺序执行

---

## 🐛 故障排查

### 问题1: 组件启用失败

```bash
# 查看组件详情
curl -X GET "http://localhost:8000/api/v1/security/components/{component_id}" \
  -H "Authorization: Bearer <token>"

# 查看错误日志
curl -X GET "http://localhost:8000/api/v1/security/components/{component_id}/logs?action=enable" \
  -H "Authorization: Bearer <token>"
```

### 问题2: 配置更新不生效

```bash
# 清除Redis缓存
redis-cli DEL "security_component:{component_code}"

# 重新获取状态
curl -X GET "http://localhost:8000/api/v1/security/components/{component_id}/status" \
  -H "Authorization: Bearer <token>"
```

### 问题3: 组件状态异常

```sql
-- 检查数据库状态
SELECT component_code, is_enabled, status, error_message, last_check_at
FROM security_components
WHERE status = 'error';

-- 重置组件状态
UPDATE security_components
SET status = 'inactive', error_message = NULL
WHERE component_id = 'uuid';
```

---

## 📈 下一步

1. **实施SSL证书管理API** - 管理HTTPS证书
2. **实施权限拦截中间件** - 自动权限验证
3. **开发前端管理页面** - Vue3可视化管理界面

---

**部署状态**: ✅ 安全组件API已就绪，可立即使用
**测试建议**: 先测试组件列表和状态查询，再测试启用/禁用功能
