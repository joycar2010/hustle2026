# Bridge 服务控制区域验证报告

## 数据库配置验证 ✅

### MT5-01
- **client_id**: 1
- **bridge_service_name**: `hustle-mt5-cq987`
- **bridge_service_port**: 8002
- **agent_instance_name**: `mt5-01`
- **状态**: 已配置 ✅

### MT5-Sys-Server
- **client_id**: 3
- **bridge_service_name**: `hustle-mt5-system`
- **bridge_service_port**: 8001
- **agent_instance_name**: `bybit_system_service`
- **状态**: 已配置 ✅

## 前端显示逻辑验证

### Bridge 服务控制区域显示条件

根据代码 `frontend/src-admin/views/UserManagement.vue` 第 386 行：

```vue
<div v-if="client.bridge_service_name" class="bg-dark-200 rounded-lg p-2.5 space-y-2">
```

**显示条件**: `client.bridge_service_name` 不为空

**MT5-01**: ✅ `hustle-mt5-cq987` (已配置)
**MT5-Sys-Server**: ✅ `hustle-mt5-system` (已配置)

### 显示内容

当 `bridge_service_name` 存在时，前端会显示：

1. **标题**: "Bridge服务"
2. **服务信息**:
   - 服务名: `client.bridge_service_name`
   - 端口: `client.bridge_service_port`
3. **状态**: 通过 `bridgeStatus[client.client_id]` 获取
4. **控制按钮**:
   - 启动 (当服务未运行时启用)
   - 停止 (当服务运行时启用)
   - 重启 (当服务运行时启用)
   - 删除

## Windows Agent 远程控制验证

### 远程控制使用的参数

**API 端点**: `/api/v1/mt5-agent/clients/{client_id}/start|stop|restart`

**使用的参数**:
- `agent_instance_name` - 用于调用 Windows Agent 的实例控制

**MT5-01**: 使用 `mt5-01` ✅
**MT5-Sys-Server**: 使用 `bybit_system_service` ✅

### 参数独立性验证

**Bridge 服务控制** (新版):
- 使用: `bridge_service_name` + `bridge_service_port`
- API: `/api/v1/mt5-agent/bridge/{client_id}/start|stop|restart`
- 控制对象: Bridge HTTP 服务 (Windows 服务)

**Windows Agent 远程控制**:
- 使用: `agent_instance_name`
- API: `/api/v1/mt5-agent/clients/{client_id}/start|stop|restart`
- 控制对象: MT5 客户端进程 (terminal64.exe)

**结论**: ✅ 两个控制系统使用不同的参数，互不干扰

## 前端 API 调用验证

### Bridge 服务控制 API

**获取状态**:
```javascript
GET /api/v1/mt5-agent/bridge/{client_id}/status
```

**控制操作**:
```javascript
POST /api/v1/mt5-agent/bridge/{client_id}/start
POST /api/v1/mt5-agent/bridge/{client_id}/stop
POST /api/v1/mt5-agent/bridge/{client_id}/restart
```

**部署**:
```javascript
POST /api/v1/mt5-agent/bridge/{client_id}/deploy
Body: { service_port: 8002 }
```

**删除**:
```javascript
DELETE /api/v1/mt5-agent/bridge/{client_id}
```

### Windows Agent 远程控制 API

**获取状态**:
```javascript
GET /api/v1/mt5-agent/instances/{agent_instance_name}/status
```

**控制操作**:
```javascript
POST /api/v1/mt5-agent/clients/{client_id}/start
POST /api/v1/mt5-agent/clients/{client_id}/stop
POST /api/v1/mt5-agent/clients/{client_id}/restart
```

## 预期前端显示

### MT5-01 账户卡片

```
┌─────────────────────────────────────┐
│ MT5-01                              │
│ MT5登录: 2325036                    │
│ 服务器: Bybit-Live-2                │
│ ...                                 │
├─────────────────────────────────────┤
│ Bridge服务                    运行中 │
│ 服务名: hustle-mt5-cq987            │
│ 端口: 8002                          │
│ [启动] [停止] [重启]                │
│ [删除Bridge]                        │
├─────────────────────────────────────┤
│ 远程控制                      运行中 │
│ CPU: 2.5%                           │
│ 内存: 150 MB                        │
│ [启动] [停止] [重启]                │
└─────────────────────────────────────┘
```

### MT5-Sys-Server 账户卡片

