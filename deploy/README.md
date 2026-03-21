# Hustle2026 Go Gateway — 部署说明

## 服务器
- Linux: 18.183.36.187 (Ubuntu)
- Go 服务端口: 8080
- 域名: go.hustle2026.xyz

## 环境变量
见 hustle-go.service，主要配置：
- SERVER_PORT=8080
- DATABASE_URL=postgres://postgres:<密码>@127.0.0.1:5432/postgres
- MT5_SERVICE_URL=http://54.249.66.53:8001
- REDIS_URL=redis://127.0.0.1:6379/0

## 启动
sudo systemctl start hustle-go

## 数据库恢复
psql -U postgres -h 127.0.0.1 postgres < hustle2026_db_backup.sql

## Nginx
cp deploy/nginx-hustle-go.conf /etc/nginx/sites-available/hustle-go
ln -sf /etc/nginx/sites-available/hustle-go /etc/nginx/sites-enabled/hustle-go
nginx -t && systemctl reload nginx
