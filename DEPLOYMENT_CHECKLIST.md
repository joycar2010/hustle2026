# MT5 管理系统重构 - 部署清单

## ✅ 已完成的开发工作

### 1. 前端改进
- [x] 创建 PasswordInput 组件
- [x] 修复表单自动填充问题
- [x] 添加密码显示/隐藏功能
- [x] 修改 MT5 管理标签名称
- [x] 创建 MT5InstanceCard 组件

### 2. 后端数据库
- [x] 修改 MT5Instance 模型
- [x] 更新 Schema 定义
- [x] 创建数据库迁移脚本

### 3. 后端 API
- [x] 创建客户端实例列表 API
- [x] 创建部署实例 API
- [x] 创建主备切换 API
- [x] 创建健康检查 API
- [x] 创建自动故障转移 API

### 4. 文档
- [x] 重构计划文档
- [x] 修改指南
- [x] API 集成指南
- [x] 前端重构方案
- [x] 实施总结

## 📋 待部署的文件清单

### 前端文件
```
frontend/src-admin/components/
├── PasswordInput.vue (新建)
└── MT5InstanceCard.vue (新建)

frontend/src-admin/views/
└── UserManagement.vue (已修改)
```

### 后端文件
```
backend/app/models/
└── mt5_instance.py (已修改)

backend/app/schemas/
└── mt5_instance.py (已修改)

backend/app/api/v1/
└── mt5_instances_extended.py (新建，需集成到 mt5_instances.py)

backend/migrations/
└── add_mt5_instance_client_relation.sql (新建)
```

### 文档文件
```
REFACTOR_PLAN.md
MODIFICATION_GUIDE.md
IMPLEMENTATION_SUMMARY.md
backend/API_INTEGRATION_GUIDE.md
frontend/FRONTEND_REFACTOR_PLAN.md
```

## 🚀 快速部署命令

### 步骤 1：备份（必须！）
```bash
cd d:/git/hustle2026

# 备份数据库
ssh -i pem/HustleNew.pem ubuntu@admin.hustle2026.xyz \
  "sudo -u postgres pg_dump hustle_db > /tmp/backup_$(date +%Y%m%d_%H%M%S).sql"

# 备份代码
ssh -i pem/HustleNew.pem ubuntu@admin.hustle2026.xyz \
  "cd /home/ubuntu/hustle2026 && tar -czf /tmp/backup_code_$(date +%Y%m%d_%H%M%S).tar.gz backend/ frontend/"
```

### 步骤 2：上传文件
```bash
cd d:/git/hustle2026

# 上传后端文件
scp -i pem/HustleNew.pem backend/app/models/mt5_instance.py \
  ubuntu@admin.hustle2026.xyz:/home/ubuntu/hustle2026/backend/app/models/

scp -i pem/HustleNew.pem backend/app/schemas/mt5_instance.py \
  ubuntu@admin.hustle2026.xyz:/home/ubuntu/hustle2026/backend/app/schemas/

scp -i pem/HustleNew.pem backend/app/api/v1/mt5_instances_extended.py \
  ubuntu@admin.hustle2026.xyz:/home/ubuntu/hustle2026/backend/app/api/v1/

scp -i pem/HustleNew.pem backend/migrations/add_mt5_instance_client_relation.sql \
  ubuntu@admin.hustle2026.xyz:/home/ubuntu/hustle2026/backend/migrations/

# 上传前端文件
scp -i pem/HustleNew.pem frontend/src-admin/components/PasswordInput.vue \
  ubuntu@admin.hustle2026.xyz:/home/ubuntu/hustle2026/frontend/src-admin/components/

scp -i pem/HustleNew.pem frontend/src-admin/components/MT5InstanceCard.vue \
  ubuntu@admin.hustle2026.xyz:/home/ubuntu/hustle2026/frontend/src-admin/components/

scp -i pem/HustleNew.pem frontend/src-admin/views/UserManagement.vue \
  ubuntu@admin.hustle2026.xyz:/home/ubuntu/hustle2026/frontend/src-admin/views/
```

### 步骤 3：执行数据库迁移
```bash
ssh -i pem/HustleNew.pem ubuntu@admin.hustle2026.xyz \
  "sudo -u postgres psql hustle_db < /home/ubuntu/hustle2026/backend/migrations/add_mt5_instance_client_relation.sql"
```

### 步骤 4：重启后端服务
```bash
ssh -i pem/HustleNew.pem ubuntu@admin.hustle2026.xyz \
  "sudo systemctl restart hustle-python && sudo systemctl status hustle-python --no-pager | tail -10"
```

