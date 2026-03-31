# Windows Agent V3 部署与使用指南

## 概述

Windows Agent V3 是运行在 Windows MT5 服务器上的管理服务，提供以下功能：

1. **远程控制 MT5 实例** - 启动/停止/重启 MT5 客户端
2. **健康状态监控** - 实时监控 MT5 实例的 CPU、内存使用情况
3. **卡顿检测与告警** - 自动检测 MT5 卡顿并发送通知
4. **后端 API 集成** - 与管理后台无缝集成，支持飞书通知

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                  Windows MT5 服务器                          │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │         Windows Agent V3 (RDP 用户会话)            │    │
│  │                                                     │    │
│  │  ┌──────────────┐      ┌──────────────┐           │    │
│  │  │ MT5 控制器   │      │ 健康监控器   │           │    │
│  │  │ - 启动/停止  │      │ - CPU 监控   │           │    │
│  │  │ - 重启       │      │ - 内存监控   │           │    │
│  │  │ - 状态查询   │      │ - 卡顿检测   │           │    │
│  │  └──────┬───────┘      └──────┬───────┘           │    │
│  │         │                     │                    │    │
│  │         └─────────┬───────────┘                    │    │
│  │                   │                                │    │
│  │         ┌─────────▼─────────┐                     │    │
│  │         │   FastAPI Server   │                     │    │
│  │         │   (Port 8765)      │                     │    │
│  │         └─────────┬─────────┘                     │    │
│  └───────────────────┼───────────────────────────────┘    │
│                      │                                     │
└──────────────────────┼─────────────────────────────────────┘
                       │ HTTP API
         ┌─────────────┴─────────────┐
         │                           │
    ┌────▼────┐              ┌──────▼──────┐
    │ 管理后台 │              │ 后端 API    │
    │ (前端)  │              │ (通知服务)  │
    └─────────┘              └─────────────┘
```

## 核心特性

### 1. 远程控制功能

- **精准控制**: 按 MT5 可执行文件路径精准识别实例，避免误操作
- **多实例支持**: 支持管理多个 MT5 实例
- **灵活配置**: 支持便携模式、隐藏窗口、自动登录等选项
- **状态查询**: 实时查询实例运行状态

### 2. 健康监控功能

- **CPU 监控**: 监控 MT5 进程 CPU 使用率
- **内存监控**: 监控 MT5 进程内存使用情况
- **卡顿检测**: 通过 CPU 使用率变化检测 MT5 卡顿
- **自动告警**: 检测到异常自动发送飞书通知

### 3. 后端集成

- **API 认证**: 自动获取后端 API 访问令牌
- **通知发送**: 异常时自动发送通知到管理员
- **模板支持**: 使用后端通知模板系统

## 安装部署

### 前置要求

1. **Windows Server 2022/2025** 或 Windows 10/11
2. **Python 3.8+**
3. **RDP 用户会话** (Agent 必须在用户会话中运行)
4. **管理员权限** (用于进程管理)

### 步骤 1: 安装依赖

```powershell
# 安装 Python 依赖
pip install fastapi uvicorn psutil httpx pydantic

# 或使用 requirements.txt
pip install -r requirements.txt
```

### 步骤 2: 配置 Agent

1. 复制配置文件模板：
```powershell
cd C:\MT5Agent
copy config.example.json config.json
copy instances.example.json instances.json
```

2. 编辑 `config.json`：
```json
{
  "agent": {
    "host": "0.0.0.0",
    "port": 8765,
    "api_key": "your_secure_api_key_here"
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

3. 编辑 `instances.json`：
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
  }
}
```

### 步骤 3: 启动 Agent

**方式 1: 手动启动（测试用）**
```powershell
cd C:\MT5Agent
python main_v3.py
```

**方式 2: 开机自启动（生产环境）**

1. 创建启动脚本 `start_agent.bat`：
```bat
@echo off
cd /d C:\MT5Agent
python main_v3.py
```

2. 将快捷方式添加到启动文件夹：
```powershell
# 打开启动文件夹
shell:startup

