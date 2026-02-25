# 系统管理模块完整文档

## 概述

本文档记录了 Hustle2026 交易系统中所有系统管理模块的功能、数据库表结构、API端点和实现状态。

---

## 1. 用户管理模块

### 1.1 功能列表
- ✅ 获取当前用户信息 (`GET /api/v1/users/me`)
- ✅ 更新当前用户信息 (`PUT /api/v1/users/me`)
- ✅ 获取所有用户列表 (`GET /api/v1/users/`)
- ✅ 创建新用户 (`POST /api/v1/users/`)
- ✅ 更新用户信息 (`PUT /api/v1/users/{user_id}`)
- ✅ 删除用户 (`DELETE /api/v1/users/{user_id}`)

### 1.2 数据库表
**表名**: `users`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| user_id | UUID | PK | 用户ID |
| username | String(50) | UNIQUE, NOT NULL | 用户名 |
| password_hash | String(256) | NOT NULL | 密码哈希 |
| email | String(100) | UNIQUE | 邮箱 |
| role | String(50) | NOT NULL, Default='交易员' | 角色（旧字段，兼容用） |
| is_active | Boolean | NOT NULL, Default=True | 是否激活 |
| create_time | TIMESTAMP | NOT NULL | 创建时间 |
| update_time | TIMESTAMP | NOT NULL | 更新时间 |

### 1.3 删除用户逻辑
删除用户时需要处理以下FK关系：

**直接删除的表**:
- `strategy_performance` (通过 strategies.id)
- `positions`
- `trades`
- `system_alerts`
- `security_component_logs`
- `ssl_certificate_logs`

**置NULL的字段**:
- `role_permissions.granted_by`
- `roles.created_by`, `roles.updated_by`
- `security_components.created_by`, `security_components.updated_by`
- `ssl_certificates.uploaded_by`
- `user_roles.assigned_by`

**ORM CASCADE自动处理**:
- `accounts`
- `strategies`
- `strategy_configs`
- `arbitrage_tasks`
- `risk_alerts`
- `risk_settings`
- `user_roles` (user_id FK)

---

## 2. RBAC权限管理模块

### 2.1 功能列表

#### 角色管理
- ✅ 获取角色列表 (`GET /api/v1/rbac/roles`)
- ✅ 获取角色详情 (`GET /api/v1/rbac/roles/{role_id}`)
- ✅ 创建角色 (`POST /api/v1/rbac/roles`)
- ✅ 更新角色 (`PUT /api/v1/rbac/roles/{role_id}`)
- ✅ 删除角色 (`DELETE /api/v1/rbac/roles/{role_id}`)
- ✅ 复制角色 (`POST /api/v1/rbac/roles/{role_id}/copy`)

#### 权限管理
- ✅ 获取权限列表 (`GET /api/v1/rbac/permissions`)
- ✅ 获取权限详情 (`GET /api/v1/rbac/permissions/{permission_id}`)
- ✅ 创建权限 (`POST /api/v1/rbac/permissions`)
- ✅ 更新权限 (`PUT /api/v1/rbac/permissions/{permission_id}`)
- ✅ 删除权限 (`DELETE /api/v1/rbac/permissions/{permission_id}`)

#### 角色权限分配
- ✅ 为角色分配权限 (`POST /api/v1/rbac/roles/{role_id}/permissions`)

#### 用户角色分配
- ✅ 为用户分配角色 (`POST /api/v1/rbac/users/{user_id}/roles`)
- ✅ 获取用户权限 (`GET /api/v1/rbac/users/{user_id}/permissions`)

### 2.2 数据库表

