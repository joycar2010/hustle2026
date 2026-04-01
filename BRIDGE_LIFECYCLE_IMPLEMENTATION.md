# Bridge 实例生命周期管理 - 实施总结

## ✅ 已完成的后端功能

### 1. Windows Agent (C:\MT5Agent\main_v3.py)

**Bridge 控制 API**
- `GET /bridge/{service_name}/status` - 获取服务状态
- `POST /bridge/{service_name}/start` - 启动服务
- `POST /bridge/{service_name}/stop` - 停止服务  
- `POST /bridge/{service_name}/restart` - 重启服务

**Bridge 生命周期管理 API**
- `POST /bridge/deploy` - 部署新的 Bridge 实例
  - 自动在 D:\ 创建 hustle-mt5-{实例名} 目录
  - 创建 app、logs、venv 子目录
  - 生成 .env 配置文件
  - 从模板复制应用代码
  - 使用 nssm 配置 Windows 服务
  - 设置自动启动
  - 失败时自动清理

- `DELETE /bridge/{service_name}` - 删除 Bridge 实例
  - 停止服务
  - 删除 nssm 服务配置
  - 删除部署目录

### 2. 后端 API (backend/app/api/v1/mt5_agent.py)

**Bridge 控制代理端点**
- `GET /api/v1/mt5-agent/bridge/{client_id}/status`
- `POST /api/v1/mt5-agent/bridge/{client_id}/start`
- `POST /api/v1/mt5-agent/bridge/{client_id}/stop`
- `POST /api/v1/mt5-agent/bridge/{client_id}/restart`

**Bridge 生命周期管理代理端点**
- `POST /api/v1/mt5-agent/bridge/{client_id}/deploy`
  - 参数：service_port
  - 自动生成服务名称
  - 调用 Windows Agent 部署
  - 更新数据库 bridge_service_name

- `DELETE /api/v1/mt5-agent/bridge/{client_id}`
  - 调用 Windows Agent 删除
  - 清空数据库 bridge_service_name

### 3. 数据库

**mt5_clients 表新增字段**
- `bridge_service_name` VARCHAR(100) - Bridge 服务名称

**当前配置**
- client_id=1 (MT5-01): bridge_service_name='hustle-mt5-cq987'
- client_id=3 (MT5-Sys-Server): bridge_service_name='hustle-mt5-system'

## 📋 前端需要实现的功能

### 1. Bridge 控制按钮（在 MT5 客户端卡片中）

需要添加的按钮：
```vue
<!-- Bridge 服务控制 -->
<div v-if="client.bridge_service_name" class="bg-dark-200 rounded-lg p-2.5 space-y-2">
  <div class="flex items-center justify-between">
    <span class="text-xs text-text-tertiary font-medium">Bridge服务</span>
    <span class="px-1.5 py-0.5 rounded text-xs" :class="getBridgeStatusClass(client)">
      {{ getBridgeStatusText(client) }}
    </span>
  </div>

  <!-- 控制按钮 -->
  <div class="flex gap-1.5">
    <button @click="bridgeControl(client, 'start')" ...>启动</button>
    <button @click="bridgeControl(client, 'stop')" ...>停止</button>
    <button @click="bridgeControl(client, 'restart')" ...>重启</button>
  </div>
</div>
```

### 2. 调整布局顺序

**当前顺序**：
1. 详情
2. 连接统计
3. 操作按钮（编辑/删除）
4. Windows Agent 远程控制
5. MT5 Bridge 客户端实例

**目标顺序**：
1. 详情
2. 连接统计
3. 操作按钮（编辑/删除）
4. **MT5 Bridge 服务控制**（新增，移到前面）
5. Windows Agent 远程控制（移到后面）
6. MT5 Bridge 客户端实例（保持）

### 3. Bridge 部署功能

在"MT5 Bridge 客户端实例"区域：
- 如果没有 bridge_service_name，显示"部署Bridge"按钮
- 点击后弹出对话框，输入服务端口
- 调用 `POST /api/v1/mt5-agent/bridge/{client_id}/deploy`

### 4. Bridge 删除功能

在 Bridge 控制区域添加删除按钮：
- 点击后二次确认
- 调用 `DELETE /api/v1/mt5-agent/bridge/{client_id}`

### 5. 需要添加的 Vue 方法

