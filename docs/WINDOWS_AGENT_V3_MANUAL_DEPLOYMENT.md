# Windows Agent V3 手动部署指南

## 问题说明

SSH 连接到 Windows 服务器 (54.249.66.53) 不稳定，建议通过 RDP 连接后手动部署。

## 部署步骤

### 方式 1: 通过 RDP 手动部署（推荐）

#### 步骤 1: 连接到 Windows 服务器

使用 RDP 客户端连接：
- 服务器地址: `54.249.66.53`
- 用户名: `Administrator`
- 密码: [您的密码]

#### 步骤 2: 下载文件

在 Windows 服务器上，打开 PowerShell 并执行：

```powershell
# 创建目录
New-Item -ItemType Directory -Path "C:\MT5Agent" -Force
New-Item -ItemType Directory -Path "C:\MT5Agent\logs" -Force

# 下载文件（如果服务器可以访问 GitHub）
# 或者从本地复制文件
```

#### 步骤 3: 创建配置文件

**创建 config.json**:
```powershell
$configContent = @'
{
  "agent": {
    "host": "0.0.0.0",
    "port": 8765,
    "api_key": "HustleXAU_MT5_Agent_Key_2026"
  },
  "backend": {
    "url": "https://admin.hustle2026.xyz",
    "username": "monitor_user",
    "password": "your_password_here",
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
'@

Set-Content -Path "C:\MT5Agent\config.json" -Value $configContent
```

**创建 instances.json**:
```powershell
$instancesContent = @'
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
'@

Set-Content -Path "C:\MT5Agent\instances.json" -Value $instancesContent
```

#### 步骤 4: 创建 main_v3.py

由于文件较大，建议：

**选项 A**: 从本地复制
1. 在本地打开文件: `d:\git\hustle2026\windows-agent\main_v3.py`
2. 复制全部内容
3. 在服务器上创建文件: `C:\MT5Agent\main_v3.py`
4. 粘贴内容并保存

**选项 B**: 使用 PowerShell 创建（分段）

```powershell
# 由于文件太大，建议使用选项 A
# 或者通过网络共享/U盘等方式传输
```

#### 步骤 5: 安装 Python 依赖

```powershell
# 检查 Python 版本
python --version

# 安装依赖
pip install fastapi==0.109.0
pip install uvicorn[standard]==0.27.0
pip install psutil==5.9.8
pip install httpx==0.26.0
pip install pydantic==2.5.3
pip install python-multipart==0.0.6
```

#### 步骤 6: 测试运行

```powershell
cd C:\MT5Agent
python main_v3.py
```

应该看到类似输出：
```
============================================================
MT5 Windows Agent V3 Starting...
Listen: http://0.0.0.0:8765
API Docs: http://0.0.0.0:8765/docs
Monitoring: Enabled
Backend Integration: Enabled
============================================================
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8765
```

#### 步骤 7: 测试 API

打开另一个 PowerShell 窗口：

```powershell
# 测试健康检查
Invoke-RestMethod -Uri "http://localhost:8765/health"

# 测试获取实例列表（需要 API Key）
$headers = @{"X-API-Key" = "HustleXAU_MT5_Agent_Key_2026"}
Invoke-RestMethod -Uri "http://localhost:8765/instances" -Headers $headers
```

#### 步骤 8: 配置为 Windows 服务（可选）

**使用 NSSM**:

1. 下载 NSSM: https://nssm.cc/download
2. 解压到 `C:\Tools\nssm.exe`
3. 安装服务：

```powershell
# 安装服务
C:\Tools\nssm.exe install MT5AgentV3 "C:\Python\python.exe" "C:\MT5Agent\main_v3.py"

# 配置服务
C:\Tools\nssm.exe set MT5AgentV3 AppDirectory "C:\MT5Agent"
C:\Tools\nssm.exe set MT5AgentV3 DisplayName "MT5 Windows Agent V3"
C:\Tools\nssm.exe set MT5AgentV3 Description "MT5 instance management and health monitoring"
C:\Tools\nssm.exe set MT5AgentV3 Start SERVICE_AUTO_START

# 配置日志
C:\Tools\nssm.exe set MT5AgentV3 AppStdout "C:\MT5Agent\logs\service_stdout.log"
C:\Tools\nssm.exe set MT5AgentV3 AppStderr "C:\MT5Agent\logs\service_stderr.log"

# 启动服务
C:\Tools\nssm.exe start MT5AgentV3

# 查看服务状态
Get-Service -Name MT5AgentV3
```

### 方式 2: 通过本地文件共享

如果 RDP 支持文件共享：

1. 在 RDP 连接设置中启用"本地资源" → "本地设备和资源" → "驱动器"
2. 连接后，在服务器上访问 `\\tsclient\C\git\hustle2026\windows-agent\`
3. 复制所有文件到 `C:\MT5Agent\`

### 方式 3: 使用 GitHub（如果服务器可以访问）

```powershell
# 克隆仓库
cd C:\
git clone https://github.com/your-repo/hustle2026.git

