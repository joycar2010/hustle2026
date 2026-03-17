# SSL 证书替代解决方案

## 🎯 当前情况

- Certbot Windows 安装程序在 GitHub releases 中不可用
- 服务器网络无法直接下载 Certbot
- Let's Encrypt 证书已获取但无法导出为 PEM 格式

## ✅ 推荐方案：使用 acme.sh（最简单）

acme.sh 是一个纯 Shell 脚本实现的 ACME 客户端，无需安装，直接运行。

### 方案 A：在 Git Bash 中使用 acme.sh

**步骤 1：下载 acme.sh**

```bash
cd /c
curl https://get.acme.sh | sh
```

**步骤 2：停止 Nginx**

```bash
cd /c/nginx
./nginx.exe -s stop
sleep 2
```

**步骤 3：获取证书**

```bash
/c/Users/Administrator/.acme.sh/acme.sh --issue --standalone -d app.hustle2026.xyz --server letsencrypt
```

**步骤 4：安装证书到 Nginx**

```bash
/c/Users/Administrator/.acme.sh/acme.sh --install-cert -d app.hustle2026.xyz \
  --key-file /c/nginx/ssl/privkey.pem \
  --fullchain-file /c/nginx/ssl/fullchain.pem \
  --reloadcmd "cd /c/nginx && ./nginx.exe -s reload"
```

**步骤 5：启动 Nginx**

```bash
cd /c/nginx
start nginx.exe
```

### 方案 B：手动使用 OpenSSL 和 Let's Encrypt API

如果 acme.sh 也无法使用，可以使用现有的 Let's Encrypt 证书。

**步骤 1：从 Windows 证书存储导出公钥**

```powershell
# 导出证书（公钥部分）
certutil -store My 5D54923E91AB908006FFE66001CCE7D16C0BDFA5 C:\nginx\ssl\cert.der

# 转换为 PEM 格式
openssl x509 -inform DER -in C:\nginx\ssl\cert.der -out C:\nginx\ssl\cert.pem
```

**步骤 2：获取中间证书**

```powershell
# 下载 Let's Encrypt R13 中间证书
curl -o C:\nginx\ssl\chain.pem https://letsencrypt.org/certs/r13.pem

# 合并为完整证书链
type C:\nginx\ssl\cert.pem C:\nginx\ssl\chain.pem > C:\nginx\ssl\fullchain.pem
```

**问题**：私钥仍然无法导出（标记为不可导出）

### 方案 C：重新配置 win-acme（删除并重建）

**步骤 1：删除现有证书配置**

```powershell
cd C:\win-acme
.\wacs.exe
# 选择 M (Manage renewals)
# 选择证书 [Manual] app.hustle2026.xyz
# 选择 C (Cancel renewal)
```

**步骤 2：重新创建证书（配置 PEM 存储）**

```powershell
# 停止 Nginx
cd C:\nginx
.\nginx.exe -s stop

# 运行 win-acme
cd C:\win-acme
.\wacs.exe
```

按照提示操作：
1. 选择 `N` (Create certificate)
2. 选择 `2` (Manual input)
3. 输入域名：`app.hustle2026.xyz`
4. 选择验证：`1` (SelfHosting)
5. 输入端口：`80`
6. 选择存储：`5` (PEM files)
7. 输入路径：`C:\nginx\ssl`
8. 密码：`1` (None)
9. 选择安装：`3` (No installation)

**步骤 3：启动 Nginx**

```powershell
cd C:\nginx
start nginx.exe
```

### 方案 D：使用 ZeroSSL（Let's Encrypt 替代品）

ZeroSSL 提供免费 SSL 证书，可以手动下载。

**步骤 1：注册账户**

访问：https://zerossl.com/

**步骤 2：创建证书**

1. 点击 "New Certificate"
2. 输入域名：`app.hustle2026.xyz`
3. 选择 90 天免费证书
4. 选择验证方式：HTTP File Upload

**步骤 3：验证域名**

1. 下载验证文件
2. 上传到：`C:\nginx\html\.well-known\acme-challenge\`
3. 确保 Nginx 运行中
4. 点击验证

**步骤 4：下载证书**

1. 验证成功后下载证书
2. 解压得到：
   - `certificate.crt` → 复制为 `C:\nginx\ssl\fullchain.pem`
   - `private.key` → 复制为 `C:\nginx\ssl\privkey.pem`

**步骤 5：重启 Nginx**

```powershell
cd C:\nginx
.\nginx.exe -s reload
```

## 📊 方案对比

| 方案 | 难度 | 时间 | 自动续期 | 推荐度 |
|------|------|------|----------|--------|
| acme.sh | ⭐⭐ | 5分钟 | ✅ | ⭐⭐⭐⭐⭐ |
| 重新配置 win-acme | ⭐⭐⭐ | 10分钟 | ✅ | ⭐⭐⭐⭐ |
| ZeroSSL 手动 | ⭐⭐⭐⭐ | 15分钟 | ❌ | ⭐⭐⭐ |
| OpenSSL 手动 | ⭐⭐⭐⭐⭐ | 20分钟 | ❌ | ⭐ |

## 🎯 推荐操作

**最推荐：方案 A（acme.sh）**

优点：
- 无需安装，直接运行
- 支持自动续期
- 命令简单
- 跨平台

**次推荐：方案 C（重新配置 win-acme）**

优点：
- win-acme 已安装
- 支持自动续期
- Windows 原生支持

## 🚀 快速开始（acme.sh）

```bash
# 1. 安装 acme.sh
cd /c
curl https://get.acme.sh | sh

# 2. 停止 Nginx
cd /c/nginx
./nginx.exe -s stop

# 3. 获取证书
~/.acme.sh/acme.sh --issue --standalone -d app.hustle2026.xyz

# 4. 安装证书
~/.acme.sh/acme.sh --install-cert -d app.hustle2026.xyz \
  --key-file /c/nginx/ssl/privkey.pem \
  --fullchain-file /c/nginx/ssl/fullchain.pem

# 5. 启动 Nginx
cd /c/nginx
start nginx.exe
```

## 📝 注意事项

1. 所有方案都需要停止 Nginx（释放 80 端口）
2. 确保防火墙允许 80 端口入站
3. 确保域名正确解析
4. 证书有效期 90 天

## 📞 需要帮助？

- acme.sh 文档：https://github.com/acmesh-official/acme.sh
- ZeroSSL：https://zerossl.com/
- Let's Encrypt：https://letsencrypt.org/

---

**推荐：使用 acme.sh（方案 A）- 最简单、最快速**
