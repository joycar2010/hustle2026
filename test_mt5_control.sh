#!/bin/bash

# MT5 远程控制功能测试脚本

echo "=== MT5 远程控制功能测试 ==="
echo ""

# 1. 测试 Windows Agent 健康状态
echo "1. 测试 Windows Agent 健康状态..."
curl -s -H "X-API-Key: hustle2026_mt5_agent_secure_key_2024" \
  http://172.31.14.113:8765/health | python3 -m json.tool
echo ""

# 2. 测试获取实例列表
echo "2. 测试获取实例列表..."
curl -s -H "X-API-Key: hustle2026_mt5_agent_secure_key_2024" \
  http://172.31.14.113:8765/instances | python3 -m json.tool
echo ""

# 3. 测试获取特定实例状态
echo "3. 测试获取 bybit_system_service 实例状态..."
curl -s -H "X-API-Key: hustle2026_mt5_agent_secure_key_2024" \
  http://172.31.14.113:8765/instances/bybit_system_service | python3 -m json.tool
echo ""

echo "=== 测试完成 ==="
