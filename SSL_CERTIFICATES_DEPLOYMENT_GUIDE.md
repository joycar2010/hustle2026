# SSL证书管理模块 - 完整部署指南

**更新时间**: 2026-02-24
**模块**: SSL证书管理API
**服务器**: http://13.115.21.77:3000

---

## ✅ 已完成的新增文件

### 1. API路由
- `backend/app/api/v1/ssl_certificates.py` - SSL证书管理API（7个接口）

### 2. Pydantic Schemas
- `backend/app/schemas/ssl.py` - SSL证书相关数据验证模型

### 3. 工具脚本
- `scripts/check_ssl_expiry.py` - SSL证书过期检查脚本

---

## 🚀 立即部署步骤

### 第一步：创建SSL证书存储目录

```bash
# 创建证书存储目录
sudo mkdir -p /etc/ssl/hustle/certs
sudo mkdir -p /etc/ssl/hustle/private
sudo mkdir -p /etc/ssl/hustle/chains

# 设置权限
sudo chown -R hustle:hustle /etc/ssl/hustle
sudo chmod 755 /etc/ssl/hustle/certs
sudo chmod 700 /etc/ssl/hustle/private
sudo chmod 755 /etc/ssl/hustle/chains
```

### 第二步：注册API路由

编辑 `backend/app/main.py`，添加SSL证书路由：

```python
from app.api.v1 import ssl_certificates  # 添加导入

# 在现有路由后添加
app.include_router(
    ssl_certificates.router,
    prefix="/api/v1/ssl",
    tags=["SSL证书管理"]
)
```

### 第三步：安装依赖

```bash
cd backend
pip install cryptography
```

### 第四步：配置定时任务

```bash
# 编辑crontab
crontab -e

# 添加每日检查任务（每天凌晨3点）
0 3 * * * /var/www/hustle/backend/venv/bin/python /var/www/hustle/scripts/check_ssl_expiry.py >> /var/log/hustle/ssl_check.log 2>&1

# 添加每周检查任务（每周一上午9点）
0 9 * * 1 /var/www/hustle/backend/venv/bin/python /var/www/hustle/scripts/check_ssl_expiry.py >> /var/log/hustle/ssl_check.log 2>&1
```

### 第五步：启动服务

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 📡 API接口测试

### 1. 获取SSL证书列表

```bash
curl -X GET "http://localhost:8000/api/v1/ssl/certificates" \
  -H "Authorization: Bearer <your_token>"
```

**响应示例**：
```json
[
  {
    "cert_id": "uuid",
    "cert_name": "主域名证书",
    "domain_name": "13.115.21.77",
    "cert_type": "ca_signed",
    "issuer": "CN=Let's Encrypt Authority X3",
    "subject": "CN=13.115.21.77",
    "issued_at": "2026-01-01T00:00:00Z",
    "expires_at": "2026-04-01T00:00:00Z",
    "status": "active",
    "is_deployed": true,
    "days_before_expiry": 35,
    "auto_renew": true,
    "created_at": "2026-02-24T10:00:00Z"
  }
]
```

### 2. 上传SSL证书

```bash
curl -X POST "http://localhost:8000/api/v1/ssl/certificates" \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "cert_name": "生产环境证书",
    "domain_name": "13.115.21.77",
    "cert_type": "ca_signed",
    "cert_content": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----",
    "key_content": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
    "chain_content": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----",
    "auto_renew": true
  }'
```

**响应示例**：
```json
{
  "cert_id": "uuid",
  "cert_name": "生产环境证书",
  "domain_name": "13.115.21.77",
  "cert_file_path": "/etc/ssl/hustle/certs/13_115_21_77_20260224_100000.crt",
  "key_file_path": "/etc/ssl/hustle/private/13_115_21_77_20260224_100000.key",
  "status": "inactive",
  "is_deployed": false,
  "days_before_expiry": 90,
  "created_at": "2026-02-24T10:00:00Z"
}
```

### 3. 部署SSL证书

```bash
curl -X POST "http://localhost:8000/api/v1/ssl/certificates/{cert_id}/deploy" \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "nginx_config_path": "/etc/nginx/sites-available/hustle",
    "reload_nginx": true,
    "backup_old_cert": true
  }'
```

**响应示例**：
```json
{
  "message": "SSL证书部署成功",
  "domain_name": "13.115.21.77",
  "cert_path": "/etc/ssl/hustle/certs/13_115_21_77_20260224_100000.crt",
  "key_path": "/etc/ssl/hustle/private/13_115_21_77_20260224_100000.key"
}
```

### 4. 获取证书状态

