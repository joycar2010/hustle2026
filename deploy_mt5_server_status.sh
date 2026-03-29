#!/bin/bash
# 部署 MT5 服务器状态监控功能

echo "=== 部署 MT5 服务器状态监控 ==="

# 1. 创建 mt5_server.py
cat > /home/ubuntu/hustle2026/backend/app/api/v1/mt5_server.py << 'EOF'
"""MT5 Server Status API"""
from fastapi import APIRouter
from app.services.mt5_agent_service import MT5AgentService

router = APIRouter()

@router.get("/mt5-server/status")
async def get_mt5_server_status():
    """Get MT5 server status via Windows Agent"""
    try:
        # Use internal IP for Windows Agent
        agent = MT5AgentService(server_ip="172.31.14.113", agent_port=9000)

        # Get health check
        health = await agent._http_request("/")

        # Get instances list
        instances_resp = await agent._http_request("/instances")
        instances = instances_resp.get("instances", {})

        # Parse uptime from health response
        uptime_str = "--"
        uptime_sec = health.get("uptime", 0)
        if uptime_sec > 86400:
            days = uptime_sec // 86400
            hours = (uptime_sec % 86400) // 3600
            uptime_str = f"{days}天{hours}时"
        elif uptime_sec > 0:
            hours = uptime_sec // 3600
            minutes = (uptime_sec % 3600) // 60
            uptime_str = f"{hours}时{minutes}分"

        return {
            "online": True,
            "uptime": uptime_str,
            "memory": health.get("memory", "--"),
            "cpu": health.get("cpu", "--"),
            "instances": len(instances)
        }
    except Exception as e:
        return {
            "online": False,
            "uptime": "--",
            "memory": "--",
            "cpu": "--",
            "instances": 0
        }
EOF

# 2. 更新 main.py - 添加 import
sed -i 's/from app.api.v1 import auth, users, accounts, strategies, market, websocket, risk, automation, system, trading, test, rbac, security_components, ssl_certificates, key_management, notifications, sound_files, health, arbitrage_opportunities, system_monitor, timing_configs, proxies, mt5_clients, performance/from app.api.v1 import auth, users, accounts, strategies, market, websocket, risk, automation, system, trading, test, rbac, security_components, ssl_certificates, key_management, notifications, sound_files, health, arbitrage_opportunities, system_monitor, timing_configs, proxies, mt5_clients, performance, mt5_server/' /home/ubuntu/hustle2026/backend/app/main.py

# 3. 更新 main.py - 添加路由
sed -i '/app.include_router(performance.router, prefix="\/api\/v1\/performance", tags=\["性能监控"\])/a app.include_router(mt5_server.router, prefix="/api/v1", tags=["MT5服务器状态"])' /home/ubuntu/hustle2026/backend/app/main.py

# 4. 重启后端服务
echo "重启后端服务..."
sudo systemctl restart hustle-backend

# 5. 等待服务启动
sleep 3

# 6. 测试接口
echo "测试 MT5 服务器状态接口..."
curl -s http://localhost:8000/api/v1/mt5-server/status | python3 -m json.tool

echo "=== 部署完成 ==="
