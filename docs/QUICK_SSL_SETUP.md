# 快速获取 SSL 证书指南

## ⚠️ 您遇到的错误

错误信息：`Unable to activate listener, this may be because of insufficient rights or a non-Microsoft webserver using port 80`

**原因**：Nginx 正在占用 80 端口，win-acme 无法启动自己的监听器。

## ✅ 解决方案

### 方案一：使用 PowerShell 手动获取（推荐）

**步骤：**

1. **停止 Nginx**
   ```powershell
   cd C:\nginx
   .\nginx.exe -s stop
   ```

2. **等待 2 秒确保端口释放**
   ```powershell
   Start-Sleep -Seconds 2
   ```

3. **运行 win-acme**
   ```powershell
   cd C:\win-acme
   .\wacs.exe
   ```

4. **按照提示操作**：
   - 输入 `N` 创建新证书
   - 选择 `2` (Manual input)
   - 输入域名：`app.hustle2026.xyz`
   - 选择验证方式：`1` (SelfHosting)
   - 输入端口：`80`
   - 选择存储：`5` (PEM files)
   - PEM 路径：`C:\nginx\ssl`
   - 选择安装：`3` (No installation)
   - 输入邮箱：`admin@hustle2026.xyz`
   - 接受条款：`yes`

5. **等待证书获取完成**（约 30 秒）

6. **重启 Nginx**
   ```powershell
   cd C:\nginx
   start nginx.exe
   ```

7. **验证证书**
   访问：https://app.hustle2026.xyz
   应该看到绿色锁图标！

### 方案二：使用自动化脚本

我已经为您创建了自动化脚本：

**位置**：`C:\win-acme\get-certificate.ps1`

**使用方法**：
1. 右键点击"开始"菜单
2. 选择"Windows PowerShell (管理员)"
3. 运行：
   ```powershell
   cd C:\win-acme
   .\get-certificate.ps1
   ```

### 方案三：使用 Certbot（备选）

如果 win-acme 仍有问题，可以使用 Certbot：

1. **下载 Certbot**
   https://dl.eff.org/certbot-beta-installer-win32.exe

2. **安装后运行**
   ```powershell
   # 停止 Nginx
   cd C:\nginx
   .\nginx.exe -s stop
   
   # 获取证书
   certbot certonly --standalone -d app.hustle2026.xyz --email admin@hustle2026.xyz --agree-tos
   
   # 复制证书
   copy C:\Certbot\live\app.hustle2026.xyz\fullchain.pem C:\nginx\ssl\
   copy C:\Certbot\live\app.hustle2026.xyz\privkey.pem C:\nginx\ssl\
   
   # 重启 Nginx
   cd C:\nginx
   start nginx.exe
   ```

## 🔍 故障排查

### 问题：端口被占用

**检查端口**：
```powershell
netstat -ano | findstr ":80 "
```

**停止 Nginx**：
```powershell
taskkill /F /IM nginx.exe
```

### 问题：域名解析失败

**检查域名解析**：
```powershell
nslookup app.hustle2026.xyz
```

应该返回：`13.115.21.77`

### 问题：防火墙阻止

**检查防火墙规则**：
```powershell
Get-NetFirewallRule -DisplayName "Nginx*"
```

应该看到 HTTP (80) 和 HTTPS (443) 规则已启用。

### 问题：权限不足

确保以**管理员权限**运行 PowerShell。

## 📝 重要提示

1. ✅ 域名已解析：app.hustle2026.xyz → 13.115.21.77
2. ✅ 防火墙已配置：80 和 443 端口已开放
3. ✅ Nginx 已配置：准备好使用 SSL 证书
4. ⚠️ 需要手动获取证书：按照上述步骤操作

## 🎯 预期结果

证书获取成功后：
- ✅ 浏览器显示绿色锁图标
- ✅ 证书有效期 90 天
- ✅ 自动续期任务已创建
- ✅ 可以通过 https://app.hustle2026.xyz 安全访问

## 📞 需要帮助？

查看详细文档：
- `C:\win-acme\GET_CERTIFICATE_INSTRUCTIONS.txt`
- `C:\nginx\SSL_CERTIFICATE_GUIDE.md`
- `C:\app\hustle2026\HTTPS_DEPLOYMENT_SUMMARY.md`

---

**当前状态**：
- Nginx：✅ 已重启
- 临时证书：✅ 可用（自签名）
- 正式证书：⚠️ 需要手动获取

**下一步**：按照上述方案一的步骤获取正式证书！