# 创建 start_agent.bat 的快捷方式并放入启动文件夹
```

**方式 3: Windows 服务（推荐）**

使用 NSSM 安装为 Windows 服务：
```powershell
# 下载 NSSM: https://nssm.cc/download
# 安装服务
nssm install MT5Agent "C:\Python\python.exe" "C:\MT5Agent\main_v3.py"
nssm set MT5Agent AppDirectory "C:\MT5Agent"
nssm set MT5Agent DisplayName "MT5 Windows Agent V3"
nssm set MT5Agent Description "MT5 instance management and health monitoring service"
nssm set MT5Agent Start SERVICE_AUTO_START

# 启动服务
nssm start MT5Agent

# 查看服务状态
nssm status MT5Agent
```

### 步骤 4: 验证部署

1. 检查 Agent 是否运行：
```powershell
# 访问健康检查端点
Invoke-RestMethod -Uri "http://localhost:8765/health"
```

2. 访问 API 文档：
```
http://localhost:8765/docs
```

3. 测试 API（需要 API Key）：
```powershell
$headers = @{"X-API-Key" = "your_api_key"}
Invoke-RestMethod -Uri "http://localhost:8765/instances" -Headers $headers
```

## API 使用指南

### 认证

所有 API 请求（除 `/health`）都需要在 Header 中提供 API Key：
```
X-API-Key: your_api_key_here
```

### 端点列表

#### 1. 健康检查
```http
GET /health
```

响应：
```json
{
  "status": "ok",
  "agent": "MT5 Windows Agent V3",
  "version": "3.0.0",
  "session": "RDP-Tcp#2"
}
```

#### 2. 获取所有实例状态
```http
GET /instances
X-API-Key: your_api_key
```

响应：
```json
[
  {
    "instance_name": "bybit_system",
    "display_name": "Bybit System Service",
    "is_running": true,
    "health_status": {
      "instance_name": "bybit_system",
      "is_running": true,
      "is_frozen": false,
      "cpu_high": false,
      "memory_high": false,
      "details": {
        "cpu_percent": 15.2,
        "memory_mb": 256.5,
        "memory_percent": 1.2,
        "pid": 12345,
        "status": "running",
        "num_threads": 42
      }
    }
  }
]
```

#### 3. 获取单个实例状态
```http
GET /instances/{instance_name}
X-API-Key: your_api_key
```

#### 4. 创建/更新实例配置
```http
POST /instances
X-API-Key: your_api_key
Content-Type: application/json

