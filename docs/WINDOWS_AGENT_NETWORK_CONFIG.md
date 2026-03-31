# Windows Agent 网络访问配置指南

## 问题描述
Ubuntu 服务器（172.31.2.22）无法访问 Windows 服务器（172.31.14.113）的端口 9000，导致 MT5 客户端的 `process_running` 状态无法获取。

## 解决方案

### 方法 1：使用 PowerShell 脚本（推荐）

1. 远程桌面连接到 Windows 服务器（54.249.66.53）
2. 以管理员身份打开 PowerShell
3. 执行配置脚本：

```powershell
# 如果脚本在本地
cd D:\git\hustle2026\scripts
.\configure_windows_agent_firewall.ps1

# 或者直接复制粘贴以下命令
New-NetFirewallRule -DisplayName "MT5 Windows Agent" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 9000 `
    -Action Allow `
    -Profile Any `
    -Enabled True `
    -Description "允许 Ubuntu 服务器访问 Windows Agent API"
```

### 方法 2：使用 Windows 防火墙 GUI

1. 打开 Windows Defender 防火墙
2. 点击"高级设置"
3. 选择"入站规则" → "新建规则"
4. 规则类型：端口
5. 协议：TCP，特定本地端口：9000
6. 操作：允许连接
7. 配置文件：全部勾选
8. 名称：MT5 Windows Agent

### 方法 3：临时禁用防火墙测试（不推荐）

```powershell
# 临时禁用防火墙（仅用于测试）
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False

# 测试完成后记得重新启用
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True
```

## 验证步骤

### 1. 在 Windows 服务器上验证

```powershell
# 检查端口监听
Get-NetTCPConnection -State Listen -LocalPort 9000

# 检查防火墙规则
Get-NetFirewallRule -DisplayName "MT5 Windows Agent"

# 测试本地连接
Invoke-RestMethod -Uri "http://localhost:9000/" -Method Get
```

### 2. 从 Ubuntu 服务器测试

```bash
# SSH 到 Ubuntu 服务器
ssh -i c:/Users/HUAWEI/.ssh/HustleNew.pem ubuntu@go.hustle2026.xyz

# 测试连接
curl -v http://172.31.14.113:9000/

# 测试健康检查端点
curl http://172.31.14.113:9000/instances/8001/health
curl http://172.31.14.113:9000/instances/8002/health
```

### 3. 验证 API 返回数据

```bash
# 检查 MT5 客户端状态
curl -s http://localhost:8000/api/v1/monitor/status | python3 -m json.tool | grep -A 10 mt5_clients
```

**预期结果**：
- `process_running` 应该显示 `true`（如果 MT5 进程正在运行）
- `last_connected_at` 应该显示最近的时间戳

## 故障排查

### 问题 1：防火墙规则创建失败
**解决**：确保以管理员身份运行 PowerShell

### 问题 2：端口 9000 未监听
**解决**：重启 Windows Agent
```powershell
# 停止现有进程
Get-Process -Name python | Where-Object {$_.Path -like '*Python311*'} | Stop-Process -Force

# 启动 Agent
cd C:\MT5Agent
Start-Job -ScriptBlock {cd C:\MT5Agent; python main.py}

# 等待 5 秒
Start-Sleep -Seconds 5

# 验证
Get-NetTCPConnection -State Listen -LocalPort 9000
```

### 问题 3：Ubuntu 仍然无法连接
**可能原因**：
1. AWS 安全组未开放端口 9000
2. Windows 服务器的网络配置问题
3. VPC 路由问题

**检查 AWS 安全组**：
- 登录 AWS Console
- EC2 → 安全组
- 找到 Windows 服务器的安全组
- 添加入站规则：TCP 9000，来源：172.31.0.0/16（VPC 内网）

## 完成后的测试

配置完成后，访问 https://admin.hustle2026.xyz/ 验证：

1. **总控面板**
   - MT5 客户端卡片应显示"进程状态：运行中"
   - 显示"最后心跳：X秒前"

2. **用户管理页面**
   - MT5 实例控制按钮可用
   - 点击"重启"按钮应触发智能轮询

3. **API 数据**
   ```json
   {
     "mt5_clients": [{
       "process_running": true,  ← 应该是 true
       "last_connected_at": "2026-03-31T03:30:00"
     }]
   }
   ```

## 相关文件

- 配置脚本：`scripts/configure_windows_agent_firewall.ps1`
- Windows Agent：`C:\MT5Agent\main.py`
- 后端 API：`backend/app/api/v1/system_monitor.py`
- 部署状态：`docs/MT5_OPTIMIZATION_DEPLOYMENT_STATUS.md`
