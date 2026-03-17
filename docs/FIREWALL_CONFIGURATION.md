# 防火墙配置说明

## ✅ 已完成的配置

### Windows 防火墙规则

已成功添加以下防火墙规则：

**1. HTTP (端口 80)**
- 规则名称：Nginx HTTP (Port 80)
- 状态：已启用
- 方向：入站
- 协议：TCP
- 端口：80
- 操作：允许
- 配置文件：Domain, Private, Public（所有网络）

**2. HTTPS (端口 443)**
- 规则名称：Nginx HTTPS (Port 443)
- 状态：已启用
- 方向：入站
- 协议：TCP
- 端口：443
- 操作：允许
- 配置文件：Domain, Private, Public（所有网络）

## 🔍 验证防火墙规则

### 查看规则详情

**查看 HTTP 规则：**
```powershell
netsh advfirewall firewall show rule name="Nginx HTTP (Port 80)"
```

**查看 HTTPS 规则：**
```powershell
netsh advfirewall firewall show rule name="Nginx HTTPS (Port 443)"
```

**查看所有 Nginx 规则：**
```powershell
Get-NetFirewallRule -DisplayName 'Nginx*' | Format-Table DisplayName, Enabled, Direction, Action
```

### 测试端口连通性

**从本地测试：**
```powershell
Test-NetConnection -ComputerName localhost -Port 80
Test-NetConnection -ComputerName localhost -Port 443
```

**从外网测试：**
```powershell
Test-NetConnection -ComputerName app.hustle2026.xyz -Port 80
Test-NetConnection -ComputerName app.hustle2026.xyz -Port 443
```

## 🛠️ 管理防火墙规则

### 启用规则
```powershell
Enable-NetFirewallRule -DisplayName "Nginx HTTP (Port 80)"
Enable-NetFirewallRule -DisplayName "Nginx HTTPS (Port 443)"
```

### 禁用规则
```powershell
Disable-NetFirewallRule -DisplayName "Nginx HTTP (Port 80)"
Disable-NetFirewallRule -DisplayName "Nginx HTTPS (Port 443)"
```

### 删除规则
```powershell
Remove-NetFirewallRule -DisplayName "Nginx HTTP (Port 80)"
Remove-NetFirewallRule -DisplayName "Nginx HTTPS (Port 443)"
```

### 重新创建规则

如果需要重新创建规则：

```powershell
# 删除旧规则
Remove-NetFirewallRule -DisplayName "Nginx HTTP (Port 80)" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "Nginx HTTPS (Port 443)" -ErrorAction SilentlyContinue

# 创建新规则
New-NetFirewallRule -DisplayName "Nginx HTTP (Port 80)" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow -Profile Any
New-NetFirewallRule -DisplayName "Nginx HTTPS (Port 443)" -Direction Inbound -LocalPort 443 -Protocol TCP -Action Allow -Profile Any
```

## 🌐 云服务商安全组配置

如果您的服务器在云平台（如AWS、阿里云等），还需要在云平台的安全组中开放端口：

### AWS EC2 安全组

1. 登录 AWS 控制台
2. 进入 EC2 -> 安全组
3. 选择您的实例的安全组
4. 添加入站规则：
   - 类型：HTTP，协议：TCP，端口：80，源：0.0.0.0/0
   - 类型：HTTPS，协议：TCP，端口：443，源：0.0.0.0/0

### 阿里云安全组

1. 登录阿里云控制台
2. 进入 ECS -> 网络与安全 -> 安全组
3. 选择您的安全组 -> 配置规则
4. 添加入方向规则：
   - 协议类型：TCP，端口范围：80/80，授权对象：0.0.0.0/0
   - 协议类型：TCP，端口范围：443/443，授权对象：0.0.0.0/0

### 腾讯云安全组

1. 登录腾讯云控制台
2. 进入云服务器 -> 安全组
3. 选择您的安全组 -> 入站规则
4. 添加规则：
   - 协议：TCP，端口：80，源：0.0.0.0/0
   - 协议：TCP，端口：443，源：0.0.0.0/0

