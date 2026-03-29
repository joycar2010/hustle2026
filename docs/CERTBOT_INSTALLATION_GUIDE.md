# Certbot 安装和使用指南

## 📥 步骤 1：下载 Certbot

由于服务器网络限制，请在本地电脑下载后上传到服务器。

### 方法一：直接下载（推荐）

1. **在浏览器中访问**：
   ```
   https://dl.eff.org/certbot-beta-installer-win_amd64_signed.exe
   ```

2. **下载完成后**，通过远程桌面或 FTP 上传到服务器的 `C:\` 目录

### 方法二：使用备用下载地址

如果上述链接无法访问，可以从 GitHub 下载：
```
https://github.com/certbot/certbot/releases
```
选择最新的 Windows 安装程序。

## 🔧 步骤 2：安装 Certbot

1. **双击运行** `C:\certbot-installer.exe`

2. **按照安装向导操作**：
   - 接受许可协议
   - 选择安装路径（默认即可）
   - 完成安装

3. **验证安装**：
   打开 PowerShell，运行：
   ```powershell
   certbot --version
   ```
   应该显示版本号（如：certbot 2.x.x）

## 🎯 步骤 3：获取 SSL 证书

### 3.1 停止 Nginx

```powershell
cd C:\nginx
.\nginx.exe -s stop
```

等待 2 秒确保端口释放。

### 3.2 运行 Certbot

```powershell
certbot certonly --standalone -d app.hustle2026.xyz --email admin@hustle2026.xyz --agree-tos
```

**参数说明：**
- `certonly`：只获取证书，不安装
- `--standalone`：使用内置 Web 服务器（需要 80 端口）
- `-d app.hustle2026.xyz`：您的域名
- `--email admin@hustle2026.xyz`：接收续期通知的邮箱
- `--agree-tos`：同意服务条款

### 3.3 等待完成

Certbot 会：
1. 启动临时 Web 服务器（监听 80 端口）
2. 向 Let's Encrypt 请求证书
3. Let's Encrypt 验证域名所有权
4. 下载并保存证书

**预期输出：**
```
Congratulations! Your certificate and chain have been saved at:
C:\Certbot\live\app.hustle2026.xyz\fullchain.pem
Your key file has been saved at:
C:\Certbot\live\app.hustle2026.xyz\privkey.pem
```

## 📋 步骤 4：复制证书到 Nginx

```powershell
# 备份旧证书
copy C:\nginx\ssl\fullchain.pem C:\nginx\ssl\fullchain.pem.old
copy C:\nginx\ssl\privkey.pem C:\nginx\ssl\privkey.pem.old

# 复制新证书
copy C:\Certbot\live\app.hustle2026.xyz\fullchain.pem C:\nginx\ssl\fullchain.pem
copy C:\Certbot\live\app.hustle2026.xyz\privkey.pem C:\nginx\ssl\privkey.pem
```

## 🚀 步骤 5：启动 Nginx

```powershell
cd C:\nginx
start nginx.exe
```

## ✅ 步骤 6：验证证书

### 6.1 检查证书文件

```powershell
openssl x509 -in C:\nginx\ssl\fullchain.pem -noout -issuer -dates
```

应该显示：
- Issuer: Let's Encrypt
- 有效期：90 天

### 6.2 访问网站

在浏览器中访问：
```
https://app.hustle2026.xyz
```

应该看到：
- ✅ 绿色锁图标
- ✅ 证书由 Let's Encrypt 颁发
- ✅ 不再有安全警告

### 6.3 在线测试

访问 SSL Labs 测试：
```
https://www.ssllabs.com/ssltest/analyze.html?d=app.hustle2026.xyz
```

## 🔄 证书自动续期

Certbot 会自动创建 Windows 计划任务。

### 查看续期任务

```powershell
Get-ScheduledTask | Where-Object {$_.TaskName -like "*certbot*"}
```

### 手动测试续期

```powershell
certbot renew --dry-run
```

### 配置续期后重启 Nginx

创建续期钩子脚本：

1. **创建脚本** `C:\Certbot\renewal-hooks\deploy\reload-nginx.bat`：
   ```batch
   @echo off
   cd C:\nginx
   nginx.exe -s reload
   ```

2. **测试续期**：
   ```powershell
   certbot renew --dry-run
   ```

## 🚨 故障排查

### 问题 1：端口 80 被占用

**错误信息**：
```
Problem binding to port 80: Could not bind to IPv4 or IPv6.
```

**解决方案**：
```powershell
# 检查端口占用
netstat -ano | findstr ":80 "

# 停止 Nginx
cd C:\nginx
.\nginx.exe -s stop

# 或强制停止
taskkill /F /IM nginx.exe
```

### 问题 2：域名解析失败

**错误信息**：
```
DNS problem: NXDOMAIN looking up A for app.hustle2026.xyz
```

**解决方案**：
```powershell
# 检查域名解析
nslookup app.hustle2026.xyz
```

应该返回：`13.115.21.77`

### 问题 3：防火墙阻止

**错误信息**：
```
Connection refused
```

**解决方案**：
```powershell
# 检查防火墙规则
Get-NetFirewallRule -DisplayName "Nginx*"

# 确保 80 端口开放
Test-NetConnection -ComputerName localhost -Port 80
```

### 问题 4：证书已存在

**错误信息**：
```
Certificate already exists
```

**解决方案**：
```powershell
# 强制续期
certbot renew --force-renewal
```

## 📝 常用命令

### 查看所有证书

```powershell
certbot certificates
```

### 续期所有证书

```powershell
certbot renew
```

### 撤销证书

```powershell
certbot revoke --cert-path C:\Certbot\live\app.hustle2026.xyz\cert.pem
```

### 删除证书

```powershell
certbot delete --cert-name app.hustle2026.xyz
```

## 🎯 完整操作流程（快速参考）

```powershell
# 1. 停止 Nginx
cd C:\nginx
.\nginx.exe -s stop

# 2. 获取证书
certbot certonly --standalone -d app.hustle2026.xyz --email admin@hustle2026.xyz --agree-tos

# 3. 复制证书
copy C:\Certbot\live\app.hustle2026.xyz\fullchain.pem C:\nginx\ssl\fullchain.pem
copy C:\Certbot\live\app.hustle2026.xyz\privkey.pem C:\nginx\ssl\privkey.pem

# 4. 启动 Nginx
cd C:\nginx
start nginx.exe

# 5. 验证
# 访问 https://app.hustle2026.xyz
```

## 📞 需要帮助？

- Certbot 文档：https://certbot.eff.org/docs/
- Let's Encrypt 文档：https://letsencrypt.org/docs/
- Certbot GitHub：https://github.com/certbot/certbot

---

**预计完成时间：5 分钟**
