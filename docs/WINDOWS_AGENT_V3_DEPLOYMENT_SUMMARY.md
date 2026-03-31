# Windows Agent V3 部署总结

## 已完成的工作

### 1. 核心代码 ✅

创建了 Windows Agent V3 (`main_v3.py`)，整合了以下功能：

- **远程控制 MT5 实例**
  - 启动/停止/重启 MT5 客户端
  - 按路径精准识别实例，避免误操作
  - 支持便携模式、隐藏窗口、自动登录

- **健康状态监控**
  - CPU 使用率监控
  - 内存使用率监控
  - 卡顿检测（通过 CPU 变化率判断）
  - 自动告警

- **后端 API 集成**
  - 自动获取访问令牌
  - 发送告警到管理员
  - 使用通知模板系统

### 2. 配置文件 ✅

- `config.example.json` - Agent 配置模板
- `instances.example.json` - MT5 实例配置模板
- `requirements.txt` - Python 依赖列表

### 3. 部署工具 ✅

- `deploy.ps1` - 自动化部署脚本
- 完整的部署文档

### 4. 文档 ✅

- `WINDOWS_AGENT_V3_GUIDE.md` - 完整使用指南
  - 架构设计
  - 安装部署
  - API 使用
  - 故障排查
  - 安全建议

## 文件清单

| 文件 | 路径 | 说明 |
|------|------|------|
| 核心代码 | `windows-agent/main_v3.py` | Agent 主程序 |
| 配置示例 | `windows-agent/config.example.json` | 配置文件模板 |
| 实例示例 | `windows-agent/instances.example.json` | 实例配置模板 |
| 依赖列表 | `windows-agent/requirements.txt` | Python 依赖 |
| 部署脚本 | `windows-agent/deploy.ps1` | 自动化部署 |
| 使用指南 | `docs/WINDOWS_AGENT_V3_GUIDE.md` | 完整文档 |

## 快速部署步骤

### 在本地准备文件

```bash
# 1. 确认文件已创建
ls d:/git/hustle2026/windows-agent/
# 应该看到：main_v3.py, config.example.json, instances.example.json, requirements.txt, deploy.ps1

# 2. 上传到 Windows 服务器
scp -i /c/Users/HUAWEI/.ssh/id_ed25519 d:/git/hustle2026/windows-agent/* Administrator@54.249.66.53:C:/MT5Agent/
```

### 在 Windows 服务器上部署

```powershell
# 1. 连接到 Windows 服务器
ssh -i /c/Users/HUAWEI/.ssh/id_ed25519 Administrator@54.249.66.53

# 2. 运行部署脚本
cd C:\MT5Agent
powershell -ExecutionPolicy Bypass -File deploy.ps1

# 3. 编辑配置文件
notepad config.json
notepad instances.json

# 4. 测试运行
python main_v3.py

# 5. 访问 API 文档
# 打开浏览器访问: http://localhost:8765/docs
```

## 核心功能说明

### 1. 远程控制 API

```http
# 启动实例
POST /instances/{instance_name}/start
X-API-Key: your_api_key

# 停止实例
POST /instances/{instance_name}/stop
X-API-Key: your_api_key

# 重启实例
POST /instances/{instance_name}/restart
X-API-Key: your_api_key

# 获取状态
GET /instances/{instance_name}
X-API-Key: your_api_key
```

### 2. 健康监控

Agent 会自动监控以下指标：

- **CPU 使用率**: 超过 95% 触发告警
- **内存使用率**: 超过 90% 触发告警
- **卡顿检测**: CPU 高但无变化，连续 10 次触发告警

### 3. 自动告警

检测到异常时，Agent 会：

1. 记录日志到 `C:\MT5Agent\logs\agent.log`
2. 调用后端 API 获取管理员列表
3. 发送通知到管理员（通过飞书）

## 配置示例

### config.json

```json
{
  "agent": {
    "host": "0.0.0.0",
    "port": 8765,
    "api_key": "HustleXAU_MT5_Agent_Key_2026"
  },
  "backend": {
    "url": "https://admin.hustle2026.xyz",
    "username": "monitor_user",
    "password": "your_password",
    "enabled": true
  },
  "monitoring": {
    "enabled": true,
    "check_interval": 30,
    "freeze_threshold": 10,
    "cpu_threshold": 95,
    "memory_threshold": 90
  }
}
```

### instances.json

```json
{
  "bybit_system": {
    "name": "Bybit System Service",
    "path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
    "account": "3971962",
    "password": "your_password",
    "server": "Bybit-Live-2",
    "is_investor": false,
    "portable": true,
    "create_no_window": false
  },
  "bybit_mt5_01": {
    "name": "Bybit MT5-01",
    "path": "D:\\MetaTrader 5-01\\terminal64.exe",
    "account": "2325036",
    "password": "your_password",
    "server": "Bybit-Live-2",
    "is_investor": false,
    "portable": true,
    "create_no_window": false
  }
}
```

## 前端集成示例

在管理后台的 MT5 客户端管理页面，添加控制按钮：

