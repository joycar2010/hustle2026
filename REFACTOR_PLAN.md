# 用户管理页面重构计划

## 需求概述

### 1. 表单自动填充问题修复
- **新增用户模态框**：邮箱和密码被浏览器自动填充
- **编辑用户模态框**：密码和飞书 Open ID 被自动填充
- **编辑账户模态框**：API Secret 被自动填充
- **解决方案**：添加 `autocomplete="off"` 或 `autocomplete="new-password"`

### 2. 密码显示/隐藏功能
需要为以下字段添加眼睛图标切换显示：
- 编辑用户模态框的密码字段
- 编辑账户模态框的 API Secret 字段（留空不修改）
- MT5 密码字段

### 3. MT5 管理页面重构

#### 3.1 命名和结构调整
- "客户端连接" 标签改名为 "MT5账户管理"
- "新增客户端" 按钮改名为 "新增MT5账户"
- 整合服务实例功能到同一页面

#### 3.2 MT5 账户与实例绑定关系
- 一个 MT5 账户可以绑定 2 个客户端实例：
  - **主跑客户端（MT5实例）**：主要使用的实例
  - **备用客户端（MT5实例）**：故障时自动切换
- 只能启用一个客户端实例
- 自动故障切换逻辑

#### 3.3 MT5 账户卡片功能
- 新增"部署客户端"按钮（原"部署新实例"按钮移动到此）
- 取消路径显示
- 右上角"启用"按钮：
  - 启用后开始调用该 MT5 账户的数据
  - 连接状态下禁止停用
- 连接状态指示
- 禁止删除处于连接或启用状态的账户

#### 3.4 服务实例卡片
- 显示在对应 MT5 账户下方
- 显示实例类型（主跑/备用）
- 功能按钮：
  - 刷新状态
  - 启动
  - 停止
  - 重启
  - 编辑
  - 删除

#### 3.5 部署新实例逻辑
- MT5 账号信息：读取绑定的 MT5 账户信息
- 部署路径：
  - 如果为空：系统在 MT5 桥接服务器上自动创建新目录
  - 自动开启新端口的逻辑和服务
- 开机自启：
  - 如果勾选：后端设置端口桥接服务和 MT5 客户端为开机自启
  - 如果不勾选：不设置开机自启
- MT5 桥接地址：自动引用主跑客户端的服务器 IP 和服务端口

#### 3.6 编辑 MT5 客户端
- 取消 MT5 桥接地址数据输入项
- 自动引用主跑客户端的服务器 IP 和服务端口
- MT5 密码显示为 * 号，带查看按钮

## 数据模型设计

### MT5 账户表 (mt5_clients)
```sql
- client_id (UUID, PK)
- user_id (UUID, FK)
- mt5_login (String)
- mt5_password (String, 加密)
- mt5_server (String)
- is_active (Boolean) -- 是否启用
- is_connected (Boolean) -- 是否连接中
- created_at (Timestamp)
- updated_at (Timestamp)
```

### MT5 实例表 (mt5_instances)
```sql
- instance_id (UUID, PK)
- client_id (UUID, FK) -- 关联 MT5 账户
- instance_type (Enum: 'primary', 'backup') -- 主跑/备用
- instance_name (String)
- server_ip (String)
- service_port (Integer)
- mt5_path (String)
- deploy_path (String)
- is_active (Boolean) -- 是否启用（只能有一个为 true）
- auto_start (Boolean)
- status (String) -- running/stopped/error
- created_at (Timestamp)
- updated_at (Timestamp)
```

## 实施步骤

### 阶段 1：修复表单问题（简单）
1. 添加 autocomplete 属性
2. 实现密码显示/隐藏组件

### 阶段 2：数据库和后端 API（中等）
1. 修改 mt5_instances 表结构，添加 client_id 和 instance_type
2. 创建 MT5 账户与实例关联的 API
3. 实现主备切换逻辑 API
4. 实现连接状态检查 API

### 阶段 3：前端页面重构（复杂）
1. 重构 MT5 管理页面结构
2. 实现 MT5 账户卡片组件
3. 实现服务实例卡片组件
4. 实现部署客户端流程
5. 实现主备切换 UI
6. 实现连接状态检查和禁用逻辑

### 阶段 4：测试和优化
1. 功能测试
2. 故障切换测试
3. 性能优化
4. 用户体验优化

## 技术要点

### 前端
- Vue 3 Composition API
- Element Plus 组件库
- 响应式设计
- 状态管理

### 后端
- FastAPI 异步 API
- SQLAlchemy ORM
- 数据库事务
- SSH 远程控制

### 安全
- 密码加密存储
- API 权限验证
- 操作日志记录

## 风险和注意事项

1. **数据迁移**：现有 MT5 实例数据需要迁移到新结构
2. **向后兼容**：确保现有功能不受影响
3. **故障切换**：需要可靠的健康检查机制
4. **并发控制**：防止同时启用多个实例
5. **用户体验**：复杂的 UI 需要清晰的交互设计
