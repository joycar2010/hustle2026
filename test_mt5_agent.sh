#!/bin/bash
# MT5 Agent 端到端测试脚本

echo "=========================================="
echo "MT5 Windows Agent 端到端测试"
echo "=========================================="
echo ""

# 测试 1: Windows Agent 健康检查
echo "测试 1: Windows Agent 健康检查"
echo "URL: http://172.31.14.113:8765/health"
AGENT_HEALTH=$(curl -s -H "X-API-Key: hustle2026_mt5_agent_secure_key_2024" http://172.31.14.113:8765/health)
echo "响应: $AGENT_HEALTH"
if echo "$AGENT_HEALTH" | grep -q "ok"; then
    echo "✅ Windows Agent 运行正常"
else
    echo "❌ Windows Agent 健康检查失败"
fi
echo ""

# 测试 2: Windows Agent 实例列表
echo "测试 2: Windows Agent 实例列表"
echo "URL: http://172.31.14.113:8765/instances"
INSTANCES=$(curl -s -H "X-API-Key: hustle2026_mt5_agent_secure_key_2024" http://172.31.14.113:8765/instances)
echo "响应: $INSTANCES"
if echo "$INSTANCES" | grep -q "bybit_system_service"; then
    echo "✅ 实例列表获取成功"
else
    echo "❌ 实例列表获取失败"
fi
echo ""

# 测试 3: 后端代理 API（需要登录）
echo "测试 3: 后端代理 API"
echo "URL: https://admin.hustle2026.xyz/api/v1/mt5-agent/instances"
echo "注意: 需要管理员账户登录"
echo ""

echo "=========================================="
echo "测试完成"
echo "=========================================="
echo ""
echo "下一步:"
echo "1. 等待前端构建完成"
echo "2. 访问 https://admin.hustle2026.xyz/users"
echo "3. 切换到「MT5账户管理」标签"
echo "4. 选择用户和账户"
echo "5. 查看 MT5 客户端卡片中的「控制 MT5 服务器」区域"