{
  "name": "Bybit MT5-01",
  "path": "D:\\MetaTrader 5-01\\terminal64.exe",
  "account": "2325036",
  "password": "your_password",
  "server": "Bybit-Live-2",
  "is_investor": false,
  "portable": true,
  "create_no_window": false
}
```

#### 5. 启动实例
```http
POST /instances/{instance_name}/start?wait_seconds=5
X-API-Key: your_api_key
```

响应：
```json
{
  "instance_name": "bybit_system",
  "operation": "start",
  "success": true,
  "message": "Instance Bybit System Service started successfully"
}
```

#### 6. 停止实例
```http
POST /instances/{instance_name}/stop?force=true
X-API-Key: your_api_key
```

#### 7. 重启实例
```http
POST /instances/{instance_name}/restart?wait_seconds=5
X-API-Key: your_api_key
```

#### 8. 删除实例配置
```http
DELETE /instances/{instance_name}
X-API-Key: your_api_key
```

## 健康监控配置

### 监控参数说明

| 参数 | 说明 | 默认值 | 建议值 |
|------|------|--------|--------|
| `check_interval` | 检查间隔（秒） | 30 | 30-60 |
| `freeze_threshold` | 卡顿判定阈值（次数） | 10 | 5-15 |
| `cpu_threshold` | CPU 告警阈值（%） | 95 | 90-95 |
| `memory_threshold` | 内存告警阈值（%） | 90 | 85-90 |

### 卡顿检测原理

Agent 通过以下方式检测 MT5 卡顿：

1. **CPU 使用率监控**: 每个检查周期记录 CPU 使用率
2. **变化率分析**: 计算 CPU 使用率变化幅度
3. **卡顿判定**: 如果 CPU 高（>80%）但变化很小（<0.1%），累计计数
4. **告警触发**: 连续 N 次（freeze_threshold）检测到卡顿，发送告警

### 告警类型

| 告警类型 | 触发条件 | 严重程度 | 通知模板 |
|---------|---------|---------|---------|
| 实例卡顿 | 连续 N 次检测到卡顿 | Error | mt5_client_error |
| CPU 过高 | CPU > cpu_threshold | Warning | mt5_client_warning |
| 内存过高 | Memory > memory_threshold | Warning | mt5_client_warning |

## 后端集成

### 配置后端连接

在 `config.json` 中配置后端 API：
```json
{
  "backend": {
    "url": "https://admin.hustle2026.xyz",
    "username": "monitor_user",
    "password": "your_password",
    "enabled": true
  }
}
```

### 通知流程

1. Agent 检测到异常
2. 自动获取后端 API 访问令牌
3. 查询管理员用户列表
4. 调用通知 API 发送告警
5. 后端通过飞书发送通知给管理员

### 通知模板

确保后端已配置以下通知模板：
- `mt5_client_error` - 严重错误（红色卡片）
- `mt5_client_warning` - 警告（橙色卡片）
- `mt5_client_info` - 信息（蓝色卡片）

## 前端集成

### 管理后台调用示例

在管理后台的 MT5 客户端管理页面，调用 Agent API：

```javascript
// 获取实例状态
async function getInstanceStatus(instanceName) {
  const response = await fetch(`http://mt5-server:8765/instances/${instanceName}`, {
    headers: {
      'X-API-Key': 'your_api_key'
    }
  });
  return await response.json();
}

// 启动实例
async function startInstance(instanceName) {
  const response = await fetch(`http://mt5-server:8765/instances/${instanceName}/start`, {
    method: 'POST',
    headers: {
      'X-API-Key': 'your_api_key'
    }
  });
  return await response.json();
}

// 停止实例
async function stopInstance(instanceName) {
  const response = await fetch(`http://mt5-server:8765/instances/${instanceName}/stop`, {
    method: 'POST',
    headers: {
      'X-API-Key': 'your_api_key'
    }
  });
  return await response.json();
}

// 重启实例
async function restartInstance(instanceName) {
  const response = await fetch(`http://mt5-server:8765/instances/${instanceName}/restart`, {
    method: 'POST',
    headers: {
      'X-API-Key': 'your_api_key'
    }
  });
  return await response.json();
}
```

## 故障排查

### 问题 1: Agent 无法启动

**症状**: 运行 `python main_v3.py` 报错

**解决方案**:
```powershell
# 检查 Python 版本
python --version  # 需要 3.8+

# 检查依赖
pip list | Select-String "fastapi|uvicorn|psutil|httpx"

# 重新安装依赖
pip install --upgrade fastapi uvicorn psutil httpx pydantic

# 检查配置文件
Test-Path C:\MT5Agent\config.json
```

### 问题 2: API 返回 401 Unauthorized

**症状**: 调用 API 返回 401 错误

**解决方案**:
```powershell
# 检查 API Key 是否正确
$config = Get-Content C:\MT5Agent\config.json | ConvertFrom-Json
Write-Host "API Key: $($config.agent.api_key)"

# 测试正确的 API Key
$headers = @{"X-API-Key" = $config.agent.api_key}
Invoke-RestMethod -Uri "http://localhost:8765/instances" -Headers $headers
```

### 问题 3: 无法启动 MT5 实例

**症状**: 调用启动 API 返回 success=false

**解决方案**:
```powershell
# 检查 MT5 路径是否正确
$instances = Get-Content C:\MT5Agent\instances.json | ConvertFrom-Json
foreach ($instance in $instances.PSObject.Properties) {
    $path = $instance.Value.path
    Write-Host "Checking: $path"
    Test-Path $path
}

