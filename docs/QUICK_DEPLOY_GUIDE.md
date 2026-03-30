# MT5 状态优化功能 - 快速部署指南

## 概述

所有代码已提交到 **`go` 分支**，包括：
- 后端优化（MT5SyncService、增强的 monitor/status 端点）
- 前端优化（MasterDashboard、UserManagement）
- Windows Agent 健康检查端点
- 部署和测试脚本

## 部署步骤

### 步骤 1: 部署后端和前端（Ubuntu 服务器）

```bash
# SSH 连接到服务器
ssh ubuntu@go.hustle2026.xyz

# 下载并执行部署脚本
cd /home/ubuntu/hustle2026
git fetch origin
git checkout go
git pull origin go

# 执行部署脚本
bash scripts/deploy_mt5_optimization.sh
```

**或者手动执行**：

```bash
# 1. 拉取代码
cd /home/ubuntu/hustle2026
git fetch origin && git checkout go && git pull origin go

# 2. 重启后端
sudo systemctl restart hustle-backend

# 3. 检查日志
sudo journalctl -u hustle-backend -n 50 | grep -i "mt5.*sync"

# 4. 构建前端
cd frontend
npm run build:admin

# 5. 部署前端
sudo cp -r dist-admin/* /var/www/admin.hustle2026.xyz/
```

---

### 步骤 2: 重启 Windows Agent（Windows 服务器）

```powershell
# 方法 1: 使用脚本（推荐）
# 从 Git 仓库下载脚本到 Windows 服务器
# 然后执行：
powershell -ExecutionPolicy Bypass -File C:\MT5Agent\restart_windows_agent.ps1

# 方法 2: 手动执行
# 停止进程
Stop-Process -Name python -Force -ErrorAction SilentlyContinue

# 等待 2 秒
Start-Sleep -Seconds 2

# 启动 Agent
Start-Process -FilePath "python" -ArgumentList "C:\MT5Agent\main.py" -WorkingDirectory "C:\MT5Agent" -WindowStyle Hidden

# 验证
Invoke-WebRequest -Uri "http://localhost:9000/" -UseBasicParsing
```

---

### 步骤 3: 测试功能

#### 3.1 自动测试（推荐）

```powershell
# 在本地 Windows 机器上执行
powershell -ExecutionPolicy Bypass -File d:\git\hustle2026\scripts\test_mt5_optimization.ps1
```

#### 3.2 手动测试

**测试后端 API**：

```bash
# 获取 Token
TOKEN=$(curl -s -X POST https://admin.hustle2026.xyz/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your_password"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 测试 monitor/status 端点
curl -H "Authorization: Bearer $TOKEN" \
  https://admin.hustle2026.xyz/api/v1/monitor/status | jq '.mt5_clients'
```

**测试 Windows Agent**：

```bash
# 测试基本端点
curl http://54.249.66.53:9000/

# 测试健康检查端点（假设 8001 端口有实例）
curl http://54.249.66.53:9000/instances/8001/health
```

**测试前端功能**：

1. 访问 https://admin.hustle2026.xyz/
2. 展开 "MT5 客户端状态" 面板
3. 检查是否显示：
   - ✅ 进程状态（运行中/已停止）
   - ✅ 最后心跳时间（如：2分钟前）
   - ✅ 重启和详情按钮
4. 打开浏览器开发者工具 Network 面板
5. 观察是否每 5 秒请求一次 `/api/v1/monitor/status`
6. 访问 https://admin.hustle2026.xyz/users
7. 切换到 "MT5客户端" tab
8. 点击实例的"重启"按钮
9. 观察控制台是否显示：
   - `Started fast polling (3s interval)`
   - `Stopped fast polling`

---

## 验证清单

### 后端验证

- [ ] 后端服务正常启动
- [ ] MT5SyncService 日志显示正常运行
- [ ] `/api/v1/monitor/status` 返回 `mt5_clients` 数组
- [ ] `mt5_clients` 包含 `process_running` 字段
- [ ] `mt5_clients` 包含 `last_connected_at` 字段

### Windows Agent 验证

- [ ] Agent 服务正常响应
- [ ] `/instances/{port}/health` 端点正常工作
- [ ] 健康检查返回 `running` 和 `mt5_connected` 字段

### 前端验证

- [ ] MasterDashboard 每 5 秒刷新 MT5 状态
- [ ] MasterDashboard 显示进程运行状态
- [ ] MasterDashboard 显示最后心跳时间
- [ ] MasterDashboard 控制按钮可点击
- [ ] UserManagement 操作时启动 3 秒轮询
- [ ] UserManagement 操作完成后停止轮询

---

## 故障排查

### 问题 1: 后端服务启动失败

```bash
# 查看详细日志
sudo journalctl -u hustle-backend -n 100 --no-pager

# 检查是否有 Python 语法错误
cd /home/ubuntu/hustle2026/backend
python3 -m py_compile app/services/mt5_sync_service.py
```

### 问题 2: Windows Agent 不响应

```powershell
# 检查进程
Get-Process python

# 查看端口占用
netstat -ano | findstr :9000

# 手动启动并查看错误
cd C:\MT5Agent
python main.py
```

### 问题 3: 前端未更新

```bash
# 清除浏览器缓存
# 或者强制刷新（Ctrl+Shift+R）

# 检查 nginx 文件
ls -la /var/www/admin.hustle2026.xyz/assets/ | grep -E "MasterDashboard|UserManagement"
```

### 问题 4: MT5 客户端状态不更新

```bash
# 检查 MT5SyncService 日志
sudo journalctl -u hustle-backend -f | grep -i "mt5.*sync"

# 检查数据库连接
sudo journalctl -u hustle-backend -n 50 | grep -i "database"

# 手动测试 Windows Agent
curl http://54.249.66.53:9000/instances/8001/health
```

---

## 回滚方案

如果部署出现问题，可以快速回滚：

```bash
# 后端回滚到 main 分支
cd /home/ubuntu/hustle2026
git checkout main
git pull origin main
sudo systemctl restart hustle-backend

# 前端回滚
cd frontend
git checkout main
npm run build:admin
sudo cp -r dist-admin/* /var/www/admin.hustle2026.xyz/
```

---

## 相关文档

- [优化方案详细文档](../docs/MT5_STATUS_OPTIMIZATION_PLAN.md)
- [部署总结](../docs/DEPLOYMENT_SUMMARY.md)
- [系统架构](../docs/FINAL_REPORT.md)

---

## 联系支持

如有问题，请查看：
- GitHub Issues: https://github.com/joycar2010/hustle2026/issues
- 文档目录: `docs/`