```bash
curl -X GET "http://localhost:8000/api/v1/ssl/certificates/{cert_id}/status" \
  -H "Authorization: Bearer <your_token>"
```

**响应示例**：
```json
{
  "cert_id": "uuid",
  "domain_name": "13.115.21.77",
  "status": "active",
  "is_deployed": true,
  "expires_at": "2026-04-01T00:00:00Z",
  "days_before_expiry": 35,
  "is_valid": true,
  "error_message": null,
  "last_check_at": "2026-02-24T10:00:00Z"
}
```

### 5. 删除SSL证书

```bash
curl -X DELETE "http://localhost:8000/api/v1/ssl/certificates/{cert_id}" \
  -H "Authorization: Bearer <your_token>"
```

### 6. 获取操作日志

```bash
curl -X GET "http://localhost:8000/api/v1/ssl/certificates/{cert_id}/logs?limit=20" \
  -H "Authorization: Bearer <your_token>"
```

---

## 🔧 手动部署SSL证书到Nginx

### 方案1：使用Let's Encrypt（推荐）

```bash
# 1. 安装Certbot
sudo apt install -y certbot python3-certbot-nginx

# 2. 获取证书
sudo certbot --nginx -d 13.115.21.77

# 3. 自动续期测试
sudo certbot renew --dry-run

# 4. 配置自动续期（crontab）
0 0 * * * certbot renew --quiet
```

### 方案2：上传自签名证书

```bash
# 1. 生成自签名证书
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/hustle/private/selfsigned.key \
  -out /etc/ssl/hustle/certs/selfsigned.crt \
  -subj "/C=CN/ST=Beijing/L=Beijing/O=Hustle/CN=13.115.21.77"

# 2. 设置权限
sudo chmod 600 /etc/ssl/hustle/private/selfsigned.key
sudo chmod 644 /etc/ssl/hustle/certs/selfsigned.crt

# 3. 更新Nginx配置
sudo nano /etc/nginx/sites-available/hustle

# 添加SSL配置
ssl_certificate /etc/ssl/hustle/certs/selfsigned.crt;
ssl_certificate_key /etc/ssl/hustle/private/selfsigned.key;

# 4. 测试并重启Nginx
sudo nginx -t
sudo systemctl reload nginx
```

### 方案3：使用CA签名证书

```bash
# 1. 将证书文件上传到服务器
scp your_cert.crt user@13.115.21.77:/tmp/
scp your_key.key user@13.115.21.77:/tmp/
scp your_chain.crt user@13.115.21.77:/tmp/

# 2. 移动到证书目录
sudo mv /tmp/your_cert.crt /etc/ssl/hustle/certs/
sudo mv /tmp/your_key.key /etc/ssl/hustle/private/
sudo mv /tmp/your_chain.crt /etc/ssl/hustle/chains/

# 3. 设置权限
sudo chmod 644 /etc/ssl/hustle/certs/your_cert.crt
sudo chmod 600 /etc/ssl/hustle/private/your_key.key
sudo chmod 644 /etc/ssl/hustle/chains/your_chain.crt

# 4. 更新Nginx配置
ssl_certificate /etc/ssl/hustle/certs/your_cert.crt;
ssl_certificate_key /etc/ssl/hustle/private/your_key.key;
ssl_trusted_certificate /etc/ssl/hustle/chains/your_chain.crt;

# 5. 重启Nginx
sudo nginx -t && sudo systemctl reload nginx
```

---

## 🔍 功能验证

### 1. 验证证书文件

```bash
# 查看证书信息
openssl x509 -in /etc/ssl/hustle/certs/your_cert.crt -text -noout

# 查看证书过期时间
openssl x509 -in /etc/ssl/hustle/certs/your_cert.crt -noout -dates

# 验证证书和私钥匹配
openssl x509 -noout -modulus -in /etc/ssl/hustle/certs/your_cert.crt | openssl md5
openssl rsa -noout -modulus -in /etc/ssl/hustle/private/your_key.key | openssl md5
```

### 2. 验证HTTPS访问

```bash
# 测试HTTPS连接
curl -I https://13.115.21.77

# 查看SSL证书详情
openssl s_client -connect 13.115.21.77:443 -servername 13.115.21.77

# 使用SSL Labs测试（在线工具）
# https://www.ssllabs.com/ssltest/analyze.html?d=13.115.21.77
```

### 3. 运行过期检查脚本

```bash
# 手动运行检查
python scripts/check_ssl_expiry.py

# 查看检查日志
tail -f /var/log/hustle/ssl_check.log
```

---

## 📊 API接口清单