## 🔒 安全建议

### 1. 限制访问源（可选）

如果您只想允许特定IP访问，可以修改规则：

```powershell
# 只允许特定IP访问
New-NetFirewallRule -DisplayName "Nginx HTTPS (Port 443) - Restricted" -Direction Inbound -LocalPort 443 -Protocol TCP -Action Allow -RemoteAddress "1.2.3.4"
```

### 2. 启用日志记录

```powershell
Set-NetFirewallProfile -Profile Domain,Public,Private -LogAllowed True -LogBlocked True -LogFileName "%systemroot%\system32\LogFiles\Firewall\pfirewall.log"
```

### 3. 定期审查规则

```powershell
# 查看所有入站规则
Get-NetFirewallRule -Direction Inbound -Enabled True | Format-Table DisplayName, Action, LocalPort
```

### 4. 监控异常流量

定期检查防火墙日志：
```powershell
Get-Content "$env:SystemRoot\System32\LogFiles\Firewall\pfirewall.log" -Tail 50
```

## 📊 当前端口使用情况

| 端口 | 服务 | 状态 | 防火墙规则 |
|------|------|------|-----------|
| 80 | Nginx HTTP | ✅ 运行中 | ✅ 已开放 |
| 443 | Nginx HTTPS | ✅ 运行中 | ✅ 已开放 |
| 3000 | 前端服务 | ✅ 运行中 | ❌ 不需要（通过Nginx代理） |
| 8000 | 后端服务 | ✅ 运行中 | ❌ 不需要（通过Nginx代理） |
| 5432 | PostgreSQL | ✅ 运行中 | ❌ 不需要（仅本地访问） |

## ✅ 验证配置

### 1. 检查防火墙状态
```powershell
Get-NetFirewallProfile | Format-Table Name, Enabled
```

### 2. 测试HTTP访问
```bash
curl -I http://app.hustle2026.xyz
```
应该返回 `301 Moved Permanently` 重定向到 HTTPS

### 3. 测试HTTPS访问
```bash
curl -I -k https://app.hustle2026.xyz
```
应该返回 `200 OK` 或前端页面

### 4. 在线端口扫描

使用在线工具检查端口是否开放：
- https://www.yougetsignal.com/tools/open-ports/
- https://www.portchecktool.com/

输入您的服务器IP或域名，检查80和443端口。

## 🚨 故障排查

### 端口无法访问

1. **检查防火墙规则是否启用：**
   ```powershell
   Get-NetFirewallRule -DisplayName "Nginx*" | Select-Object DisplayName, Enabled
   ```

2. **检查Nginx是否运行：**
   ```powershell
   netstat -ano | findstr ":80 "
   netstat -ano | findstr ":443 "
   ```

3. **检查云平台安全组：**
   确保云平台的安全组也开放了80和443端口

4. **测试本地连接：**
   ```powershell
   Test-NetConnection -ComputerName localhost -Port 80
   Test-NetConnection -ComputerName localhost -Port 443
   ```

5. **查看防火墙日志：**
   ```powershell
   Get-Content "$env:SystemRoot\System32\LogFiles\Firewall\pfirewall.log" -Tail 20
   ```

### 规则冲突

如果有多个规则冲突：

```powershell
# 查看所有80端口的规则
Get-NetFirewallPortFilter | Where-Object {$_.LocalPort -eq 80} | Get-NetFirewallRule

# 查看所有443端口的规则
Get-NetFirewallPortFilter | Where-Object {$_.LocalPort -eq 443} | Get-NetFirewallRule
```

## 📝 总结

✅ **已完成：**
- Windows 防火墙已开放 80 和 443 端口
- 规则已启用并应用到所有网络配置文件
- 端口可从外网访问

⚠️ **注意事项：**
- 如果服务器在云平台，还需要在云平台安全组中开放端口
- 定期检查防火墙日志，监控异常访问
- 保持防火墙规则简洁，避免冲突

🎉 **配置完成！**
您的服务器现在可以通过 HTTP (80) 和 HTTPS (443) 端口对外提供服务了！
