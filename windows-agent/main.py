"""
Windows Agent - MT5实例管理服务
运行在Windows服务器上，通过FastAPI提供MT5实例管理接口
"""
import os
import sys
import json
import subprocess
import psutil
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

app = FastAPI(title="MT5 Windows Agent", version="1.0.0")

# 实例配置存储路径
INSTANCES_CONFIG_FILE = Path("C:/MT5Agent/instances.json")
INSTANCES_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)


class InstanceDeployRequest(BaseModel):
    """部署实例请求"""
    port: int = Field(..., ge=1024, le=65535)
    mt5_path: str
    deploy_path: str
    auto_start: bool = True
    account: Optional[str] = None
    server: Optional[str] = None


def load_instances() -> Dict:
    """加载实例配置"""
    if not INSTANCES_CONFIG_FILE.exists():
        return {}
    try:
        with open(INSTANCES_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_instances(instances: Dict):
    """保存实例配置"""
    with open(INSTANCES_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(instances, f, indent=2, ensure_ascii=False)


def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用"""
    for conn in psutil.net_connections():
        if conn.laddr.port == port and conn.status == 'LISTEN':
            return True
    return False


def get_process_by_port(port: int) -> Optional[psutil.Process]:
    """根据端口获取进程"""
    for conn in psutil.net_connections():
        if conn.laddr.port == port and conn.status == 'LISTEN':
            try:
                return psutil.Process(conn.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None
    return None


@app.get("/")
async def health():
    """健康检查"""
    return {"status": "healthy", "service": "MT5 Windows Agent"}


@app.get("/instances")
async def list_instances():
    """列出所有实例"""
    instances = load_instances()
    result = []
    for port_str, config in instances.items():
        port = int(port_str)
        status = "stopped"
        if is_port_in_use(port):
            status = "running"
        result.append({
            "port": port,
            "status": status,
            **config
        })
    return {"instances": result}


@app.post("/instances/deploy")
async def deploy_instance(req: InstanceDeployRequest):
    """部署新实例"""
    instances = load_instances()
    port_str = str(req.port)

    # 检查端口是否已被占用
    if is_port_in_use(req.port):
        raise HTTPException(status_code=400, detail=f"Port {req.port} is already in use")

    # 检查MT5路径是否存在
    if not Path(req.mt5_path).exists():
        raise HTTPException(status_code=400, detail=f"MT5 path not found: {req.mt5_path}")

    # 保存实例配置
    instances[port_str] = {
        "mt5_path": req.mt5_path,
        "deploy_path": req.deploy_path,
        "auto_start": req.auto_start,
        "account": req.account,
        "server": req.server
    }
    save_instances(instances)

    return {"message": "Instance deployed successfully", "port": req.port}


@app.post("/instances/{port}/start")
async def start_instance(port: int):
    """启动实例"""
    instances = load_instances()
    port_str = str(port)

    if port_str not in instances:
        raise HTTPException(status_code=404, detail=f"Instance on port {port} not found")

    if is_port_in_use(port):
        return {"message": "Instance is already running", "port": port}

    # 这里应该启动MT5服务进程
    # 实际实现需要根据具体的MT5服务启动方式
    return {"message": "Instance started", "port": port}


@app.post("/instances/{port}/stop")
async def stop_instance(port: int):
    """停止实例"""
    proc = get_process_by_port(port)
    if not proc:
        return {"message": "Instance is not running", "port": port}

    try:
        proc.terminate()
        proc.wait(timeout=10)
    except psutil.TimeoutExpired:
        proc.kill()

    return {"message": "Instance stopped", "port": port}


@app.post("/instances/{port}/restart")
async def restart_instance(port: int):
    """重启实例"""
    await stop_instance(port)
    await start_instance(port)
    return {"message": "Instance restarted", "port": port}


@app.get("/instances/{port}/status")
async def get_instance_status(port: int):
    """获取实例状态"""
    instances = load_instances()
    port_str = str(port)

    if port_str not in instances:
        raise HTTPException(status_code=404, detail=f"Instance on port {port} not found")

    status = "running" if is_port_in_use(port) else "stopped"
    return {"port": port, "status": status, **instances[port_str]}


@app.delete("/instances/{port}")
async def delete_instance(port: int):
    """删除实例"""
    instances = load_instances()
    port_str = str(port)

    if port_str not in instances:
        raise HTTPException(status_code=404, detail=f"Instance on port {port} not found")

    # 如果实例正在运行，先停止
    if is_port_in_use(port):
        await stop_instance(port)

    # 删除配置
    del instances[port_str]
    save_instances(instances)

    return {"message": "Instance deleted", "port": port}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