```vue
<template>
  <div class="mt5-client-card">
    <div class="client-info">
      <h3>{{ client.name }}</h3>
      <span :class="statusClass">{{ statusText }}</span>
    </div>
    <div class="client-controls">
      <el-button
        type="success"
        :disabled="isRunning"
        @click="startInstance">
        启动
      </el-button>
      <el-button
        type="danger"
        :disabled="!isRunning"
        @click="stopInstance">
        停止
      </el-button>
      <el-button
        type="warning"
        :disabled="!isRunning"
        @click="restartInstance">
        重启
      </el-button>
    </div>
    <div v-if="healthStatus" class="health-info">
      <div>CPU: {{ healthStatus.details.cpu_percent }}%</div>
      <div>内存: {{ healthStatus.details.memory_mb.toFixed(1) }} MB</div>
      <el-tag v-if="healthStatus.is_frozen" type="danger">卡顿</el-tag>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  client: Object
})

const isRunning = ref(false)
const healthStatus = ref(null)

const API_BASE = 'http://mt5-server:8765'
const API_KEY = 'your_api_key'

async function fetchStatus() {
  try {
    const response = await fetch(`${API_BASE}/instances/${props.client.instance_name}`, {
      headers: { 'X-API-Key': API_KEY }
    })
    const data = await response.json()
    isRunning.value = data.is_running
    healthStatus.value = data.health_status
  } catch (error) {
    ElMessage.error('获取状态失败')
  }
}

async function startInstance() {
  try {
    const response = await fetch(`${API_BASE}/instances/${props.client.instance_name}/start`, {
      method: 'POST',
      headers: { 'X-API-Key': API_KEY }
    })
    const data = await response.json()
    if (data.success) {
      ElMessage.success('启动成功')
      await fetchStatus()
    } else {
      ElMessage.error('启动失败')
    }
  } catch (error) {
    ElMessage.error('操作失败')
  }
}

async function stopInstance() {
  try {
    const response = await fetch(`${API_BASE}/instances/${props.client.instance_name}/stop`, {
      method: 'POST',
      headers: { 'X-API-Key': API_KEY }
    })
    const data = await response.json()
    if (data.success) {
      ElMessage.success('停止成功')
      await fetchStatus()
    } else {
      ElMessage.error('停止失败')
    }
  } catch (error) {
    ElMessage.error('操作失败')
  }
}

async function restartInstance() {
  try {
    const response = await fetch(`${API_BASE}/instances/${props.client.instance_name}/restart`, {
      method: 'POST',
      headers: { 'X-API-Key': API_KEY }
    })
    const data = await response.json()
    if (data.success) {
      ElMessage.success('重启成功')
      await fetchStatus()
    } else {
      ElMessage.error('重启失败')
    }
  } catch (error) {
    ElMessage.error('操作失败')
  }
}

// 定时刷新状态
setInterval(fetchStatus, 30000)
fetchStatus()
</script>
```

## 测试验证

### 1. 基础功能测试

```powershell
# 测试健康检查
Invoke-RestMethod -Uri "http://localhost:8765/health"

# 测试获取实例列表（需要 API Key）
$headers = @{"X-API-Key" = "your_api_key"}
Invoke-RestMethod -Uri "http://localhost:8765/instances" -Headers $headers

# 测试启动实例
Invoke-RestMethod -Uri "http://localhost:8765/instances/bybit_system/start" `
    -Method Post -Headers $headers

# 测试获取实例状态
Invoke-RestMethod -Uri "http://localhost:8765/instances/bybit_system" -Headers $headers
```

### 2. 监控功能测试

1. 启动 Agent
2. 启动一个 MT5 实例
3. 观察日志：`Get-Content C:\MT5Agent\logs\agent.log -Tail 20 -Wait`
4. 应该看到定期的健康检查日志

### 3. 告警功能测试

1. 确保后端集成已启用
2. 手动触发高 CPU（运行密集计算）
3. 等待告警触发
4. 检查是否收到飞书通知

## 下一步工作

### 必须完成

1. **上传文件到 Windows 服务器**
   ```bash
   scp -i /c/Users/HUAWEI/.ssh/id_ed25519 d:/git/hustle2026/windows-agent/* Administrator@54.249.66.53:C:/MT5Agent/
   ```

2. **配置 Agent**
   - 编辑 `config.json`
   - 编辑 `instances.json`
   - 填入正确的账号密码

3. **测试运行**
   ```powershell
   cd C:\MT5Agent
   python main_v3.py
   ```

### 可选优化

1. **安装为 Windows 服务**
   - 使用 NSSM 安装
   - 配置自动启动
   - 配置日志轮转

2. **前端集成**
   - 在管理后台添加控制按钮
   - 显示健康状态
   - 实时刷新状态

3. **监控优化**
   - 调整监控参数
   - 添加更多监控指标
   - 优化告警策略

## 技术支持

- **完整文档**: `docs/WINDOWS_AGENT_V3_GUIDE.md`
- **API 文档**: http://localhost:8765/docs
- **日志位置**: C:\MT5Agent\logs\agent.log

---

**创建时间**: 2026-04-01
**版本**: V3.0.0
**状态**: 已完成，待部署