### 步骤 5：构建前端
```bash
ssh -i pem/HustleNew.pem ubuntu@admin.hustle2026.xyz \
  "cd /home/ubuntu/hustle2026/frontend && npm run build:admin"
```

### 步骤 6：验证部署
```bash
# 检查后端服务
ssh -i pem/HustleNew.pem ubuntu@admin.hustle2026.xyz \
  "sudo systemctl status hustle-python --no-pager"

# 测试 API（需要替换 TOKEN）
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://admin.hustle2026.xyz/api/v1/mt5/instances
```

## ⚠️ 重要注意事项

### 1. API 集成
`mt5_instances_extended.py` 中的端点需要手动集成到 `mt5_instances.py`。
参考 `backend/API_INTEGRATION_GUIDE.md` 进行集成。

### 2. 数据迁移
现有的 MT5 实例数据需要手动关联到对应的 MT5 客户端：
```sql
-- 示例：将实例关联到客户端
UPDATE mt5_instances
SET client_id = 1, instance_type = 'primary'
WHERE instance_id = 'your-instance-uuid';
```

### 3. 前端完整重构
当前只完成了基础组件和部分修改。完整的前端重构需要：
- 修改数据加载逻辑（同时加载客户端和实例）
- 集成 MT5InstanceCard 组件到主页面
- 实现部署客户端功能
- 实现主备切换功能
- 实现删除保护逻辑

参考 `frontend/FRONTEND_REFACTOR_PLAN.md` 完成剩余工作。

### 4. 测试
部署后必须进行以下测试：
- [ ] 密码显示/隐藏功能
- [ ] 表单自动填充是否修复
- [ ] 数据库迁移是否成功
- [ ] 后端 API 是否正常
- [ ] 前端页面是否正常显示

## 📝 测试清单

### 基础功能测试
- [ ] 登录系统
- [ ] 查看用户管理页面
- [ ] 测试密码输入框的显示/隐藏功能
- [ ] 测试新增用户（检查邮箱和密码是否自动填充）
- [ ] 测试编辑用户（检查密码和飞书 Open ID 是否自动填充）
- [ ] 测试编辑账户（检查 API Secret 是否自动填充）

### MT5 管理测试
- [ ] 查看 MT5 账户管理标签
- [ ] 测试新增 MT5 账户
- [ ] 测试部署客户端（如果已实现）
- [ ] 测试主备切换（如果已实现）
- [ ] 测试删除保护（如果已实现）

### API 测试
```bash
# 获取实例列表
curl -H "Authorization: Bearer $TOKEN" \
  https://admin.hustle2026.xyz/api/v1/mt5/instances

# 获取客户端的实例
curl -H "Authorization: Bearer $TOKEN" \
  https://admin.hustle2026.xyz/api/v1/mt5/instances/client/1

# 健康检查
curl -H "Authorization: Bearer $TOKEN" \
  https://admin.hustle2026.xyz/api/v1/mt5/instances/client/1/health
```

## 🔄 回滚方案

如果部署出现问题，执行以下回滚步骤：

### 1. 回滚数据库
```bash
ssh -i pem/HustleNew.pem ubuntu@admin.hustle2026.xyz \
  "sudo -u postgres psql hustle_db < /tmp/backup_YYYYMMDD_HHMMSS.sql"
```

### 2. 回滚代码
```bash
ssh -i pem/HustleNew.pem ubuntu@admin.hustle2026.xyz \
  "cd /home/ubuntu && tar -xzf /tmp/backup_code_YYYYMMDD_HHMMSS.tar.gz -C /home/ubuntu/hustle2026"
```

### 3. 重启服务
```bash
ssh -i pem/HustleNew.pem ubuntu@admin.hustle2026.xyz \
  "sudo systemctl restart hustle-python && cd /home/ubuntu/hustle2026/frontend && npm run build:admin"
```

## 📞 支持

如有问题，请参考以下文档：
- `IMPLEMENTATION_SUMMARY.md` - 完整实施总结
- `MODIFICATION_GUIDE.md` - 详细修改指南
- `backend/API_INTEGRATION_GUIDE.md` - API 集成指南
- `frontend/FRONTEND_REFACTOR_PLAN.md` - 前端重构方案

## ✨ 下一步

1. 测试当前部署的基础功能
2. 根据测试结果调整
3. 完成前端完整重构
4. 实现自动故障转移定时任务
5. 添加监控告警功能
