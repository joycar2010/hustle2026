# 交易管理系统 - 完整实施方案

**项目地址**: http://13.115.21.77:3000/system
**实施日期**: 2026-02-24
**技术栈**: FastAPI + PostgreSQL + Redis + Vue3 + TailwindCSS

---

## 📋 目录

1. [数据库设计](#数据库设计)
2. [后端开发](#后端开发)
3. [前端开发](#前端开发)
4. [服务器配置](#服务器配置)
5. [部署指南](#部署指南)
6. [测试验证](#测试验证)

---

## 一、数据库设计

### 1.1 表结构说明

已创建的数据库表：
- `roles` - 角色表
- `permissions` - 权限表
- `user_roles` - 用户-角色关联表
- `role_permissions` - 角色-权限关联表
- `security_components` - 安全组件配置表
- `security_component_logs` - 安全组件日志表
- `ssl_certificates` - SSL证书表
- `ssl_certificate_logs` - SSL证书日志表

### 1.2 执行迁移

```bash
# 连接数据库
psql -h localhost -U hustle_user -d hustle_db

# 执行迁移脚本
\i database/migrations/create_rbac_security_tables.sql
```

---

## 二、后端开发

### 2.1 模型文件清单

已创建的模型文件：
- `backend/app/models/role.py` - 角色模型
- `backend/app/models/permission.py` - 权限模型

需要继续创建的模型：
- `backend/app/models/user_role.py` - 用户角色关联模型
- `backend/app/models/role_permission.py` - 角色权限关联模型
- `backend/app/models/security_component.py` - 安全组件模型
- `backend/app/models/ssl_certificate.py` - SSL证书模型

### 2.2 API接口清单

#### 权限管理模块 (`/api/v1/rbac`)
- `GET /roles` - 获取角色列表
- `POST /roles` - 创建角色
- `PUT /roles/{id}` - 更新角色
- `DELETE /roles/{id}` - 删除角色
- `GET /permissions` - 获取权限列表
- `POST /roles/{id}/permissions` - 分配权限
- `POST /roles/{id}/copy` - 复制角色
- `POST /users/{id}/roles` - 分配角色

#### 安全组件模块 (`/api/v1/security`)
- `GET /components` - 获取组件列表
- `POST /components/{id}/enable` - 启用组件
- `POST /components/{id}/disable` - 禁用组件
- `PUT /components/{id}/config` - 更新配置
- `GET /components/{id}/status` - 获取状态

#### SSL证书模块 (`/api/v1/ssl`)
- `GET /certificates` - 获取证书列表
- `POST /certificates` - 上传证书
- `POST /certificates/{id}/deploy` - 部署证书
- `DELETE /certificates/{id}` - 删除证书
- `GET /certificates/{id}/status` - 获取证书状态

### 2.3 Redis缓存策略

```python
# 权限缓存键格式
user_permissions:{user_id} = Set[permission_code]  # 过期时间: 1小时
role_permissions:{role_id} = Set[permission_code]  # 过期时间: 24小时

# 安全组件状态缓存
security_component:{component_code} = {status, config}  # 过期时间: 5分钟

# WebSocket连接状态
ws_connections:{user_id} = Set[connection_id]  # 过期时间: 会话结束
```

---

## 三、前端开发

### 3.1 页面组件清单

#### 权限管理模块
- `frontend/src/views/system/RoleManagement.vue` - 角色管理页面
- `frontend/src/views/system/PermissionManagement.vue` - 权限管理页面
- `frontend/src/components/rbac/RoleForm.vue` - 角色表单组件
- `frontend/src/components/rbac/PermissionTree.vue` - 权限树组件

#### 安全组件模块
- `frontend/src/views/system/SecurityComponents.vue` - 安全组件管理页面
- `frontend/src/components/security/ComponentCard.vue` - 组件卡片
- `frontend/src/components/security/ComponentConfig.vue` - 配置表单

#### SSL证书模块
- `frontend/src/views/system/SSLCertificates.vue` - SSL证书管理页面
- `frontend/src/components/ssl/CertificateUpload.vue` - 证书上传组件
- `frontend/src/components/ssl/CertificateStatus.vue` - 证书状态组件

### 3.2 Pinia Store

```javascript
// stores/permission.js - 权限状态管理
// stores/security.js - 安全组件状态管理
// stores/ssl.js - SSL证书状态管理
```

---

## 四、服务器配置

### 4.1 Nginx配置 (HTTPS)

文件位置: `/etc/nginx/sites-available/hustle`

```nginx
# HTTP重定向到HTTPS
server {
    listen 80;
    server_name 13.115.21.77;
    return 301 https://$server_name$request_uri;
}

# HTTPS配置
server {
    listen 443 ssl http2;
    server_name 13.115.21.77;

    # SSL证书配置
    ssl_certificate /etc/ssl/certs/hustle.crt;
    ssl_certificate_key /etc/ssl/private/hustle.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # 前端静态文件
    location / {
        root /var/www/hustle/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # 后端API代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket代理
    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

### 4.2 Gunicorn + Uvicorn配置

文件位置: `backend/gunicorn_config.py`

```python
import multiprocessing

# 服务器绑定
bind = "127.0.0.1:8000"

# Worker配置
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# 超时配置
timeout = 120
keepalive = 5

# 日志配置
accesslog = "/var/log/hustle/access.log"
errorlog = "/var/log/hustle/error.log"
loglevel = "info"

# 进程命名
proc_name = "hustle_backend"

# 优雅重启
graceful_timeout = 30
```

### 4.3 Systemd服务配置

文件位置: `/etc/systemd/system/hustle-backend.service`

```ini
[Unit]
Description=Hustle XAU Arbitrage System Backend
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=hustle
Group=hustle
WorkingDirectory=/var/www/hustle/backend
Environment="PATH=/var/www/hustle/backend/venv/bin"
ExecStart=/var/www/hustle/backend/venv/bin/gunicorn -c gunicorn_config.py app.main:app
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

---

## 五、部署指南

### 5.1 环境准备

```bash
# 1. 更新系统
sudo apt update && sudo apt upgrade -y

# 2. 安装依赖
sudo apt install -y python3.11 python3.11-venv postgresql-15 redis-server nginx

# 3. 创建应用用户
sudo useradd -m -s /bin/bash hustle

# 4. 创建目录结构
sudo mkdir -p /var/www/hustle/{backend,frontend}
sudo mkdir -p /var/log/hustle
sudo mkdir -p /etc/ssl/hustle
sudo chown -R hustle:hustle /var/www/hustle
sudo chown -R hustle:hustle /var/log/hustle
```

### 5.2 后端部署

```bash
# 1. 切换到hustle用户
sudo su - hustle

# 2. 创建虚拟环境
cd /var/www/hustle/backend
python3.11 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install --upgrade pip
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑.env文件，配置SECRET_KEY、ENCRYPTION_KEY、数据库连接等

# 5. 执行数据库迁移
psql -h localhost -U hustle_user -d hustle_db -f database/migrations/create_rbac_security_tables.sql

# 6. 测试启动
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 5.3 前端部署

```bash
# 1. 安装Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# 2. 构建前端
cd /var/www/hustle/frontend
npm install
npm run build

# 3. 部署到Nginx
sudo cp -r dist/* /var/www/hustle/frontend/dist/
```

### 5.4 SSL证书部署

```bash
# 方案1: 使用Let's Encrypt (推荐)
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 13.115.21.77

# 方案2: 使用自签名证书 (开发环境)
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/hustle.key \
  -out /etc/ssl/certs/hustle.crt

# 设置权限
sudo chmod 600 /etc/ssl/private/hustle.key
sudo chmod 644 /etc/ssl/certs/hustle.crt
```

### 5.5 启动服务

```bash
# 1. 启动Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# 2. 启动PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# 3. 启动后端服务
sudo systemctl start hustle-backend
sudo systemctl enable hustle-backend

# 4. 启动Nginx
sudo nginx -t  # 测试配置
sudo systemctl start nginx
sudo systemctl enable nginx

# 5. 查看服务状态
sudo systemctl status hustle-backend
sudo systemctl status nginx
```

---

## 六、测试验证

### 6.1 HTTPS访问测试

```bash
# 测试HTTP重定向
curl -I http://13.115.21.77

# 测试HTTPS访问
curl -k https://13.115.21.77

# 测试API接口
curl -k https://13.115.21.77/api/v1/health
```

### 6.2 WebSocket连接测试

```javascript
// 前端测试代码
const token = localStorage.getItem('access_token')
const ws = new WebSocket(`wss://13.115.21.77/ws?token=${token}`)

ws.onopen = () => console.log('WebSocket connected')
ws.onmessage = (event) => console.log('Message:', event.data)
ws.onerror = (error) => console.error('WebSocket error:', error)
```

### 6.3 权限控制测试

```bash
# 1. 登录获取Token
curl -X POST https://13.115.21.77/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password"}'

# 2. 测试权限接口
curl -X GET https://13.115.21.77/api/v1/rbac/roles \
  -H "Authorization: Bearer <token>"

# 3. 测试无权限访问
curl -X DELETE https://13.115.21.77/api/v1/users/123 \
  -H "Authorization: Bearer <token>"
```

### 6.4 性能测试

```bash
# 使用ab进行压力测试
ab -n 1000 -c 10 -H "Authorization: Bearer <token>" \
  https://13.115.21.77/api/v1/market/data

# 使用wrk进行性能测试
wrk -t4 -c100 -d30s --latency \
  -H "Authorization: Bearer <token>" \
  https://13.115.21.77/api/v1/trading
```

---

## 七、监控与维护

### 7.1 日志查看

```bash
# 后端日志
tail -f /var/log/hustle/error.log
tail -f /var/log/hustle/access.log

# Nginx日志
tail -f /var/log/nginx/error.log
tail -f /var/log/nginx/access.log

# 系统日志
journalctl -u hustle-backend -f
```

### 7.2 性能监控

```bash
# 查看进程状态
ps aux | grep gunicorn
ps aux | grep nginx

# 查看端口占用
netstat -tlnp | grep 8000
netstat -tlnp | grep 443

# 查看资源使用
htop
```

### 7.3 备份策略

```bash
# 数据库备份 (每日凌晨2点)
0 2 * * * /var/www/hustle/scripts/backup_database.sh

# SSL证书备份
sudo cp /etc/ssl/certs/hustle.crt /backup/ssl/
sudo cp /etc/ssl/private/hustle.key /backup/ssl/
```

---

## 八、故障排查

### 8.1 常见问题

**问题1**: WebSocket连接失败
```bash
# 检查Nginx配置
sudo nginx -t

# 检查防火墙
sudo ufw status
sudo ufw allow 443/tcp

# 检查后端日志
tail -f /var/log/hustle/error.log
```

**问题2**: SSL证书错误
```bash
# 验证证书
openssl x509 -in /etc/ssl/certs/hustle.crt -text -noout

# 检查证书过期时间
openssl x509 -in /etc/ssl/certs/hustle.crt -noout -dates

# 重新部署证书
sudo certbot renew --force-renewal
```

**问题3**: 权限缓存不生效
```bash
# 清空Redis缓存
redis-cli FLUSHDB

# 重启Redis
sudo systemctl restart redis-server

# 检查Redis连接
redis-cli ping
```

---

## 九、安全加固

### 9.1 防火墙配置

```bash
# 启用UFW
sudo ufw enable

# 允许SSH
sudo ufw allow 22/tcp

# 允许HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 拒绝其他端口
sudo ufw default deny incoming
sudo ufw default allow outgoing
```

### 9.2 Fail2Ban配置

```bash
# 安装Fail2Ban
sudo apt install -y fail2ban

# 配置Nginx保护
sudo nano /etc/fail2ban/jail.local

[nginx-http-auth]
enabled = true
port = http,https
logpath = /var/log/nginx/error.log
```

---

## 十、后续优化建议

1. **性能优化**
   - 启用Redis集群
   - 配置CDN加速
   - 实现API响应缓存

2. **安全增强**
   - 启用WAF (ModSecurity)
   - 配置DDoS防护
   - 实现API速率限制

3. **监控告警**
   - 集成Prometheus + Grafana
   - 配置告警规则
   - 实现日志聚合 (ELK)

4. **高可用**
   - 配置负载均衡
   - 实现数据库主从复制
   - 部署容器化 (Docker + Kubernetes)

---

**文档版本**: 1.0
**最后更新**: 2026-02-24
**维护人员**: 系统管理员
