# Windows Agent V3 部署报告

**部署时间**: 2026-03-31
**服务器**: 54.249.66.53 (Windows Server)
**状态**: ✅ 部署成功，需配置 AWS 安全组

---

## 部署摘要

### ✅ 已完成项目

1. **文件部署**
   - ✅ `C:\hustle-agent\main_v3.py` - Agent 主程序
   - ✅ `C:\hustle-agent\config.json` - 配置文件（已修正格式）
   - ✅ `C:\hustle-agent\instances.json` - MT5 实例配置（已修正格式）
   - ✅ `C:\hustle-agent\requirements.txt` - Python 依赖列表

2. **依赖安装**
   - ✅ fastapi==0.109.0
   - ✅ uvicorn==0.27.0
   - ✅ psutil==5.9.8
   - ✅ httpx==0.26.0
   - ✅ pydantic==2.5.3
   - ✅ python-multipart==0.0.6

3. **网络配置**
   - ✅ Windows 防火墙规则已添加（端口 8765）
   - ✅ Agent 监听 0.0.0.0:8765

4. **进程状态**
   - ✅ Agent 进程正在运行
   - ✅ 本地测试通过：`http://localhost:8765/health` 返回正常

---

## 配置详情

### Agent 配置 (config.json)
```json
{
  "agent": {
    "host": "0.0.0.0",
    "port": 8765,
    "api_key": "hustle2026_mt5_agent_secure_key_2024"
  },
  "backend": {
    "url": "https://admin.hustle2026.xyz",
    "username": "admin",
    "password": "Hustle@2026"
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

### MT5 实例配置 (instances.json)
```json
{
  "bybit_system_service": {
    "path": "C:\\Program Files\\Bybit MT5\\terminal64.exe",
    "account": "3971962",
    "password": "Bybit@2024",
    "server": "Bybit-Live-2",
    "portable_mode": false
  }
}
```

---

## 测试结果

### ✅ 本地测试（Windows 服务器内部）
```powershell
Invoke-RestMethod -Uri 'http://localhost:8765/health' -Headers @{'X-API-Key'='hustle2026_mt5_agent_secure_key_2024'}
```
**结果**: 成功
```
status agent                version session
------ -----                ------- -------
ok     MT5 Windows Agent V3 3.0.0   Unknown
```

### ❌ 外部访问测试（从 VPC 内部）
```bash
curl -H "X-API-Key: hustle2026_mt5_agent_secure_key_2024" http://172.31.14.113:8765/health
```
**结果**: 连接被重置（Connection was reset）

---

## 🔴 待解决问题

### 问题：无法从外部访问 Agent API

**症状**:
- 本地访问（localhost:8765）正常
- VPC 内部访问（172.31.14.113:8765）连接被重置
- Windows 防火墙规则已添加
- 端口正在监听（netstat 确认）

**根本原因**: AWS EC2 安全组未开放端口 8765

**解决方案**: 在 AWS 控制台配置安全组

---

## 📋 后续步骤

### 步骤 1: 配置 AWS 安全组

1. 登录 AWS 控制台
2. 进入 EC2 → 实例 → 选择 Windows MT5 服务器（54.249.66.53）
3. 点击「安全」标签 → 点击安全组
4. 添加入站规则：
   - **类型**: 自定义 TCP
   - **端口范围**: 8765
   - **源**: 172.31.0.0/16（VPC 内部）或后端服务器的私有 IP
   - **描述**: Hustle MT5 Agent API

### 步骤 2: 配置后端环境变量

SSH 连接到后端服务器：
```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@go.hustle2026.xyz
cd /home/ubuntu/hustle2026/backend
nano .env
```

添加以下配置：
```bash
# MT5 Windows Agent Configuration
MT5_AGENT_URL=http://172.31.14.113:8765
MT5_AGENT_API_KEY=hustle2026_mt5_agent_secure_key_2024
```

重启后端服务：
```bash
sudo systemctl restart hustle-backend
sudo systemctl status hustle-backend
```

### 步骤 3: 部署前端代码

前端代码已提交到 `go` 分支，需要部署：

```bash
# 在后端服务器上
cd /home/ubuntu/hustle2026/frontend
git fetch origin
git checkout go
git pull origin go
npm run build:admin
```

### 步骤 4: 验证端到端功能

1. **测试后端代理 API**:
```bash
TOKEN=$(curl -s -X POST https://admin.hustle2026.xyz/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Hustle@2026"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -H "Authorization: Bearer $TOKEN" \
  https://admin.hustle2026.xyz/api/v1/mt5-agent/instances
```

2. **测试前端界面**:
   - 访问：https://admin.hustle2026.xyz/users
   - 切换到「MT5账户管理」标签
   - 选择用户和账户
   - 查看 MT5 客户端卡片中的「控制 MT5 服务器」区域
   - 测试启动/停止/重启按钮

### 步骤 5: 配置 Agent 自动启动（可选）

当前 Agent 作为后台进程运行，服务器重启后需要手动启动。建议配置自动启动：

**方法 A: 使用任务计划程序**
```powershell
$action = New-ScheduledTaskAction -Execute 'python.exe' -Argument 'C:\hustle-agent\main_v3.py' -WorkingDirectory 'C:\hustle-agent'
$trigger = New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Seconds 30)
$principal = New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName 'HustleMT5Agent' -Action $action -Trigger $trigger -Principal $principal -Force
```

**方法 B: 等待服务器重启后重新安装 NSSM 服务**
（当前 HustleAgent 服务已标记为删除，需要重启后才能重新创建）

---

## API 端点

### Windows Agent 端点（内部访问）
- **Base URL**: http://172.31.14.113:8765
- **认证**: Header `X-API-Key: hustle2026_mt5_agent_secure_key_2024`

主要端点：
- `GET /health` - 健康检查
- `GET /instances` - 获取所有 MT5 实例状态
- `POST /instances/{name}/start` - 启动 MT5 实例
- `POST /instances/{name}/stop` - 停止 MT5 实例
- `POST /instances/{name}/restart` - 重启 MT5 实例

### 后端代理端点（外部访问）
- **Base URL**: https://admin.hustle2026.xyz/api/v1/mt5-agent
- **认证**: Bearer Token（需要管理员权限）

主要端点：
- `GET /instances` - 获取所有 MT5 实例状态
- `POST /instances/{name}/start` - 启动 MT5 实例
- `POST /instances/{name}/stop` - 停止 MT5 实例
- `POST /instances/{name}/restart` - 重启 MT5 实例

---

## 故障排查

### Agent 无法启动
```powershell
# 检查进程
Get-Process python | Where-Object {$_.Path -like "*hustle-agent*"}

