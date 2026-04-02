# Bridge 服务控制功能测试文档

## 功能概述

Bridge 服务控制区域提供完整的 Bridge HTTP 服务生命周期管理功能。

## 功能特性

### 1. Bridge 服务状态显示
- **位置**: MT5 账户卡片中，在"Windows Agent 远程控制"区域之前
- **显示内容**:
  - 服务状态（运行中/已停止/未知）
  - 服务名称（如：hustle-mt5-xxx）
  - 服务端口（如：8001）

### 2. Bridge 服务控制按钮
- **启动按钮**: 
  - 当服务已停止时启用
  - 当服务运行中时禁用
  - 点击后调用 `/api/v1/mt5-agent/bridge/{client_id}/start`
  
- **停止按钮**:
  - 当服务运行中时启用
  - 当服务已停止时禁用
  - 点击后调用 `/api/v1/mt5-agent/bridge/{client_id}/stop`
  
- **重启按钮**:
  - 当服务运行中时启用
  - 当服务已停止时禁用
  - 点击后调用 `/api/v1/mt5-agent/bridge/{client_id}/restart`

### 3. Bridge 部署功能
- **部署按钮**: 当客户端未部署 Bridge 时显示"+ 部署Bridge服务"
- **部署对话框**:
  - 显示客户端名称
  - 输入服务端口（8000-9000）
  - 端口范围验证
  - 自动部署说明

### 4. Bridge 删除功能
- **删除按钮**: 在已部署 Bridge 的控制面板底部
- **确认提示**: 防止误操作
- **删除内容**:
  - Windows 服务
  - Bridge 部署目录
  - MT5 客户端目录
  - 桌面快捷方式

## API 端点

### 后端 API (FastAPI)

#### 获取 Bridge 状态
```
GET /api/v1/mt5-agent/bridge/{client_id}/status
```
返回:
```json
{
  "service_name": "hustle-mt5-xxx",
  "status": "SERVICE_RUNNING",
  "is_running": true
}
```

#### 启动 Bridge 服务
```
POST /api/v1/mt5-agent/bridge/{client_id}/start
```
返回:
```json
{
  "service_name": "hustle-mt5-xxx",
  "operation": "start",
  "success": true,
  "message": "Service started successfully"
}
```

#### 停止 Bridge 服务
```
POST /api/v1/mt5-agent/bridge/{client_id}/stop
```

#### 重启 Bridge 服务
```
POST /api/v1/mt5-agent/bridge/{client_id}/restart
```

#### 部署 Bridge 服务
```
POST /api/v1/mt5-agent/bridge/{client_id}/deploy
Body: { "service_port": 8001 }
```

#### 删除 Bridge 服务
```
DELETE /api/v1/mt5-agent/bridge/{client_id}
```

### Windows Agent API

#### 获取服务状态
```
GET /bridge/{service_name}/status
Header: X-API-Key: {api_key}
```

#### 启动服务
```
POST /bridge/{service_name}/start
Header: X-API-Key: {api_key}
```

#### 停止服务
```
POST /bridge/{service_name}/stop
Header: X-API-Key: {api_key}
```

#### 重启服务
```
POST /bridge/{service_name}/restart
Header: X-API-Key: {api_key}
```

## 测试步骤

### 1. 部署 Bridge 服务

1. 访问 https://admin.hustle2026.xyz/users
2. 找到一个已配置 MT5 客户端的账户
3. 在 MT5 客户端卡片中，找到"Bridge 服务控制"区域
4. 如果显示"+ 部署Bridge服务"按钮，点击它
5. 在弹出的对话框中输入端口号（如：8001）
6. 点击"开始部署"
7. 等待部署完成（约10-30秒）
8. 刷新页面，应该看到 Bridge 服务控制面板

### 2. 测试 Bridge 服务控制

#### 测试启动
1. 如果服务已停止，点击"启动"按钮
2. 等待3秒后，状态应该变为"运行中"
3. 启动按钮应该变为禁用状态

#### 测试停止
1. 如果服务运行中，点击"停止"按钮
2. 确认操作
3. 等待1秒后，状态应该变为"已停止"
4. 停止按钮应该变为禁用状态

#### 测试重启
1. 确保服务运行中
2. 点击"重启"按钮
3. 确认操作
4. 等待3秒后，状态应该仍为"运行中"

### 3. 测试删除功能

1. 点击"删除Bridge"按钮
2. 在确认对话框中确认删除
3. 等待删除完成
4. 刷新页面，应该看到"+ 部署Bridge服务"按钮

## 故障排查

### 问题1: 点击按钮没有反应
**可能原因**:
- 浏览器缓存未清除
- 前端代码未更新

**解决方法**:
1. 强制刷新浏览器（Ctrl+F5 或 Cmd+Shift+R）
2. 清除浏览器缓存
3. 检查浏览器控制台是否有错误

### 问题2: 提示"未配置 Bridge 服务"
**可能原因**:
- 数据库中 bridge_service_name 字段为空

**解决方法**:
1. 先部署 Bridge 服务
2. 检查数据库 mt5_clients 表的 bridge_service_name 和 bridge_service_port 字段

### 问题3: 服务状态显示"未知"
**可能原因**:
- Windows Agent 无法连接
- 服务名称不正确

**解决方法**:
1. 检查 Windows Agent 服务是否运行
2. 检查网络连接
3. 查看后端日志

### 问题4: 部署失败
**可能原因**:
- 端口已被占用
- MT5 源目录不存在
- 权限不足

**解决方法**:
1. 更换端口号
2. 检查 D:\MetaTrader 5-01 目录是否存在
3. 检查 Windows Agent 服务权限

## 日志查看

### 后端日志
```bash
ssh -i ~/.ssh/HustleNew.pem ubuntu@go.hustle2026.xyz
sudo journalctl -u hustle-python -f
```

### Windows Agent 日志
```bash
ssh -i ~/.ssh/id_ed25519 Administrator@54.249.66.53
type C:\MT5Agent\logs\agent.log
```

### Bridge 服务日志
```bash
ssh -i ~/.ssh/id_ed25519 Administrator@54.249.66.53
type D:\hustle-mt5-{service_name}\logs\stdout.log
type D:\hustle-mt5-{service_name}\logs\stderr.log
```

## 数据库字段

### mt5_clients 表
- `bridge_service_name`: Bridge 服务名称（如：hustle-mt5-xxx）
- `bridge_service_port`: Bridge 服务端口（如：8001）

## 注意事项

1. **端口范围**: Bridge 服务端口必须在 8000-9000 之间
2. **唯一性**: 每个端口只能部署一个 Bridge 服务
3. **依赖关系**: Bridge 服务依赖 MT5 客户端，删除时会同时删除
4. **权限要求**: 需要管理员权限才能操作 Bridge 服务
5. **状态刷新**: 状态每30秒自动刷新一次
6. **桌面快捷方式**: 部署时会在 C:\Users\Administrator\Desktop 创建快捷方式