#### 2.2.1 角色表 (`roles`)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| role_id | UUID | PK | 角色ID |
| role_name | String(50) | UNIQUE, NOT NULL | 角色名称 |
| role_code | String(50) | UNIQUE, NOT NULL | 角色代码 |
| description | Text | - | 角色描述 |
| is_active | Boolean | NOT NULL, Default=True | 是否激活 |
| is_system | Boolean | NOT NULL, Default=False | 是否系统内置 |
| created_at | TIMESTAMP | NOT NULL | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL | 更新时间 |
| created_by | UUID | FK(users.user_id) | 创建者 |
| updated_by | UUID | FK(users.user_id) | 更新者 |

#### 2.2.2 权限表 (`permissions`)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| permission_id | UUID | PK | 权限ID |
| permission_name | String(100) | NOT NULL | 权限名称 |
| permission_code | String(100) | UNIQUE, NOT NULL | 权限代码 |
| resource_type | String(50) | NOT NULL | 资源类型 (api/menu/button) |
| resource_path | String(255) | - | 资源路径 |
| http_method | String(10) | - | HTTP方法 |
| description | Text | - | 权限描述 |
| parent_id | UUID | FK(permissions.permission_id) | 父权限ID |
| sort_order | Integer | Default=0 | 排序顺序 |
| is_active | Boolean | NOT NULL, Default=True | 是否激活 |
| created_at | TIMESTAMP | NOT NULL | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL | 更新时间 |

#### 2.2.3 角色权限关联表 (`role_permissions`)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 关联ID |
| role_id | UUID | FK(roles.role_id, CASCADE), NOT NULL | 角色ID |
| permission_id | UUID | FK(permissions.permission_id, CASCADE), NOT NULL | 权限ID |
| granted_at | TIMESTAMP | NOT NULL | 授予时间 |
| granted_by | UUID | FK(users.user_id) | 授予者ID |

#### 2.2.4 用户角色关联表 (`user_roles`)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 关联ID |
| user_id | UUID | FK(users.user_id, CASCADE), NOT NULL | 用户ID |
| role_id | UUID | FK(roles.role_id, CASCADE), NOT NULL | 角色ID |
| assigned_at | TIMESTAMP | NOT NULL | 分配时间 |
| assigned_by | UUID | FK(users.user_id) | 分配者ID |
| expires_at | TIMESTAMP | - | 过期时间 |

### 2.3 权限架构
```
User (users)
  ↓ (多对多)
UserRole (user_roles)
  ↓ (多对多)
Role (roles)
  ↓ (多对多)
RolePermission (role_permissions)
  ↓ (多对多)
Permission (permissions)
```

### 2.4 特性
- 权限树结构支持 (parent_id)
- 系统内置角色保护 (is_system=True)
- 角色过期时间支持
- Redis权限缓存
- 完整的审计日志 (created_by, updated_by, granted_by, assigned_by)

---

## 3. 安全组件管理模块

### 3.1 功能列表
- ✅ 获取安全组件列表 (`GET /api/v1/security/components`)
- ✅ 获取组件详情 (`GET /api/v1/security/components/{component_id}`)
- ✅ 启用组件 (`POST /api/v1/security/components/{component_id}/enable`)
- ✅ 禁用组件 (`POST /api/v1/security/components/{component_id}/disable`)
- ✅ 更新组件配置 (`PUT /api/v1/security/components/{component_id}/config`)
- ✅ 获取组件状态 (`GET /api/v1/security/components/{component_id}/status`)
- ✅ 获取组件日志 (`GET /api/v1/security/components/{component_id}/logs`)
- ✅ 健康检查 (`GET /api/v1/security/health/all`)
- ✅ 单个组件健康检查 (`POST /api/v1/security/components/{component_id}/health/check`)

### 3.2 数据库表

