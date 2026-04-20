"""MT5 Server Status API"""
from fastapi import APIRouter, HTTPException
from app.services.mt5_agent_service import MT5AgentService
import os

router = APIRouter()

def _get_agent_config():
    try:
        from sqlalchemy import text
        from app.core.database import SessionLocal
        with SessionLocal() as session:
            row = session.execute(text("SELECT value FROM mt5_config WHERE key = 'agent_url'")).fetchone()
            if row:
                url = row[0]  # e.g. http://172.31.14.113:8765
                parts = url.replace("http://", "").replace("https://", "").split(":")
                return parts[0], int(parts[1]) if len(parts) > 1 else 8765
    except Exception:
        pass
    ip = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113").replace("http://", "").replace("https://", "")
    port = int(os.getenv("MT5_AGENT_PORT", "8765"))
    return ip, port

AGENT_IP, AGENT_PORT = _get_agent_config()


@router.get("/mt5-server/status")
async def get_mt5_server_status():
    """Get MT5 server status via Windows Agent"""
    try:
        agent = MT5AgentService(server_ip=AGENT_IP, agent_port=AGENT_PORT)

        # Agent health: GET /health returns {status, agent, version, session}
        health = await agent._http_request("/health")

        # Instances list: GET /instances returns array
        instances_resp = await agent._http_request("/instances")
        instances = instances_resp if isinstance(instances_resp, list) else instances_resp.get("instances", [])

        # Aggregate memory/cpu from running instances
        total_mem_mb = 0
        running_count = 0
        for inst in instances:
            hs = inst.get("health_status", {})
            if hs.get("is_running"):
                running_count += 1
                details = hs.get("details", {})
                total_mem_mb += details.get("memory_mb", 0)

        return {
            "online": True,
            "uptime": health.get("session", "--"),
            "memory": f"{total_mem_mb:.0f} MB" if total_mem_mb else "--",
            "cpu": f"{running_count} 进程",
            "instances": len(instances),
            "running": running_count,
            "version": health.get("version", "--"),
        }
    except Exception as e:
        return {
            "online": False,
            "uptime": "--",
            "memory": "--",
            "cpu": "--",
            "instances": 0,
            "running": 0,
            "version": "--",
        }