| 方法 | 路径 | 功能 | 权限要求 |
|------|------|------|----------|
| GET | `/api/v1/ssl/certificates` | 获取证书列表 | ssl:list |
| GET | `/api/v1/ssl/certificates/{id}` | 获取证书详情 | ssl:detail |
| POST | `/api/v1/ssl/certificates` | 上传证书 | ssl:upload |
| POST | `/api/v1/ssl/certificates/{id}/deploy` | 部署证书 | ssl:deploy |
| DELETE | `/api/v1/ssl/certificates/{id}` | 删除证书 | ssl:delete |
| GET | `/api/v1/ssl/certificates/{id}/status` | 获取状态 | ssl:status |
| GET | `/api/v1/ssl/certificates/{id}/logs` | 获取日志 | ssl:logs |

---

## 🎯 使用场景

### 场景1：部署Let's Encrypt证书

```bash
# 1. 使用Certbot获取证书
sudo certbot certonly --standalone -d 13.115.21.77

# 2. 通过API上传证书
curl -X POST "http://localhost:8000/api/v1/ssl/certificates" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "cert_name": "Let'\''s Encrypt证书",
    "domain_name": "13.115.21.77",
    "cert_type": "letsencrypt",
    "cert_content": "'$(cat /etc/letsencrypt/live/13.115.21.77/fullchain.pem)'",
    "key_content": "'$(cat /etc/letsencrypt/live/13.115.21.77/privkey.pem)'",
    "auto_renew": true
  }'

# 3. 部署证书
curl -X POST "http://localhost:8000/api/v1/ssl/certificates/{cert_id}/deploy" \
  -H "Authorization: Bearer <token>"
```

### 场景2：证书过期提醒

```bash
# 查看即将过期的证书（30天内）
curl -X GET "http://localhost:8000/api/v1/ssl/certificates?status=expiring_soon" \
  -H "Authorization: Bearer <token>"

# 查看已过期的证书
curl -X GET "http://localhost:8000/api/v1/ssl/certificates?status=expired" \
  -H "Authorization: Bearer <token>"
```

### 场景3：证书续期

```bash
# 1. 使用Certbot续期
sudo certbot renew

# 2. 上传新证书
curl -X POST "http://localhost:8000/api/v1/ssl/certificates" \
  -H "Authorization: Bearer <token>" \
  -d '{...}'

# 3. 部署新证书
curl -X POST "http://localhost:8000/api/v1/ssl/certificates/{new_cert_id}/deploy" \
  -H "Authorization: Bearer <token>"

# 4. 删除旧证书
curl -X DELETE "http://localhost:8000/api/v1/ssl/certificates/{old_cert_id}" \
  -H "Authorization: Bearer <token>"
```

---

## ⚠️ 注意事项

1. **证书文件权限**
   - 证书文件：644 (可读)
   - 私钥文件：600 (仅所有者可读)
   - 目录权限：755/700

2. **证书验证**
   - 上传前验证证书格式
   - 确保证书和私钥匹配
   - 检查证书有效期

3. **部署限制**
   - 正在使用的证书无法删除
   - 已过期的证书无法部署
   - 部署前备份旧证书

4. **自动续期**
   - Let's Encrypt证书90天有效期
   - 建议提前30天续期
   - 配置自动续期任务

5. **安全建议**
   - 使用强加密算法（TLS 1.3）
   - 定期更新证书
   - 监控证书过期状态

---

## 🐛 故障排查

### 问题1: 证书上传失败

```bash
# 检查证书格式
openssl x509 -in your_cert.crt -text -noout

# 检查私钥格式
openssl rsa -in your_key.key -check

# 验证证书和私钥匹配
openssl x509 -noout -modulus -in your_cert.crt | openssl md5
openssl rsa -noout -modulus -in your_key.key | openssl md5
```

### 问题2: Nginx配置错误

```bash
# 测试Nginx配置
sudo nginx -t

# 查看Nginx错误日志
sudo tail -f /var/log/nginx/error.log

# 重新加载配置
sudo systemctl reload nginx
```

### 问题3: HTTPS访问失败

```bash
# 检查防火墙
sudo ufw status
sudo ufw allow 443/tcp

# 检查端口监听
sudo netstat -tlnp | grep 443

# 测试SSL连接
openssl s_client -connect 13.115.21.77:443
```

---

## 📈 下一步

1. **实施权限拦截中间件** - 自动权限验证
2. **开发前端管理页面** - Vue3可视化界面
3. **集成告警通知** - 邮件/钉钉/企业微信

---

**部署状态**: ✅ SSL证书API已就绪，可立即使用
**测试建议**: 先使用自签名证书测试功能，确认无误后再部署生产证书
**安全提示**: 私钥文件务必妥善保管，不要泄露