# 复制文件
Copy-Item -Path "C:\hustle2026\windows-agent\*" -Destination "C:\MT5Agent\" -Recurse
```

## 验证部署

### 1. 检查文件

```powershell
Get-ChildItem C:\MT5Agent\

# 应该看到：
# main_v3.py
# config.json
# instances.json
# logs\ (目录)
```

### 2. 测试 API

```powershell
# 健康检查
Invoke-RestMethod -Uri "http://localhost:8765/health"

# 获取实例状态
$headers = @{"X-API-Key" = "HustleXAU_MT5_Agent_Key_2026"}
Invoke-RestMethod -Uri "http://localhost:8765/instances" -Headers $headers
```

### 3. 测试启动 MT5

```powershell
# 启动实例
$headers = @{"X-API-Key" = "HustleXAU_MT5_Agent_Key_2026"}
Invoke-RestMethod -Uri "http://localhost:8765/instances/bybit_system/start" `
    -Method Post -Headers $headers

# 检查状态
Invoke-RestMethod -Uri "http://localhost:8765/instances/bybit_system" -Headers $headers
```

## 前端集成

### 后端 API 代理配置

在后端添加代理路由，避免前端直接访问 Windows 服务器：

**backend/app/api/v1/mt5_agent.py** (新建文件):

```python
"""MT5 Agent 代理 API"""
from fastapi import APIRouter, HTTPException, Depends
from app.core.security import get_current_user
import httpx
import os

router = APIRouter()

MT5_AGENT_URL = os.getenv("MT5_AGENT_URL", "http://172.31.14.113:8765")
MT5_AGENT_API_KEY = os.getenv("MT5_AGENT_API_KEY", "HustleXAU_MT5_Agent_Key_2026")

async def call_agent_api(method: str, path: str, **kwargs):
    """调用 Agent API"""
    headers = {"X-API-Key": MT5_AGENT_API_KEY}
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=method,
            url=f"{MT5_AGENT_URL}{path}",
            headers=headers,
            timeout=30.0,
            **kwargs
        )
        return response.json()

@router.get("/instances")
async def get_instances(current_user: dict = Depends(get_current_user)):
    """获取所有 MT5 实例状态"""
    return await call_agent_api("GET", "/instances")

@router.get("/instances/{instance_name}")
async def get_instance(instance_name: str, current_user: dict = Depends(get_current_user)):
    """获取单个实例状态"""
    return await call_agent_api("GET", f"/instances/{instance_name}")

@router.post("/instances/{instance_name}/start")
async def start_instance(instance_name: str, current_user: dict = Depends(get_current_user)):
    """启动实例"""
    if current_user["role"] not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(403, "需要管理员权限")
    return await call_agent_api("POST", f"/instances/{instance_name}/start")

@router.post("/instances/{instance_name}/stop")
async def stop_instance(instance_name: str, current_user: dict = Depends(get_current_user)):
    """停止实例"""
    if current_user["role"] not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(403, "需要管理员权限")
    return await call_agent_api("POST", f"/instances/{instance_name}/stop")

@router.post("/instances/{instance_name}/restart")
async def restart_instance(instance_name: str, current_user: dict = Depends(get_current_user)):
    """重启实例"""
    if current_user["role"] not in ["超级管理员", "系统管理员", "管理员"]:
        raise HTTPException(403, "需要管理员权限")
    return await call_agent_api("POST", f"/instances/{instance_name}/restart")
```

**注册路由** (backend/app/main.py):

```python
from app.api.v1 import mt5_agent

app.include_router(mt5_agent.router, prefix="/api/v1/mt5-agent", tags=["MT5 Agent"])
```

### 前端组件

**frontend/src-admin/views/UserManagement.vue** (在 MT5 客户端卡片中添加):