# 手动运行查看错误
cd C:\hustle-agent
python main_v3.py
```

### 配置文件格式错误
```powershell
# 验证 JSON 格式
python -c "import json; print(json.load(open('config.json')))"
python -c "import json; print(json.load(open('instances.json')))"
```

### 端口被占用
```cmd
netstat -ano | findstr :8765
taskkill /F /PID <进程ID>
```

### 防火墙问题
```powershell
# 检查防火墙规则
Get-NetFirewallRule -DisplayName "Hustle Agent"

# 重新添加规则
New-NetFirewallRule -DisplayName "Hustle Agent" -Direction Inbound -LocalPort 8765 -Protocol TCP -Action Allow
```

---

## 文件位置

### Windows 服务器
- Agent 目录: `C:\hustle-agent\`
- 主程序: `C:\hustle-agent\main_v3.py`
- 配置文件: `C:\hustle-agent\config.json`
- 实例配置: `C:\hustle-agent\instances.json`

### 后端服务器
- API 代理: `/home/ubuntu/hustle2026/backend/app/api/v1/mt5_agent.py`
- 环境变量: `/home/ubuntu/hustle2026/backend/.env`

### 前端代码
- 控制组件: `frontend/src-admin/components/MT5ControlCard.vue`
- 用户管理页面: `frontend/src-admin/views/UserManagement.vue`

---

## 安全注意事项

1. **API Key 保护**:
   - API Key 已配置在 config.json 和后端 .env 中
   - 确保这些文件权限正确，不被未授权访问

2. **网络隔离**:
   - Agent API 仅在 VPC 内部访问
   - 不要将端口 8765 暴露到公网

3. **密码安全**:
   - MT5 密码存储在 instances.json 中
   - 考虑使用加密存储或环境变量

4. **权限控制**:
   - 后端 API 已实现管理员权限检查
   - 只有管理员角色可以控制 MT5 实例

---

## 总结

✅ **已完成**:
- Windows Agent V3 成功部署到 MT5 服务器
- 本地测试通过，Agent 运行正常
- 后端 API 代理已集成
- 前端控制组件已开发并集成
- 代码已提交到 `go` 分支

🔴 **待完成**:
- 配置 AWS 安全组开放端口 8765
- 配置后端环境变量
- 部署前端代码
- 端到端功能测试

⏱️ **预计完成时间**: 10-15 分钟（主要是 AWS 配置和部署）

---

**下一步行动**: 请配置 AWS 安全组，然后我们可以继续完成后端和前端的部署。
