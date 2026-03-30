#!/bin/bash
# MT5 状态优化功能部署脚本
# 在 Ubuntu 服务器上执行此脚本

set -e  # 遇到错误立即退出

echo "========================================="
echo "MT5 状态优化功能部署脚本"
echo "========================================="

# 1. 拉取最新代码
echo ""
echo "[1/5] 拉取最新代码..."
cd /home/ubuntu/hustle2026
git fetch origin
git checkout go
git pull origin go

# 2. 重启后端服务
echo ""
echo "[2/5] 重启后端服务..."
sudo systemctl restart hustle-backend

# 等待服务启动
echo "等待服务启动..."
sleep 5

# 检查服务状态
echo "检查服务状态..."
sudo systemctl status hustle-backend --no-pager | head -20

# 检查 MT5SyncService 是否启动
echo ""
echo "检查 MT5SyncService 日志..."
sudo journalctl -u hustle-backend -n 50 | grep -i "mt5.*sync" || echo "未找到 MT5 sync 相关日志"

# 3. 构建前端
echo ""
echo "[3/5] 构建前端..."
cd /home/ubuntu/hustle2026/frontend
npm run build:admin

# 4. 部署前端
echo ""
echo "[4/5] 部署前端到 nginx..."
sudo cp -r dist-admin/* /var/www/admin.hustle2026.xyz/

# 5. 验证部署
echo ""
echo "[5/5] 验证部署..."

# 检查后端 API
echo "测试后端 API..."
curl -s -I https://admin.hustle2026.xyz/api/v1/monitor/status | head -5

# 检查前端
echo ""
echo "测试前端..."
curl -s -I https://admin.hustle2026.xyz/ | head -5

echo ""
echo "========================================="
echo "部署完成！"
echo "========================================="
echo ""
echo "下一步："
echo "1. 重启 Windows Agent (在 Windows 服务器上执行)"
echo "2. 访问 https://admin.hustle2026.xyz/ 测试功能"
echo ""
echo "验证清单："
echo "- [ ] MasterDashboard 每 5 秒刷新 MT5 状态"
echo "- [ ] MasterDashboard 显示进程状态和最后心跳"
echo "- [ ] MasterDashboard 控制按钮可点击"
echo "- [ ] UserManagement 操作时启动 3 秒轮询"
echo ""
