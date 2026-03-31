# MT5 Windows Agent 集成指南

## 概述

本指南说明如何将 Windows Agent V3 集成到 Hustle2026 系统中，实现从管理后台远程控制 MT5 客户端的启动/停止/重启功能，以及 MT5 客户端健康监控和告警功能。

## 架构说明

```
┌─────────────────┐      ┌─────────────────┐      ┌──────────────────┐
│  管理后台前端    │─────▶│  Backend API    │─────▶│  Windows Agent   │
│  UserManagement │ HTTPS │  mt5_agent.py   │ HTTP │  main_v3.py      │
│  MT5ControlCard │      │  (Proxy)        │      │  (FastAPI)       │
└─────────────────┘      └─────────────────┘      └──────────────────┘
                                                            │
                                                            ▼
                                                   ┌──────────────────┐
                                                   │  MT5 Instances   │
                                                   │  (GUI Process)   │
                                                   └──────────────────┘
```

## 已完成的集成步骤

### 1. 后端 API 集成 ✅

**文件**: `backend/app/api/v1/mt5_agent.py`

已创建后端代理 API，提供以下端点：
- `GET /api/v1/mt5-agent/instances` - 获取所有 MT5 实例状态
- `POST /api/v1/mt5-agent/instances/{instance_name}/start` - 启动 MT5 实例
- `POST /api/v1/mt5-agent/instances/{instance_name}/stop` - 停止 MT5 实例
- `POST /api/v1/mt5-agent/instances/{instance_name}/restart` - 重启 MT5 实例

**文件**: `backend/app/main.py`

已注册路由：
```python
from app.api.v1 import ..., mt5_agent
app.include_router(mt5_agent.router, prefix="/api/v1/mt5-agent", tags=["MT5 Agent控制"])
```

### 2. 前端组件集成 ✅

**文件**: `frontend/src-admin/components/MT5ControlCard.vue`

已创建 Vue 3 组件，提供：
- 实时状态显示（运行/停止/冻结）
- 健康指标可视化（CPU/内存使用率）
- 控制按钮（启动/停止/重启）
- 告警指示器（冻结/高 CPU/高内存）
- 自动刷新（30秒）

**文件**: `frontend/src-admin/views/UserManagement.vue`

已集成组件：
```vue
import MT5ControlCard from '@/components/MT5ControlCard.vue'

<!-- 在 MT5 客户端卡片中 -->
<MT5ControlCard :client="client" />
```

### 3. 环境变量配置 ✅

**文件**: `backend/.env.example`

已添加配置项：
```bash
# MT5 Windows Agent Configuration
MT5_AGENT_URL=http://172.31.14.113:8765
MT5_AGENT_API_KEY=your_secure_api_key_here
```

## 待完成的部署步骤

### 步骤 1: 部署 Windows Agent 到 MT5 服务器

由于 SSH 连接不稳定，需要通过 RDP 手动部署。

#### 方法 A: RDP 手动部署（推荐）

1. 通过 RDP 连接到 Windows 服务器：
   ```
   服务器: 54.249.66.53
   用户: Administrator
   ```

2. 打开 PowerShell（管理员权限），执行以下命令创建目录结构：
   ```powershell
   # 创建目录
   New-Item -ItemType Directory -Force -Path "C:\hustle-agent"
   Set-Location "C:\hustle-agent"
   ```

3. 创建 `main_v3.py` 文件：
   - 内容见：`d:\git\hustle2026\windows-agent\main_v3.py`
   - 或访问：`d:\git\hustle2026\docs\WINDOWS_AGENT_V3_MANUAL_DEPLOYMENT.md` 中的完整代码

4. 创建 `config.json` 文件：
   ```json
   {
     "agent": {
       "host": "0.0.0.0",
       "port": 8765,
       "api_key": "your_secure_api_key_here"
     },
     "backend": {
       "url": "https://admin.hustle2026.xyz",
       "username": "admin",
       "password": "your_admin_password"
     },
     "monitoring": {
       "enabled": true,
       "interval_seconds": 30,
       "cpu_threshold": 95.0,
       "memory_threshold": 90.0,
       "freeze_check_count": 10
     }
   }
   ```

5. 创建 `instances.json` 文件：
   ```json
   {
     "bybit_system_service": {
       "path": "C:\\Program Files\\Bybit MT5\\terminal64.exe",
       "account": "3971962",
       "password": "your_password",
       "server": "Bybit-Live-2",
       "portable_mode": false
     }
   }
   ```

6. 创建 `requirements.txt` 文件：
   ```
   fastapi==0.104.1
   uvicorn[standard]==0.24.0
   psutil==5.9.6
   httpx==0.25.1
   pydantic==2.5.0
   ```

7. 安装依赖：
   ```powershell
   python -m pip install -r requirements.txt
   ```

8. 测试运行：
   ```powershell
   python main_v3.py
   ```

9. 使用 NSSM 安装为 Windows 服务：
   ```powershell
   # 下载 NSSM
   Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "nssm.zip"
   Expand-Archive -Path "nssm.zip" -DestinationPath "."

   # 安装服务
   .\nssm-2.24\win64\nssm.exe install HustleAgent "C:\Python39\python.exe" "C:\hustle-agent\main_v3.py"
   .\nssm-2.24\win64\nssm.exe set HustleAgent AppDirectory "C:\hustle-agent"
   .\nssm-2.24\win64\nssm.exe set HustleAgent DisplayName "Hustle MT5 Agent"
   .\nssm-2.24\win64\nssm.exe set HustleAgent Description "MT5 remote control and health monitoring agent"
   .\nssm-2.24\win64\nssm.exe set HustleAgent Start SERVICE_AUTO_START

   # 启动服务
   .\nssm-2.24\win64\nssm.exe start HustleAgent
   ```