#### 3.2.1 安全组件表 (`security_components`)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| component_id | UUID | PK | 组件ID |
| component_code | String(50) | UNIQUE, NOT NULL | 组件代码 |
| component_name | String(100) | NOT NULL | 组件名称 |
| component_type | String(50) | NOT NULL | 组件类型 |
| description | Text | - | 组件描述 |
| is_enabled | Boolean | NOT NULL, Default=False | 是否启用 |
| config_json | JSONB | - | 配置参数 |
| priority | Integer | Default=0 | 执行优先级 |
| status | String(20) | Default='inactive' | 状态 |
| last_check_at | TIMESTAMP | - | 最后检查时间 |
| error_message | Text | - | 错误信息 |
| created_at | TIMESTAMP | NOT NULL | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL | 更新时间 |
| created_by | UUID | FK(users.user_id) | 创建者 |
| updated_by | UUID | FK(users.user_id) | 更新者 |

#### 3.2.2 安全组件日志表 (`security_component_logs`)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| log_id | UUID | PK | 日志ID |
| component_id | UUID | FK(security_components.component_id, CASCADE), NOT NULL | 组件ID |
| action | String(50) | NOT NULL | 操作类型 |
| old_config | JSONB | - | 旧配置 |
| new_config | JSONB | - | 新配置 |
| result | String(20) | NOT NULL | 结果 |
| error_message | Text | - | 错误信息 |
| performed_by | UUID | FK(users.user_id) | 执行者 |
| performed_at | TIMESTAMP | NOT NULL | 执行时间 |
| ip_address | String(45) | - | IP地址 |

### 3.3 组件类型
- `middleware`: 中间件组件
- `service`: 服务组件
- `protection`: 防护组件

### 3.4 特性
- JSONB配置存储
- 优先级管理
- Redis缓存集成
- 完整操作日志 (包含配置变更前后对比)
- 健康检查机制
- IP地址审计

---

## 4. SSL证书管理模块

### 4.1 功能列表
- ✅ 获取证书列表 (`GET /api/v1/ssl/certificates`)
- ✅ 获取证书详情 (`GET /api/v1/ssl/certificates/{cert_id}`)
- ✅ 上传证书 (`POST /api/v1/ssl/certificates`)
- ✅ 部署证书 (`POST /api/v1/ssl/certificates/{cert_id}/deploy`)
- ✅ 删除证书 (`DELETE /api/v1/ssl/certificates/{cert_id}`)
- ✅ 获取证书状态 (`GET /api/v1/ssl/certificates/{cert_id}/status`)
- ✅ 获取证书日志 (`GET /api/v1/ssl/certificates/{cert_id}/logs`)

### 4.2 数据库表

#### 4.2.1 SSL证书表 (`ssl_certificates`)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| cert_id | UUID | PK | 证书ID |
| cert_name | String(100) | NOT NULL | 证书名称 |
| domain_name | String(255) | NOT NULL | 域名 |
| cert_type | String(20) | NOT NULL | 证书类型 |
| cert_file_path | String(500) | - | 证书文件路径 |
| key_file_path | String(500) | - | 私钥文件路径 |
| chain_file_path | String(500) | - | 证书链文件路径 |
| issuer | String(255) | - | 颁发者 |
| subject | String(255) | - | 主体 |
| serial_number | String(100) | - | 序列号 |
| issued_at | TIMESTAMP | - | 颁发时间 |
| expires_at | TIMESTAMP | NOT NULL | 过期时间 |
| status | String(20) | Default='inactive' | 状态 |
| is_deployed | Boolean | Default=False | 是否已部署 |
| auto_renew | Boolean | Default=False | 是否自动续期 |
| days_before_expiry | Integer | - | 距离过期天数 |
| last_check_at | TIMESTAMP | - | 最后检查时间 |
| created_at | TIMESTAMP | NOT NULL | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL | 更新时间 |
| uploaded_by | UUID | FK(users.user_id) | 上传者 |

