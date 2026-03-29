# Windows Agent 内网访问配置指南

## 问题
当前 Windows Agent (9000端口) 无法从 GO 服务器 (172.31.2.22) 通过内网访问，导致 MT5 实例控制操作延迟。

## 解决方案

### 步骤 1: 配置 Windows 防火墙

在 Windows MT5 服务器 (172.31.14.113) 上以管理员身份运行：

```powershell
# 方法 1: 使用提供的脚本
cd C:\MT5Agent
.\configure-firewall.ps1

# 方法 2: 手动执行命令
New-NetFirewallRule -DisplayName "MT5 Windows Agent" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 9000 `
    -Action Allow `
    -Profile Any
```

### 步骤 2: 配置 AWS 安全组

在 AWS 控制台中，为 Windows MT5 服务器的安全组添加入站规则：

- **类型**: 自定义 TCP
- **协议**: TCP
- **端口范围**: 9000
- **源**: 172.31.2.22/32 (GO 服务器内网 IP)
- **描述**: Allow MT5 Agent API from GO server

或者允许整个 VPC 内网段：
- **源**: 172.31.0.0/16

### 步骤 3: 验证连接

从 GO 服务器测试连接：

```bash
ssh -i ~/.ssh/HustleNew.pem ubuntu@go.hustle2026.xyz
curl http://172.31.14.113:9000/
```

应该返回：
```json
{"status": "healthy", "service": "MT5 Windows Agent"}
```

### 步骤 4: 部署优化后的代码

配置完成后，部署优化后的 MT5AgentService：

```bash
# 在 GO 服务器上
cd /home/ubuntu/hustle2026/backend
cp app/services/mt5_agent_service.py app/services/mt5_agent_service.backup.py
# 上传新的 mt5_agent_service_optimized.py 并重命名
sudo systemctl restart hustle-backend
```

## 预期效果

- **延迟降低**: 从 SSH 隧道 (~500ms) 降低到直接 HTTP 调用 (~10ms)
- **连接复用**: 使用 httpx 连接池，避免每次请求都建立新连接
- **更稳定**: 减少 SSH 连接失败的风险

## 故障排查

### 1. 防火墙规则检查
```powershell
Get-NetFirewallRule -DisplayName "MT5 Windows Agent"
```

### 2. 端口监听检查
```powershell
netstat -an | findstr :9000
```

应该看到：
```
TCP    0.0.0.0:9000           0.0.0.0:0              LISTENING
```

### 3. Agent 服务状态
```powershell
# 如果安装为服务
Get-Service -Name "MT5Agent"

# 或检查进程
Get-Process -Name python | Where-Object {$_.CommandLine -like "*main.py*"}
```

### 4. 从 GO 服务器测试
```bash
# 测试连通性
telnet 172.31.14.113 9000

# 测试 HTTP
curl -v http://172.31.14.113:9000/
```

## 注意事项

1. **安全性**: 9000 端口只对内网开放，不要暴露到公网
2. **服务重启**: 修改防火墙规则后无需重启 Agent 服务
3. **AWS 安全组**: 确保两台服务器在同一个 VPC 中
4. **备份**: 修改前备份原有配置