#### 方法 B: 使用文件共享

详见：`d:\git\hustle2026\docs\WINDOWS_AGENT_V3_MANUAL_DEPLOYMENT.md`

#### 方法 C: 通过 GitHub

详见：`d:\git\hustle2026\docs\WINDOWS_AGENT_V3_MANUAL_DEPLOYMENT.md`

### 步骤 2: 配置后端环境变量

1. SSH 连接到后端服务器：
   ```bash
   ssh -i ~/.ssh/id_ed25519 ubuntu@go.hustle2026.xyz
   ```

2. 编辑环境变量文件：
   ```bash
   cd /home/ubuntu/hustle2026/backend
   nano .env
   ```

3. 添加以下配置：
   ```bash
   # MT5 Windows Agent Configuration
   MT5_AGENT_URL=http://172.31.14.113:8765
   MT5_AGENT_API_KEY=your_secure_api_key_here
   ```

   **注意**: `MT5_AGENT_API_KEY` 必须与 Windows Agent 的 `config.json` 中的 `api_key` 一致。

4. 重启后端服务：
   ```bash
   sudo systemctl restart hustle-backend
   sudo systemctl status hustle-backend
   ```

### 步骤 3: 部署前端代码

1. 提交代码到 Git：
   ```bash
   cd d:\git\hustle2026
   git add .
   git commit -m "集成 MT5 Windows Agent 控制功能"
   git push origin main
   ```

2. SSH 连接到前端服务器并拉取代码：
   ```bash
   ssh -i ~/.ssh/id_ed25519 ubuntu@go.hustle2026.xyz
   cd /home/ubuntu/hustle2026/frontend
   git pull origin main
   ```

3. 构建前端：
   ```bash
   npm run build:admin
   ```

4. Nginx 会自动服务新的静态文件，无需重启。

### 步骤 4: 验证功能

1. **验证 Windows Agent 运行状态**：
   ```powershell
   # 在 Windows 服务器上
   Get-Service HustleAgent

   # 测试 API
   Invoke-WebRequest -Uri "http://localhost:8765/health" -Headers @{"X-API-Key"="your_secure_api_key_here"}
   ```

2. **验证后端代理 API**：
   ```bash
   # 获取访问令牌
   TOKEN=$(curl -s -X POST https://admin.hustle2026.xyz/api/v1/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"your_password"}' \
     | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

   # 测试获取实例状态
   curl -H "Authorization: Bearer $TOKEN" \
     https://admin.hustle2026.xyz/api/v1/mt5-agent/instances
   ```

3. **验证前端功能**：
   - 访问：https://admin.hustle2026.xyz/users
   - 切换到「MT5账户管理」标签
   - 选择用户和账户
   - 在 MT5 客户端卡片中查看「控制 MT5 服务器」区域
   - 测试启动/停止/重启按钮
   - 观察实时状态和健康指标

## 功能说明

### 远程控制功能

- **启动**: 启动 MT5 客户端进程，自动登录账户
- **停止**: 优雅关闭 MT5 客户端（保存数据）
- **重启**: 先停止再启动，等待 5 秒确保完全关闭

### 健康监控功能

- **CPU 监控**: 实时显示 CPU 使用率，超过 95% 触发告警
- **内存监控**: 实时显示内存使用量，超过 90% 触发告警
- **冻结检测**: 检测 MT5 是否卡顿（CPU 高但无变化），连续 10 次检测到冻结触发告警
- **自动告警**: 通过后端通知系统发送飞书告警

### 安全机制

- **API Key 认证**: 所有请求需要提供有效的 API Key
- **权限控制**: 只有管理员角色可以执行控制操作
- **代理模式**: 前端不直接访问 Windows Agent，通过后端代理
- **日志记录**: 所有操作都有详细日志

## 故障排查

### Windows Agent 无法启动

1. 检查 Python 版本（需要 3.8+）：
   ```powershell
   python --version
   ```

2. 检查依赖是否安装：
   ```powershell
   python -m pip list | Select-String "fastapi|uvicorn|psutil|httpx"
   ```

3. 检查配置文件格式：
   ```powershell
   python -c "import json; print(json.load(open('config.json')))"
   ```

4. 查看服务日志：
   ```powershell
   Get-EventLog -LogName Application -Source "HustleAgent" -Newest 50
   ```

### 后端无法连接 Windows Agent

1. 检查网络连通性：
   ```bash
   curl -v http://172.31.14.113:8765/health
   ```

2. 检查防火墙规则：
   ```powershell
   # 在 Windows 服务器上
   Get-NetFirewallRule | Where-Object {$_.DisplayName -like "*8765*"}
   ```

3. 检查 API Key 是否匹配：
   ```bash
   # 后端 .env 中的 MT5_AGENT_API_KEY
   # Windows Agent config.json 中的 agent.api_key
   ```

### 前端显示连接失败

1. 检查后端日志：
   ```bash
   sudo journalctl -u hustle-backend -n 100 | grep -i "mt5-agent"
   ```

2. 检查浏览器控制台错误

3. 验证用户权限（需要管理员角色）

## 相关文档

- [Windows Agent V3 完整指南](./WINDOWS_AGENT_V3_GUIDE.md)
- [Windows Agent V3 手动部署指南](./WINDOWS_AGENT_V3_MANUAL_DEPLOYMENT.md)
- [Windows Agent V3 部署摘要](./WINDOWS_AGENT_V3_DEPLOYMENT_SUMMARY.md)

## 技术支持

如遇问题，请检查：
1. Windows Agent 服务状态
2. 后端服务日志
3. 网络连通性
4. API Key 配置
5. 用户权限设置
