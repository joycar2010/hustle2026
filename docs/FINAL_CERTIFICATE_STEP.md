# 🎉 证书已成功获取！最后一步

## ✅ 好消息

Let's Encrypt 证书已成功获取！

**证书详情：**
- 域名：app.hustle2026.xyz
- 颁发者：Let's Encrypt R13
- 有效期至：2026年6月13日
- 指纹：5D54923E91AB908006FFE66001CCE7D16C0BDFA5
- 下次续期：2026年5月9日

## ⚠️ 最后一步：导出证书为 PEM 格式

证书目前存储在 Windows 证书存储中，需要导出为 PEM 格式供 Nginx 使用。

### 方法一：重新运行 win-acme 并选择 PEM 存储（推荐）

1. **打开 PowerShell（管理员）**

2. **停止 Nginx**
   ```powershell
   cd C:\nginx
   .\nginx.exe -s stop
   Start-Sleep -Seconds 2
   ```

3. **运行 win-acme**
   ```powershell
   cd C:\win-acme
   .\wacs.exe
   ```

4. **选择操作**：
   - 输入 `M` → Manage renewals
   - 选择证书：`[Manual] app.hustle2026.xyz`
   - 输入 `4` → Update renewal
   - 输入 `5` → Change store settings

5. **配置 PEM 存储**：
   - 选择 `5` → PEM files
   - 输入路径：`C:\nginx\ssl`
   - 确认

6. **运行续期**（强制更新）：
   ```powershell
   .\wacs.exe --renew --id 5S5ANHVp_kqLFiePsJYdww --force
   ```

7. **重启 Nginx**
   ```powershell
   cd C:\nginx
   start nginx.exe
   ```

### 方法二：使用 PowerShell 从证书存储导出

1. **打开 PowerShell（管理员）**

2. **导出证书**
   ```powershell
   # 查找证书
   $cert = Get-ChildItem -Path Cert:\LocalMachine\My | Where-Object {$_.Thumbprint -eq '5D54923E91AB908006FFE66001CCE7D16C0BDFA5'}
   
   # 导出为PFX（需要设置密码）
   $pwd = ConvertTo-SecureString -String "temp123" -Force -AsPlainText
   Export-PfxCertificate -Cert $cert -FilePath C:\nginx\ssl\cert.pfx -Password $pwd
   
   # 使用OpenSSL转换为PEM
   cd C:\nginx\ssl
   openssl pkcs12 -in cert.pfx -nocerts -nodes -out privkey.pem -passin pass:temp123
   openssl pkcs12 -in cert.pfx -clcerts -nokeys -out fullchain.pem -passin pass:temp123
   ```

3. **重启 Nginx**
   ```powershell
   cd C:\nginx
   .\nginx.exe -s reload
   ```

### 方法三：使用 Certbot（如果以上方法都不行）

1. **下载 Certbot**
   https://dl.eff.org/certbot-beta-installer-win32.exe

2. **安装并运行**
   ```powershell
   # 停止 Nginx
   cd C:\nginx
   .\nginx.exe -s stop
   
   # 获取证书
   certbot certonly --standalone -d app.hustle2026.xyz --email admin@hustle2026.xyz --agree-tos --force-renewal
   
   # 复制证书
   copy C:\Certbot\live\app.hustle2026.xyz\fullchain.pem C:\nginx\ssl\
   copy C:\Certbot\live\app.hustle2026.xyz\privkey.pem C:\nginx\ssl\
   
   # 重启 Nginx
   cd C:\nginx
   start nginx.exe
   ```

## 🔍 验证证书

完成后，访问：
```
https://app.hustle2026.xyz
```

您应该看到：
- ✅ 绿色锁图标
- ✅ 证书由 Let's Encrypt 颁发
- ✅ 有效期至 2026年6月13日
- ✅ 不再有安全警告

## 📊 当前状态

| 项目 | 状态 |
|------|------|
| 域名解析 | ✅ 完成 |
| 防火墙配置 | ✅ 完成 |
| Nginx 配置 | ✅ 完成 |
| Let's Encrypt 证书 | ✅ 已获取 |
| 证书导出为 PEM | ⚠️ 需要完成 |
| 自动续期任务 | ✅ 已创建 |

## 🔄 证书自动续期

win-acme 已自动创建 Windows 计划任务，每天检查证书是否需要续期。

**查看续期任务：**
```powershell
Get-ScheduledTask | Where-Object {$_.TaskName -like "*win-acme*"}
```

**手动测试续期：**
```powershell
cd C:\win-acme
.\wacs.exe --renew --id 5S5ANHVp_kqLFiePsJYdww
```

## 📝 重要提示

1. 证书有效期 90 天
2. win-acme 会在到期前 30 天自动续期
3. 续期后需要重新加载 Nginx
4. 建议配置 PEM 文件存储，这样续期后证书会自动更新

## 🎯 推荐操作

**最简单的方法**：使用方法一重新配置 win-acme 的存储设置为 PEM 文件，这样以后续期时证书会自动导出到 Nginx 目录。

---

**需要帮助？** 查看详细文档：
- C:\nginx\SSL_CERTIFICATE_GUIDE.md
- C:\app\hustle2026\HTTPS_DEPLOYMENT_SUMMARY.md