#### 4.2.2 SSL证书日志表 (`ssl_certificate_logs`)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| log_id | UUID | PK | 日志ID |
| cert_id | UUID | FK(ssl_certificates.cert_id, CASCADE), NOT NULL | 证书ID |
| action | String(50) | NOT NULL | 操作类型 |
| result | String(20) | NOT NULL | 结果 |
| error_message | Text | - | 错误信息 |
| performed_by | UUID | FK(users.user_id) | 执行者 |
| performed_at | TIMESTAMP | NOT NULL | 执行时间 |
| ip_address | String(45) | - | IP地址 |

### 4.3 证书类型
- `self_signed`: 自签名证书
- `ca_signed`: CA签名证书
- `letsencrypt`: Let's Encrypt证书

### 4.4 证书状态
- `active`: 已部署且有效
- `inactive`: 未部署
- `expired`: 已过期
- `expiring_soon`: 即将过期 (≤30天)

### 4.5 证书存储路径
- 证书: `/etc/ssl/hustle/certs`
- 私钥: `/etc/ssl/hustle/private`
- 证书链: `/etc/ssl/hustle/chains`

### 4.6 特性
- 自动证书解析 (使用cryptography库)
- 自动过期天数计算
- 文件权限管理 (证书644, 私钥600)
- 部署前验证
- 完整操作日志
- IP地址审计

---

## 5. 前端页面

### 5.1 系统管理页面 (`System.vue`)
**路由**: `/system`

**功能模块**:
1. 用户管理
   - 用户列表展示
   - 创建用户
   - 编辑用户
   - 删除用户 ✅
   - 用户角色分配

2. RBAC管理 (子页面 `/rbac`)
   - 角色管理
   - 权限管理
   - 角色权限分配
   - 用户角色分配

3. 安全组件管理 (子页面 `/security`)
   - 组件列表
   - 启用/禁用组件
   - 配置管理
   - 健康检查
   - 操作日志

4. SSL证书管理 (子页面 `/ssl`)
   - 证书列表
   - 上传证书
   - 部署证书
   - 证书状态监控
   - 操作日志

---

## 6. 数据库完整性状态

### 6.1 已存在的表 ✅
- `users`
- `roles`
- `permissions`
- `role_permissions`
- `user_roles`
- `security_components`
- `security_component_logs`
- `ssl_certificates`
- `ssl_certificate_logs`
- `trades`
- `system_alerts`
- `positions`
- `accounts`
- `strategies`
- `strategy_configs`
- `strategy_performance`
- `arbitrage_tasks`
- `risk_alerts`
- `risk_settings`
- `order_records`
- `account_snapshots`
- `market_data`
- `spread_records`
- `platforms`

### 6.2 外键关系完整性 ✅
所有表的外键关系已正确配置，包括：
- CASCADE删除关系
- NO ACTION约束
- 软引用 (可NULL的FK)

---

## 7. 实现状态总结

| 模块 | 后端API | 数据库表 | 前端页面 | 状态 |
|------|---------|----------|----------|------|
| 用户管理 | ✅ | ✅ | ✅ | 完成 |
| RBAC权限管理 | ✅ | ✅ | ✅ | 完成 |
| 安全组件管理 | ✅ | ✅ | ✅ | 完成 |
| SSL证书管理 | ✅ | ✅ | ✅ | 完成 |

---

## 8. 最近修复记录

### 2026-02-25
- ✅ 修复用户删除功能的FK约束问题
- ✅ 添加完整的删除前置处理逻辑
- ✅ 处理所有相关表的FK关系
- ✅ 验证所有系统管理模块表的存在性
- ✅ 更新删除用户API的错误提示为中文

---

## 9. API文档链接

完整的API文档可通过以下方式访问：
- Swagger UI: `http://localhost:8001/docs`
- ReDoc: `http://localhost:8001/redoc`

---

## 10. 开发团队

- 后端开发: FastAPI + SQLAlchemy 2.0 + PostgreSQL
- 前端开发: Vue 3 + Element Plus
- 数据库迁移: Alembic

---

**文档版本**: 1.0
**最后更新**: 2026-02-25
**维护者**: Claude Sonnet 4.6
