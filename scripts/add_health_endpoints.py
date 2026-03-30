"""
脚本：为 Windows Agent 添加健康检查端点
使用方法：在 Windows 服务器上运行此脚本
python add_health_endpoints.py
"""

import shutil
from pathlib import Path

MAIN_PY_PATH = Path("C:/MT5Agent/main.py")
BACKUP_PATH = Path("C:/MT5Agent/main.py.backup")

HEALTH_ENDPOINTS_CODE = '''
import httpx
from datetime import datetime
from fastapi import Query


@app.get("/instances/{port}/health")
async def check_instance_health(port: int):
    """检查实例健康状态"""
    instances = load_instances()
    port_str = str(port)

    if port_str not in instances:
        raise HTTPException(status_code=404, detail=f"Instance on port {port} not found")

    running = is_port_in_use(port)
    mt5_connected = False
    bridge_status = "unknown"

    if running:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"http://localhost:{port}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    mt5_connected = data.get("mt5", False)
                    bridge_status = "healthy" if mt5_connected else "mt5_disconnected"
                else:
                    bridge_status = "unhealthy"
        except httpx.TimeoutException:
            bridge_status = "timeout"
        except Exception:
            bridge_status = "error"
    else:
        bridge_status = "stopped"

    return {
        "port": port,
        "running": running,
        "mt5_connected": mt5_connected,
        "bridge_status": bridge_status,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/instances/batch/health")
async def check_batch_health(ports: str = Query(..., description="Comma-separated port numbers")):
    """Batch check instance health"""
    port_list = [int(p.strip()) for p in ports.split(",")]
    results = []

    for port in port_list:
        try:
            health = await check_instance_health(port)
            results.append(health)
        except HTTPException:
            results.append({
                "port": port,
                "running": False,
                "mt5_connected": False,
                "bridge_status": "not_found",
                "timestamp": datetime.now().isoformat()
            })

    return {"results": results, "total": len(results)}

'''

def main():
    # 备份原文件
    if MAIN_PY_PATH.exists():
        shutil.copy(MAIN_PY_PATH, BACKUP_PATH)
        print(f"Backup created: {BACKUP_PATH}")

    # 读取文件
    with open(MAIN_PY_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # 检查是否已经添加
    if '/instances/{port}/health' in content:
        print("Health check endpoints already exist!")
        return

    # 找到插入位置
    marker = 'if __name__ == "__main__":'
    if marker not in content:
        print(f"Error: Could not find marker: {marker}")
        return

    # 插入代码
    new_content = content.replace(marker, HEALTH_ENDPOINTS_CODE + '\n\n' + marker)

    # 写回文件
    with open(MAIN_PY_PATH, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print("Health check endpoints added successfully!")
    print("Please restart the MT5 Agent service.")

if __name__ == "__main__":
    main()