```javascript
// Bridge 状态管理
const bridgeStatus = ref({})
const bridgeLoading = ref({})

// 获取 Bridge 状态
async function fetchBridgeStatus() {
  for (const client of mt5Clients.value) {
    if (client.bridge_service_name) {
      try {
        const response = await api.get(`/api/v1/mt5-agent/bridge/${client.client_id}/status`)
        bridgeStatus.value[client.client_id] = response.data
      } catch (error) {
        console.error(`Failed to fetch bridge status for client ${client.client_id}:`, error)
      }
    }
  }
}

// Bridge 控制
async function bridgeControl(client, action) {
  try {
    bridgeLoading.value[client.client_id] = action
    const response = await api.post(`/api/v1/mt5-agent/bridge/${client.client_id}/${action}`)
    
    if (response.data.success) {
      toast(`Bridge ${action}成功！`, 'success')
      await fetchBridgeStatus()
    }
  } catch (error) {
    toast(`Bridge ${action}失败: ${error.response?.data?.detail || error.message}`, 'error')
  } finally {
    bridgeLoading.value[client.client_id] = null
  }
}

// 部署 Bridge
async function deployBridge(client) {
  const port = await promptForPort() // 弹出对话框获取端口
  if (!port) return

  try {
    const response = await api.post(`/api/v1/mt5-agent/bridge/${client.client_id}/deploy`, {
      service_port: port
    })
    
    if (response.data.success) {
      toast('Bridge 部署成功！', 'success')
      await fetchMT5Clients()
    }
  } catch (error) {
    toast(`部署失败: ${error.response?.data?.detail || error.message}`, 'error')
  }
}

// 删除 Bridge
async function deleteBridge(client) {
  if (!confirm(`确定要删除 ${client.client_name} 的 Bridge 服务吗？\n\n这将删除部署目录和服务配置，操作不可恢复！`)) {
    return
  }

  try {
    const response = await api.delete(`/api/v1/mt5-agent/bridge/${client.client_id}`)
    
    if (response.data.success) {
      toast('Bridge 删除成功！', 'success')
      await fetchMT5Clients()
    }
  } catch (error) {
    toast(`删除失败: ${error.response?.data?.detail || error.message}`, 'error')
  }
}

// 状态样式
function getBridgeStatusClass(client) {
  const status = bridgeStatus.value[client.client_id]
  if (!status) return 'bg-gray-600 text-gray-300'
  return status.is_running ? 'bg-[#0ecb81]/10 text-[#0ecb81]' : 'bg-gray-600 text-gray-300'
}

function getBridgeStatusText(client) {
  const status = bridgeStatus.value[client.client_id]
  if (!status) return '未知'
  return status.is_running ? '运行中' : '已停止'
}
```

### 6. 生命周期钩子

在 `onMounted` 中添加：
```javascript
onMounted(async () => {
  await fetchUsers()
  await fetchAccounts()
  await fetchMT5Clients()
  await fetchAgentStatus()
  await fetchBridgeStatus() // 新增
  
  // 定时刷新
  setInterval(fetchAgentStatus, 30000)
  setInterval(fetchBridgeStatus, 30000) // 新增
})
```

## 🚀 部署步骤

### 1. 部署 Windows Agent
```bash
scp -i /c/Users/HUAWEI/.ssh/id_ed25519 d:/git/hustle2026/windows-agent/main_v3.py Administrator@35.77.212.24:C:/MT5Agent/main_v3.py
ssh -i /c/Users/HUAWEI/.ssh/id_ed25519 Administrator@35.77.212.24 "nssm restart MT5WindowsAgent"
```

### 2. 部署后端
```bash
ssh -i c:/Users/HUAWEI/.ssh/HustleNew.pem ubuntu@go.hustle2026.xyz "cd /home/ubuntu/hustle2026 && git pull origin go && sudo systemctl restart hustle-python"
```

### 3. 创建 Bridge 模板目录（在 Windows 服务器上）
```powershell
# 在 Windows 服务器上执行
mkdir D:\hustle-mt5-template
mkdir D:\hustle-mt5-template\app
mkdir D:\hustle-mt5-template\venv
mkdir D:\hustle-mt5-template\logs

# 从现有的 Bridge 实例复制代码
Copy-Item D:\hustle-mt5-cq987\app\* D:\hustle-mt5-template\app\ -Recurse
Copy-Item D:\hustle-mt5-cq987\venv\* D:\hustle-mt5-template\venv\ -Recurse
Copy-Item D:\hustle-mt5-cq987\requirements.txt D:\hustle-mt5-template\
```

### 4. 部署前端
前端代码需要完成上述功能后再部署。

## 📝 测试计划

### 1. Bridge 控制测试
- [ ] 启动 Bridge 服务
- [ ] 停止 Bridge 服务
- [ ] 重启 Bridge 服务
- [ ] 状态显示正确

### 2. Bridge 部署测试
- [ ] 输入端口号
- [ ] 自动创建目录
- [ ] 自动配置服务
- [ ] 服务自动启动
- [ ] 数据库更新正确

### 3. Bridge 删除测试
- [ ] 二次确认提示
- [ ] 停止服务
- [ ] 删除服务配置
- [ ] 删除部署目录
- [ ] 数据库清空正确

### 4. 错误处理测试
- [ ] 端口冲突
- [ ] 目录已存在
- [ ] 服务名冲突
- [ ] 权限不足
- [ ] 网络错误

## 🎯 下一步行动

1. **立即部署后端代码**（已完成编码）
2. **创建 Bridge 模板目录**（在 Windows 服务器上）
3. **完成前端界面修改**（需要实现上述 Vue 代码）
4. **测试完整流程**
5. **编写用户文档**
