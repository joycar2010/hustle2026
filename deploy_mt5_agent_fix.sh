#!/bin/bash
# 部署 MT5AgentService 修复到后端服务器

set -e

echo "=========================================="
echo "部署 MT5AgentService 修复"
echo "=========================================="
echo ""

# 1. 拉取最新代码
echo "[1/4] 拉取最新代码..."
cd /data/hustle2026
git fetch origin
git checkout main
git pull origin main
echo "✓ 代码已更新"
echo ""

# 2. 备份当前服务
echo "[2/4] 备份当前服务..."
cp backend/app/services/mt5_agent_service.py backend/app/services/mt5_agent_service.py.backup_$(date +%Y%m%d_%H%M%S)
echo "✓ 备份完成"
echo ""

# 3. 重启后端服务
echo "[3/4] 重启后端服务..."
sudo systemctl restart hustle-python
sleep 3
echo "✓ 服务已重启"
echo ""

# 4. 验证服务状态
echo "[4/4] 验证服务状态..."
if sudo systemctl is-active --quiet hustle-python; then
    echo "✓ 后端服务运行正常"
else
    echo "✗ 后端服务启动失败"
    sudo journalctl -u hustle-python -n 50 --no-pager
    exit 1
fi

# 测试 API
echo ""
echo "测试 MT5 实例 API..."
curl -s https://admin.hustle2026.xyz/api/v1/mt5/instances | python3 -c "import sys, json; data=json.load(sys.stdin); print(f'找到 {len(data)} 个实例')"

echo ""
echo "=========================================="
echo "部署完成！"
echo "=========================================="