# 检查 MT5 是否已经运行
Get-Process -Name "terminal64" -ErrorAction SilentlyContinue

# 查看 Agent 日志
Get-Content C:\MT5Agent\logs\agent.log -Tail 50
```

### 问题 4: 监控不工作

**症状**: 没有收到卡顿告警

**解决方案**:
```powershell
# 检查监控是否启用
$config = Get-Content C:\MT5Agent\config.json | ConvertFrom-Json
Write-Host "Monitoring enabled: $($config.monitoring.enabled)"

# 检查后端集成是否启用
Write-Host "Backend enabled: $($config.backend.enabled)"

# 测试后端连接
$body = @{
    username = $config.backend.username
    password = $config.backend.password
} | ConvertTo-Json

Invoke-RestMethod -Uri "$($config.backend.url)/api/v1/auth/login" `
    -Method Post -Body $body -ContentType "application/json"

# 查看监控日志
Get-Content C:\MT5Agent\logs\agent.log | Select-String "monitoring|frozen|cpu|memory"
```

### 问题 5: RDP 断开后 Agent 停止

**症状**: 断开 RDP 后 Agent 和 MT5 都停止运行

**解决方案**:

使用会话保持脚本：
```bat
@echo off
echo Switching to console session...
for /f "tokens=2" %%i in ('query session ^| findstr /r /c:">rdp-tcp" /c:">console"') do set SESSION_ID=%%i
tscon %SESSION_ID% /dest:console
echo Done. You can now safely disconnect RDP.
pause
```

或配置 Windows 自动登录：
```powershell
# 设置自动登录（谨慎使用）
$RegPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
Set-ItemProperty -Path $RegPath -Name "AutoAdminLogon" -Value "1"
Set-ItemProperty -Path $RegPath -Name "DefaultUserName" -Value "Administrator"
Set-ItemProperty -Path $RegPath -Name "DefaultPassword" -Value "your_password"
```

## 安全建议

1. **API Key 保护**
   - 使用强随机 API Key
   - 定期更换 API Key
   - 不要在代码中硬编码 API Key

2. **网络隔离**
   - Agent 仅监听内网 IP
   - 使用防火墙限制访问来源
   - 不要将 Agent 暴露到公网

3. **权限控制**
   - Agent 使用专用账户运行
   - 限制账户权限（仅需进程管理权限）
   - 定期审计操作日志

4. **配置文件安全**
   - 配置文件包含敏感信息（密码）
   - 设置文件访问权限
   - 定期备份配置文件

## 性能优化

1. **监控间隔调整**
   - 生产环境建议 30-60 秒
   - 测试环境可以更频繁（10-30 秒）
   - 避免过于频繁导致性能影响

2. **日志管理**
   - 定期清理旧日志
   - 配置日志轮转
   - 监控日志文件大小

3. **资源限制**
   - Agent 本身资源占用很小（<50MB 内存，<1% CPU）
   - 监控多个实例时适当增加检查间隔
   - 避免同时启动/停止多个实例

## 更新日志

### V3.0.0 (2026-04-01)
- 整合远程控制和健康监控功能
- 添加卡顿检测和自动告警
- 集成后端 API 和通知系统
- 支持多实例管理
- 完整的 API 文档和错误处理

### V2.0.0 (2026-03-30)
- 基础远程控制功能
- 实例配置管理
- 启动/停止/重启操作

### V1.0.0 (2026-03-25)
- 初始版本
- 基本的 MT5 进程管理

## 技术支持

- **文档**: 本文档
- **API 文档**: http://localhost:8765/docs
- **日志位置**: C:\MT5Agent\logs\agent.log
- **配置文件**: C:\MT5Agent\config.json

---

**部署人员**: Claude AI Assistant
**文档版本**: V3.0.0
**更新日期**: 2026-04-01
