# 快速部署指南 - RBAC权限管理模块

**更新时间**: 2026-02-24
**模块**: RBAC权限管理API

---

## ✅ 已完成的新增文件

### 1. API路由
- `backend/app/api/v1/rbac.py` - RBAC权限管理API（18个接口）

### 2. Pydantic Schemas
- `backend/app/schemas/rbac.py` - RBAC相关数据验证模型

---

## 🚀 立即部署步骤

### 第一步：注册API路由

编辑 `backend/app/main.py`，添加RBAC路由：

```python
from app.api.v1 import rbac  # 添加导入

# 在现有路由后添加
app.include_router(rbac.router, prefix="/api/v1/rbac", tags=["RBAC权限管理"])
```

### 第二步：执行数据库迁移

```bash
psql -h localhost -U hustle_user -d hustle_db -f database/migrations/create_rbac_security_tables.sql
```

### 第三步：启动Redis

```bash
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

### 第四步：配置环境变量

编辑 `backend/.env`：

```bash
# Redis配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# 已有的配置保持不变
SECRET_KEY=<your_secret_key>
ENCRYPTION_KEY=<your_encryption_key>
```

### 第五步：启动后端服务

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 📡 API接口测试

### 1. 获取角色列表

```bash
curl -X GET "http://localhost:8000/api/v1/rbac/roles" \
  -H "Authorization: Bearer <your_token>"
```

### 2. 创建角色

```bash
curl -X POST "http://localhost:8000/api/v1/rbac/roles" \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "role_name": "测试角色",
    "role_code": "test_role",
    "description": "这是一个测试角色",
    "is_active": true
  }'
```

### 3. 获取权限列表

```bash
curl -X GET "http://localhost:8000/api/v1/rbac/permissions" \
  -H "Authorization: Bearer <your_token>"
```

### 4. 为角色分配权限

```bash
curl -X POST "http://localhost:8000/api/v1/rbac/roles/{role_id}/permissions" \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "permission_ids": [
      "permission_id_1",
      "permission_id_2"
    ]
  }'
```

### 5. 为用户分配角色

```bash
curl -X POST "http://localhost:8000/api/v1/rbac/users/{user_id}/roles" \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "role_ids": ["role_id_1", "role_id_2"],
    "expires_at": null
  }'
```

### 6. 获取用户权限

```bash
curl -X GET "http://localhost:8000/api/v1/rbac/users/{user_id}/permissions" \
  -H "Authorization: Bearer <your_token>"
```

### 7. 复制角色

```bash
curl -X POST "http://localhost:8000/api/v1/rbac/roles/{role_id}/copy" \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "new_role_name": "新角色名称",
    "new_role_code": "new_role_code",
    "copy_permissions": true
  }'
```

---

## 🔍 功能验证

### 1. 验证Redis缓存

```python
# 测试脚本
import asyncio
from app.services.permission_cache import permission_cache

async def test_cache():
    await permission_cache.connect()

    # 设置用户权限
    await permission_cache.set_user_permissions(
        "test_user_id",
        {"user:list", "user:create", "user:update"}
    )

    # 获取用户权限
    perms = await permission_cache.get_user_permissions("test_user_id")
    print(f"用户权限: {perms}")

    # 检查权限
    has_perm = await permission_cache.has_permission("test_user_id", "user:list")
    print(f"拥有 user:list 权限: {has_perm}")

    await permission_cache.close()

asyncio.run(test_cache())
```

### 2. 验证数据库

```sql
-- 查看系统角色
SELECT * FROM roles WHERE is_system = true;

-- 查看系统权限
SELECT * FROM permissions ORDER BY resource_type, permission_code;

-- 查看角色权限关联
SELECT r.role_name, p.permission_name
FROM roles r
JOIN role_permissions rp ON r.role_id = rp.role_id
JOIN permissions p ON rp.permission_id = p.permission_id;
```

---

## 📊 API接口清单

| 方法 | 路径 | 功能 | 权限要求 |
|------|------|------|----------|
| GET | `/api/v1/rbac/roles` | 获取角色列表 | role:list |
| GET | `/api/v1/rbac/roles/{id}` | 获取角色详情 | role:detail |
| POST | `/api/v1/rbac/roles` | 创建角色 | role:create |
| PUT | `/api/v1/rbac/roles/{id}` | 更新角色 | role:update |
| DELETE | `/api/v1/rbac/roles/{id}` | 删除角色 | role:delete |
| POST | `/api/v1/rbac/roles/{id}/copy` | 复制角色 | role:copy |
| GET | `/api/v1/rbac/permissions` | 获取权限列表 | permission:list |
| POST | `/api/v1/rbac/roles/{id}/permissions` | 分配角色权限 | role:assign_permission |
| POST | `/api/v1/rbac/users/{id}/roles` | 分配用户角色 | user:assign_role |
| GET | `/api/v1/rbac/users/{id}/permissions` | 获取用户权限 | user:permissions |

---

## ⚠️ 注意事项

1. **系统角色保护**
   - 系统内置角色（is_system=true）不可修改和删除
   - 包括：super_admin, system_admin, security_admin, trader, observer

2. **权限缓存**
   - 用户权限缓存：1小时
   - 角色权限缓存：24小时
   - 修改权限后会自动清除相关缓存

3. **角色删除限制**
   - 正在被用户使用的角色无法删除
   - 删除前需先解除用户关联

4. **批量操作**
   - 分配权限和角色都支持批量操作
   - 会先删除现有关联，再添加新关联

---

## 🐛 故障排查

### 问题1: Redis连接失败

```bash
# 检查Redis状态
sudo systemctl status redis-server

# 测试Redis连接
redis-cli ping

# 查看Redis日志
sudo tail -f /var/log/redis/redis-server.log
```

### 问题2: 权限缓存不生效

```bash
# 清空Redis缓存
redis-cli FLUSHDB

# 重启应用
sudo systemctl restart hustle-backend
```

### 问题3: 数据库连接错误

```bash
# 检查PostgreSQL状态
sudo systemctl status postgresql

# 测试数据库连接
psql -h localhost -U hustle_user -d hustle_db -c "SELECT 1"
```

---

## 📈 下一步

1. **实施权限中间件** - 自动拦截未授权请求
2. **实施安全组件API** - 管理安全组件配置
3. **实施SSL证书API** - 管理SSL证书
4. **开发前端页面** - Vue3权限管理界面

---

**部署状态**: ✅ RBAC API已就绪，可立即使用
**测试建议**: 先使用Postman/curl测试所有接口，确认功能正常后再开发前端