```vue
<template>
  <el-card class="mt5-client-card">
    <template #header>
      <div class="card-header">
        <span>{{ client.client_name }}</span>
        <el-tag :type="statusTagType">{{ statusText }}</el-tag>
      </div>
    </template>

    <div class="client-info">
      <p><strong>账号:</strong> {{ client.mt5_login }}</p>
      <p><strong>服务器:</strong> {{ client.mt5_server }}</p>
      <p><strong>路径:</strong> {{ client.mt5_path }}</p>
    </div>

    <!-- 健康状态 -->
    <div v-if="healthStatus" class="health-status">
      <el-divider>健康状态</el-divider>
      <div class="health-metrics">
        <div class="metric">
          <span>CPU:</span>
          <el-progress
            :percentage="healthStatus.details?.cpu_percent || 0"
            :status="healthStatus.cpu_high ? 'exception' : 'success'"
          />
        </div>
        <div class="metric">
          <span>内存:</span>
          <el-progress
            :percentage="healthStatus.details?.memory_percent || 0"
            :status="healthStatus.memory_high ? 'exception' : 'success'"
          />
        </div>
        <el-tag v-if="healthStatus.is_frozen" type="danger" effect="dark">
          ⚠️ 检测到卡顿
        </el-tag>
      </div>
    </div>

    <!-- 控制按钮 -->
    <div class="control-buttons">
      <el-button
        type="success"
        :icon="VideoPlay"
        :disabled="isRunning || loading"
        :loading="loading === 'start'"
        @click="handleStart">
        启动
      </el-button>
      <el-button
        type="danger"
        :icon="VideoPause"
        :disabled="!isRunning || loading"
        :loading="loading === 'stop'"
        @click="handleStop">
        停止
      </el-button>
      <el-button
        type="warning"
        :icon="RefreshRight"
        :disabled="!isRunning || loading"
        :loading="loading === 'restart'"
        @click="handleRestart">
        重启
      </el-button>
      <el-button
        :icon="Refresh"
        :disabled="loading"
        @click="fetchStatus">
        刷新
      </el-button>
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { VideoPlay, VideoPause, RefreshRight, Refresh } from '@element-plus/icons-vue'
import api from '@/utils/api'

const props = defineProps({
  client: {
    type: Object,
    required: true
  }
})

const isRunning = ref(false)
const healthStatus = ref(null)
const loading = ref(null)
let refreshTimer = null

const statusText = computed(() => {
  if (loading.value) return '操作中...'
  return isRunning.value ? '运行中' : '已停止'
})

const statusTagType = computed(() => {
  if (loading.value) return 'info'
  return isRunning.value ? 'success' : 'info'
})

// 获取实例名称（从 client_name 转换）
const instanceName = computed(() => {
  return props.client.client_name.toLowerCase().replace(/[^a-z0-9]/g, '_')
})

async function fetchStatus() {
  try {
    const response = await api.get(`/api/v1/mt5-agent/instances/${instanceName.value}`)
    isRunning.value = response.is_running
    healthStatus.value = response.health_status
  } catch (error) {
    console.error('Failed to fetch status:', error)
  }
}

async function handleStart() {
  try {
    await ElMessageBox.confirm(
      `确定要启动 ${props.client.client_name} 吗？`,
      '确认启动',
      { type: 'warning' }
    )

    loading.value = 'start'
    const response = await api.post(`/api/v1/mt5-agent/instances/${instanceName.value}/start`)

    if (response.success) {
      ElMessage.success('启动成功')
      await fetchStatus()
    } else {
      ElMessage.error(`启动失败: ${response.message}`)
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('启动失败')
    }
  } finally {
    loading.value = null
  }
}

async function handleStop() {
  try {
    await ElMessageBox.confirm(
      `确定要停止 ${props.client.client_name} 吗？`,
      '确认停止',
      { type: 'warning' }
    )

    loading.value = 'stop'
    const response = await api.post(`/api/v1/mt5-agent/instances/${instanceName.value}/stop`)

    if (response.success) {
      ElMessage.success('停止成功')
      await fetchStatus()
    } else {
      ElMessage.error(`停止失败: ${response.message}`)
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('停止失败')
    }
  } finally {
    loading.value = null
  }
}

async function handleRestart() {
  try {
    await ElMessageBox.confirm(
      `确定要重启 ${props.client.client_name} 吗？`,
      '确认重启',
      { type: 'warning' }
    )

    loading.value = 'restart'
    const response = await api.post(`/api/v1/mt5-agent/instances/${instanceName.value}/restart`)

    if (response.success) {
      ElMessage.success('重启成功')
      await fetchStatus()
    } else {
      ElMessage.error(`重启失败: ${response.message}`)
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('重启失败')
    }
  } finally {
    loading.value = null
  }
}

onMounted(() => {
  fetchStatus()
  // 每 30 秒自动刷新状态
  refreshTimer = setInterval(fetchStatus, 30000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>

<style scoped>
.mt5-client-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.client-info {
  margin-bottom: 16px;
}

.client-info p {
  margin: 8px 0;
}

.health-status {
  margin: 16px 0;
}

.health-metrics {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.metric {
  display: flex;
  align-items: center;
  gap: 12px;
}

.metric span {
  min-width: 60px;
  font-weight: 500;
}

.control-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
```

## 故障排查

### 问题 1: Python 依赖安装失败

```powershell
# 升级 pip
python -m pip install --upgrade pip

# 使用国内镜像
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple fastapi uvicorn psutil httpx pydantic
```

### 问题 2: 端口被占用

```powershell
# 检查端口占用
netstat -ano | findstr :8765

# 结束占用进程
taskkill /PID <进程ID> /F
```

### 问题 3: Agent 无法启动 MT5

```powershell
# 检查 MT5 路径
Test-Path "C:\Program Files\MetaTrader 5\terminal64.exe"

# 手动测试启动
& "C:\Program Files\MetaTrader 5\terminal64.exe" /portable

# 查看 Agent 日志
Get-Content C:\MT5Agent\logs\agent.log -Tail 50
```

## 下一步

1. ✅ 在 Windows 服务器上部署 Agent
2. ✅ 测试 API 功能
3. ⏳ 在后端添加代理 API
4. ⏳ 在前端添加控制组件
5. ⏳ 测试端到端功能

---

**创建时间**: 2026-04-01
**文档版本**: 1.0