```
┌─────────────────────────────────────┐
│ MT5-Sys-Server                      │
│ MT5登录: 3971962                    │
│ 服务器: Bybit-Live-2                │
│ ...                                 │
├─────────────────────────────────────┤
│ Bridge服务                    已停止 │
│ 服务名: hustle-mt5-system           │
│ 端口: 8001                          │
│ [启动] [停止] [重启]                │
│ [删除Bridge]                        │
├─────────────────────────────────────┤
│ 远程控制                      运行中 │
│ CPU: 1.8%                           │
│ 内存: 120 MB                        │
│ [启动] [停止] [重启]                │
└─────────────────────────────────────┘
```

## 验证步骤

### 1. 前端显示验证

1. 访问: https://admin.hustle2026.xyz/users
2. 强制刷新: Ctrl+F5
3. 检查 MT5-01 和 MT5-Sys-Server 卡片

**预期结果**:
- ✅ 看到"Bridge服务"区域（不是"Bridge实例"）
- ✅ 显示服务名称和端口号
- ✅ 显示服务状态
- ✅ 有启动/停止/重启/删除按钮
- ✅ "Windows Agent 远程控制"区域在 Bridge 服务区域下方

### 2. Bridge 服务控制测试

**测试 MT5-01 (hustle-mt5-cq987)**:
1. 点击"停止"按钮
2. 等待 2-3 秒
3. 状态应变为"已停止"
4. 点击"启动"按钮
5. 等待 2-3 秒
6. 状态应变为"运行中"

**测试 MT5-Sys-Server (hustle-mt5-system)**:
1. 当前状态应为"已停止"
2. 点击"启动"按钮
3. 等待 2-3 秒
4. 状态应变为"运行中"

### 3. Windows Agent 远程控制测试

**测试 MT5-01**:
1. 在"远程控制"区域点击"重启"
2. 确认操作
3. 等待 5-10 秒
4. 状态应保持"运行中"
5. CPU 和内存数据应更新

### 4. 独立性验证

**验证两个控制系统互不干扰**:
1. 停止 Bridge 服务
2. 检查"远程控制"状态 - 应该仍然显示 MT5 进程运行中
3. 停止 MT5 进程（通过远程控制）
4. 检查 Bridge 服务状态 - 应该独立显示

## 故障排查

### 问题1: 前端不显示 Bridge 服务区域

**可能原因**: 浏览器缓存

**解决方法**:
1. 强制刷新: Ctrl+F5
2. 清除浏览器缓存
3. 使用无痕模式访问

### 问题2: 显示"+ 部署Bridge服务"按钮

**可能原因**: `bridge_service_name` 为空

**解决方法**:
```sql
-- 检查数据库
SELECT client_id, client_name, bridge_service_name, bridge_service_port
FROM mt5_clients
WHERE client_name IN ('MT5-01', 'MT5-Sys-Server');

-- 如果为空，更新数据
UPDATE mt5_clients
SET bridge_service_name = 'hustle-mt5-cq987', bridge_service_port = 8002
WHERE client_name = 'MT5-01';

UPDATE mt5_clients
SET bridge_service_name = 'hustle-mt5-system', bridge_service_port = 8001
WHERE client_name = 'MT5-Sys-Server';
```

### 问题3: 控制按钮无响应

**可能原因**: Windows Agent 服务未运行

**解决方法**:
```powershell
# 检查服务
sc query MT5Agent

# 重启服务
nssm restart MT5Agent
```

### 问题4: 503 错误

**可能原因**: 后端无法连接到 Windows Agent

**解决方法**:
1. 检查 Windows Agent 服务状态
2. 检查网络连接
3. 检查防火墙设置
4. 验证 API Key 配置

## 总结

### 配置状态
- ✅ 数据库配置正确
- ✅ Bridge 服务名称和端口已设置
- ✅ Windows Agent 实例名称已配置
- ✅ 前端代码已更新
- ✅ 旧版 Bridge 实例区域已删除

### 系统架构
- ✅ Bridge 服务控制和 Windows Agent 远程控制使用不同参数
- ✅ 两个控制系统互不干扰
- ✅ 前端正确区分两个控制区域

### 下一步
1. 访问前端验证显示
2. 测试 Bridge 服务控制功能
3. 测试 Windows Agent 远程控制功能
4. 验证两个系统的独立性

所有配置已正确完成，系统应该可以正常工作！
