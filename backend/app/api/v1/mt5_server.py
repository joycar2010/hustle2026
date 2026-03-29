"""MT5 Server Status API"""
from fastapi import APIRouter, HTTPException
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
