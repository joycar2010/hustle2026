# SSL 证书问题解决方案

## 🔍 当前问题

### 已完成
✅ Let's Encrypt 证书已成功获取
✅ 证书存储在 Windows 证书存储中
✅ 证书详情：
- 域名：app.hustle2026.xyz
- 颁发者：Let's Encrypt R13
- 有效期至：2026年6月13日
- 指纹：5D54923E91AB908006FFE66001CCE7D16C0BDFA5

### 问题
❌ 私钥被标记为"不可导出"
❌ 无法导出为 PEM 格式供 Nginx 使用
❌ Nginx 仍在使用旧的自签名证书
❌ 网站无法访问（使用自签名证书时浏览器会阻止）

## ✅ 最简单的解决方案

使用 **Certbot** 重新获取证书（推荐，5分钟完成）

### 步骤 1：下载并安装 Certbot

1. **下载 Certbot**
   访问：https://dl.eff.org/certbot-beta-installer-win_amd64_signed.exe
   或运行：
   ```powershell
   curl -L -o C:\certbot-installer.exe https://dl.eff.org/certbot-beta-installer-win_amd64_signed.exe
   ```

2. **安装 Certbot**
   双击 `C:\certbot-installer.exe` 并按照提示安装

### 步骤 2：获取证书

1. **确保 Nginx 已停止**
   ```powershell
   cd C:\nginx
   .\nginx.exe -s stop
   ```

2. **运行 Certbot**
   ```powershell
   certbot certonly --standalone -d app.hustle2026.xyz --email admin@hustle2026.xyz --agree-tos
   ```

3. **等待完成**（约30秒）
   证书将保存到：`C:\Certbot\live\app.hustle2026.xyz\`

### 步骤 3：复制证书到 Nginx

```powershell
copy C:\Certbot\live\app.hustle2026.xyz\fullchain.pem C:\nginx\ssl\fullchain.pem
copy C:\Certbot\live\app.hustle2026.xyz\privkey.pem C:\nginx\ssl\privkey.pem
```

### 步骤 4：启动 Nginx

```powershell
cd C:\nginx
start nginx.exe
```

### 步骤 5：验证

访问：https://app.hustle2026.xyz

应该看到：
✅ 绿色锁图标
✅ 证书由 Let's Encrypt 颁发
✅ 不再有安全警告

## 🔄 证书自动续期

Certbot 会自动创建 Windows 计划任务来续期证书。

**查看续期任务：**
```powershell
Get-ScheduledTask | Where-Object {$_.TaskName -like "*certbot*"}
```

**手动测试续期：**
```powershell
certbot renew --dry-run
```

## 📊 为什么选择 Certbot？

| 特性 | win-acme | Certbot |
|------|----------|---------|
| 易用性 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| PEM 导出 | ❌ 需要配置 | ✅ 默认支持 |
| 私钥导出 | ❌ 标记为不可导出 | ✅ 可导出 |
| 自动续期 | ✅ | ✅ |
| 文档 | 较少 | 丰富 |

## 🎯 预期时间

- 下载 Certbot：1分钟
- 安装 Certbot：1分钟
- 获取证书：30秒
- 复制证书：10秒
- 启动 Nginx：10秒
- **总计：约3分钟**

## 📝 备选方案

如果您想继续使用 win-acme，需要：

1. **删除现有续期配置**
   ```powershell
   cd C:\win-acme
   .\wacs.exe
   # 选择 M (Manage renewals)
   # 选择证书
   # 选择 C (Cancel renewal)
   ```

2. **重新创建证书**（配置 PEM 存储）
   ```powershell
   .\wacs.exe
   # 选择 N (Create certificate)
   # 选择 2 (Manual input)
   # 域名：app.hustle2026.xyz
   # 验证：1 (SelfHosting)
   # 存储：5 (PEM files)
   # 路径：C:\nginx\ssl
   # 密码：1 (None)
   ```

但这需要更多步骤，建议使用 Certbot。

## 🚨 重要提示

1. 获取证书前必须停止 Nginx（释放 80 端口）
2. 确保防火墙允许 80 端口入站
3. 确保域名正确解析到服务器 IP
4. 证书有效期 90 天，会自动续期

## 📞 需要帮助？

- Certbot 文档：https://certbot.eff.org/docs/
- Let's Encrypt 文档：https://letsencrypt.org/docs/

---

**推荐操作：使用 Certbot 重新获取证书（最简单、最快速）**
