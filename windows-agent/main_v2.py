"""
Windows Agent - MT5实例管理服务（完整版）
运行在Windows服务器上，通过FastAPI提供MT5实例管理接口
支持启动、停止、重启 MT5 客户端（带 /portable 参数）
"""
import os
import sys
import json
import subprocess
import psutil
import time
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

app = FastAPI(title="MT5 Windows Agent", version="2.0.0")

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


def is_mt5_running_by_path(mt5_path: str) -> bool:
    """
    检查指定路径的 MT5 实例是否正在运行（精准判断，避免误判）

    Args:
        mt5_path: MT5 可执行文件的绝对路径

    Returns:
        True 如果该实例正在运行，否则 False
    """
    target_path = os.path.normpath(mt5_path).lower()
    for proc in psutil.process_iter(['name', 'exe']):
        try:
            if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
                proc_path = os.path.normpath(proc.info['exe']).lower()
                if proc_path == target_path:
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False


def start_mt5_in_user_session(mt5_path: str) -> Optional[psutil.Process]:
    """
    在用户会话中启动 MT5 客户端（显示 GUI）

    使用 PowerShell Start-Process 方法，确保 MT5 在当前会话中启动并显示窗口

    Args:
        mt5_path: MT5 可执行文件的绝对路径

    Returns:
        psutil.Process 对象，如果启动失败则返回 None
    """
    try:
        # 1. 检查是否已经在运行
        if is_mt5_running_by_path(mt5_path):
            print(f"MT5 already running: {mt5_path}")
            # 返回已运行的进程
            target_path = os.path.normpath(mt5_path).lower()
            for proc in psutil.process_iter(['name', 'exe']):
                try:
                    if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
                        proc_path = os.path.normpath(proc.info['exe']).lower()
                        if proc_path == target_path:
                            return proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return None

        # 2. 检查路径是否存在
        if not os.path.exists(mt5_path):
            print(f"MT5 path not found: {mt5_path}")
            return None

        mt5_dir = str(Path(mt5_path).parent)

        # 3. 使用 PowerShell Start-Process 启动（推荐方法）
        # 这会在当前会话中启动进程，如果 Windows Agent 在用户会话中运行则有效
        ps_cmd = f'Start-Process -FilePath "{mt5_path}" -ArgumentList "/portable" -WorkingDirectory "{mt5_dir}"'

        subprocess.Popen(
            ["powershell", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        print(f"MT5 start command sent: {mt5_path}")

        # 4. 等待进程启动并验证
        max_wait = 5
        for i in range(max_wait):
            time.sleep(1)
            if is_mt5_running_by_path(mt5_path):
                # 找到并返回进程对象
                target_path = os.path.normpath(mt5_path).lower()
                for proc in psutil.process_iter(['name', 'exe', 'create_time']):
                    try:
                        if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
                            proc_path = os.path.normpath(proc.info['exe']).lower()
                            if proc_path == target_path and time.time() - proc.info['create_time'] < 10:
                                print(f"MT5 started successfully with PID {proc.pid}")
                                return proc
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

        print(f"MT5 start verification failed: {mt5_path}")
        return None

    except Exception as e:
        print(f"Failed to start MT5: {str(e)}")
        return None


def stop_mt5_client_by_path(mt5_path: str) -> bool:
    """
    停止指定路径的 MT5 客户端（精准匹配，避免误杀其他实例）

    Args:
        mt5_path: MT5 可执行文件的绝对路径

    Returns:
        True 如果成功停止，否则 False
    """
    if not is_mt5_running_by_path(mt5_path):
        print(f"MT5 not running: {mt5_path}")
        return True

    target_path = os.path.normpath(mt5_path).lower()
    stopped = False

    try:
        for proc in psutil.process_iter(['name', 'exe', 'pid']):
            try:
                if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
                    proc_path = os.path.normpath(proc.info['exe']).lower()
                    if proc_path == target_path:
                        print(f"Stopping MT5 process PID {proc.info['pid']}: {mt5_path}")
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except psutil.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=2)
                        stopped = True
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if stopped:
            print(f"MT5 stopped successfully: {mt5_path}")
        else:
            print(f"Failed to stop MT5: {mt5_path}")

        return stopped

    except Exception as e:
        print(f"Error stopping MT5: {str(e)}")
        return False


def stop_mt5_client(deploy_path: str, account: str = None) -> bool:
    """
    停止 MT5 客户端（兼容旧接口，推荐使用 stop_mt5_client_by_path）

    策略：
    1. 尝试从 deploy_path 推断 MT5 路径
    2. 如果只有一个 terminal64 进程，直接停止
    3. 如果有多个，停止所有（确保当前实例被停止）

    Args:
        deploy_path: 部署目录路径
        account: MT5 账号（用于日志）

    Returns:
        是否成功停止
    """
    stopped = False
    terminal_procs = []

    # 收集所有 terminal64 进程
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            if proc.info['name'] and 'terminal64.exe' in proc.info['name'].lower():
                terminal_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not terminal_procs:
        return False

    # 如果只有一个 MT5 进程，直接停止它
    if len(terminal_procs) == 1:
        try:
            terminal_procs[0].terminate()
            terminal_procs[0].wait(timeout=5)
            stopped = True
        except psutil.TimeoutExpired:
            terminal_procs[0].kill()
            stopped = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    else:
        # 多个进程：停止所有（简单但有效）
        # 注意：这会影响其他实例，但确保当前实例被停止
        for proc in terminal_procs:
            try:
                proc.terminate()
                stopped = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # 等待进程退出
        time.sleep(2)
        for proc in terminal_procs:
            try:
                if proc.is_running():
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    return stopped


def start_mt5_bridge(mt5_path: str, deploy_path: str, port: int) -> subprocess.Popen:
    """
    启动 MT5 桥接服务

    Args:
        mt5_path: MT5 可执行文件路径
        deploy_path: 部署目录（包含 main.py 的目录）
        port: 服务端口

    Returns:
        启动的进程对象
    """
    # 检查部署目录
    deploy_path_obj = Path(deploy_path)
    if not deploy_path_obj.exists():
        raise FileNotFoundError(f"Deploy path not found: {deploy_path}")

    # 检查 main.py 位置（支持两种结构）
    main_py = deploy_path_obj / "main.py"
    app_main_py = deploy_path_obj / "app" / "main.py"

    if app_main_py.exists():
        # app 目录结构
        use_app_module = True
    elif main_py.exists():
        # 根目录结构
        use_app_module = False
    else:
        raise FileNotFoundError(f"main.py not found in: {deploy_path} or {deploy_path}/app")

    # 检查 MT5 路径
    if not Path(mt5_path).exists():
        raise FileNotFoundError(f"MT5 executable not found: {mt5_path}")

    # 设置环境变量
    env = os.environ.copy()
    env['MT5_PATH'] = mt5_path
    env['MT5_PORTABLE'] = '1'  # 标记使用 portable 模式

    # 启动命令：使用部署目录下的 venv
    venv_python = deploy_path_obj / "venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        # 如果没有 venv，使用系统 Python
        venv_python = "python"

    cmd = [
        str(venv_python),
        "-m", "uvicorn",
        "app.main:app" if use_app_module else "main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
        "--workers", "1"
    ]

    # 启动进程
    process = subprocess.Popen(
        cmd,
        cwd=str(deploy_path_obj),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    )

    # 等待服务启动
    time.sleep(2)

    # 检查进程是否还在运行
    if process.poll() is not None:
        stdout, stderr = process.communicate()
        raise RuntimeError(f"Failed to start MT5 bridge: {stderr.decode()}")

    return process


@app.get("/")
async def health():
    """健康检查 - 包含系统信息"""
    # Get system metrics
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    boot_time = psutil.boot_time()
    uptime_seconds = int(time.time() - boot_time)

    return {
        "status": "healthy",
        "service": "MT5 Windows Agent",
        "version": "2.0.0",
        "uptime": uptime_seconds,
        "cpu": f"{cpu_percent:.1f}%",
        "memory": f"{memory.percent:.1f}%"
    }


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


@app.post("", response_model=dict, status_code=201)
@app.post("/deploy", response_model=dict, status_code=201)
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

    # 检查部署路径
    deploy_path_obj = Path(req.deploy_path)
    if not deploy_path_obj.exists():
        raise HTTPException(status_code=400, detail=f"Deploy path not found: {req.deploy_path}")

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
    """启动实例（只启动 Bridge 服务，MT5 客户端需要预先在 RDP 会话中启动）"""
    instances = load_instances()
    port_str = str(port)

    if port_str not in instances:
        raise HTTPException(status_code=404, detail=f"Instance on port {port} not found")

    if is_port_in_use(port):
        return {"message": "Instance is already running", "port": port}

    config = instances[port_str]
    mt5_process = None
    bridge_process = None

    try:
        # 1. 检查 MT5 客户端是否已在运行
        mt5_path = config["mt5_path"]
        if os.path.exists(mt5_path):
            # 使用精准的路径检查
            if is_mt5_running_by_path(mt5_path):
                print(f"MT5 already running: {mt5_path}")
                # 获取已运行的进程
                target_path = os.path.normpath(mt5_path).lower()
                for proc in psutil.process_iter(['name', 'exe']):
                    try:
                        if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
                            proc_path = os.path.normpath(proc.info['exe']).lower()
                            if proc_path == target_path:
                                mt5_process = proc
                                print(f"Found MT5 process: PID {proc.pid}, SessionId {proc.info.get('sessionid', 'N/A')}")
                                break
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        continue
            else:
                # MT5 未运行，返回提示信息
                raise HTTPException(
                    status_code=400,
                    detail=f"MT5 client is not running. Please start MT5 manually in RDP session first. Path: {mt5_path}"
                )

        # 2. 启动 MT5 桥接服务
        print(f"Starting MT5 Bridge service on port {port}...")
        bridge_process = start_mt5_bridge(
            mt5_path=config["mt5_path"],
            deploy_path=config["deploy_path"],
            port=port
        )

        # 验证服务已启动（MT5 桥接服务启动需要时间）
        max_retries = 10
        for i in range(max_retries):
            time.sleep(0.5)
            if is_port_in_use(port):
                print(f"Bridge service started successfully on port {port}")
                break
        else:
            # 10次重试后仍未监听，但进程可能还在启动中
            print(f"Warning: Port {port} not listening after {max_retries * 0.5} seconds")
            pass

        return {
            "message": "Instance started successfully",
            "port": port,
            "bridge_pid": bridge_process.pid,
            "mt5_pid": mt5_process.pid if mt5_process else None,
            "note": "MT5 client was already running" if mt5_process else "MT5 client status unknown"
        }

    except HTTPException:
        # 重新抛出 HTTP 异常
        raise
    except Exception as e:
        error_msg = f"Failed to start instance: {str(e)}"
        print(error_msg)
        raise HTTPException(
            status_code=500,
            detail=error_msg
        )


@app.post("/instances/{port}/stop")
async def stop_instance(port: int):
    """停止实例（包括 MT5 桥接服务和 MT5 客户端）"""
    instances = load_instances()
    port_str = str(port)

    if port_str not in instances:
        raise HTTPException(status_code=404, detail=f"Instance on port {port} not found")

    config = instances[port_str]
    stopped_services = []

    # 1. 停止 MT5 桥接服务
    proc = get_process_by_port(port)
    if proc:
        try:
            print(f"Stopping bridge service on port {port}, PID: {proc.pid}")
            proc.terminate()
            try:
                proc.wait(timeout=5)
                print(f"Bridge service terminated gracefully")
                stopped_services.append("MT5 Bridge Service")
            except psutil.TimeoutExpired:
                print(f"Bridge service did not terminate, force killing...")
                proc.kill()
                try:
                    proc.wait(timeout=3)
                    print(f"Bridge service killed")
                    stopped_services.append("MT5 Bridge Service (forced)")
                except psutil.TimeoutExpired:
                    print(f"Warning: Failed to kill bridge service PID {proc.pid}")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            print(f"Process already gone or access denied: {e}")
            stopped_services.append("MT5 Bridge Service")

    # 2. 额外检查：确保端口已释放
    time.sleep(1)
    if is_port_in_use(port):
        print(f"Warning: Port {port} still in use after stopping bridge service")
        # 尝试再次查找并终止占用端口的进程
        proc = get_process_by_port(port)
        if proc:
            print(f"Force killing remaining process on port {port}, PID: {proc.pid}")
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception as e:
                print(f"Failed to kill process: {e}")

    # 3. 停止 MT5 客户端（使用精准路径匹配）
    mt5_path = config.get("mt5_path")
    if mt5_path and stop_mt5_client_by_path(mt5_path):
        stopped_services.append("MT5 Client")

    message = f"Stopped: {', '.join(stopped_services)}" if stopped_services else "Instance was not running"
    return {"message": message, "port": port, "stopped": stopped_services}


@app.post("/instances/{port}/restart")
async def restart_instance(port: int):
    """重启实例"""
    instances = load_instances()
    port_str = str(port)

    if port_str not in instances:
        raise HTTPException(status_code=404, detail=f"Instance on port {port} not found")

    try:
        # 1. 先停止实例
        print(f"Restarting instance on port {port}: Step 1 - Stopping...")
        stop_result = await stop_instance(port)
        print(f"Stop result: {stop_result}")

        # 2. 等待端口释放
        print(f"Restarting instance on port {port}: Step 2 - Waiting for port release...")
        max_wait = 20  # 增加等待时间到 10 秒
        for i in range(max_wait):
            if not is_port_in_use(port):
                print(f"Port {port} released after {i * 0.5} seconds")
                break
            time.sleep(0.5)
        else:
            # 端口仍然被占用
            print(f"Warning: Port {port} still in use after {max_wait * 0.5} seconds")
            # 尝试强制清理
            proc = get_process_by_port(port)
            if proc:
                print(f"Force killing process on port {port}: PID {proc.pid}")
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                    time.sleep(1)
                except Exception as e:
                    print(f"Failed to kill process: {e}")

        # 3. 再次确认端口已释放
        if is_port_in_use(port):
            raise HTTPException(
                status_code=500,
                detail=f"Port {port} is still in use after stopping. Cannot restart."
            )

        # 4. 启动实例
        print(f"Restarting instance on port {port}: Step 3 - Starting...")
        start_result = await start_instance(port)
        print(f"Start result: {start_result}")

        return {
            "message": "Instance restarted successfully",
            "port": port,
            "details": {
                "stopped": stop_result.get("stopped", []),
                "started": True
            }
        }

    except HTTPException:
        # 重新抛出 HTTP 异常
        raise
    except Exception as e:
        # 捕获其他异常并返回详细错误信息
        error_msg = f"Failed to restart instance on port {port}: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


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

    return {"message": "Instance deleted successfully", "port": port}


@app.get("/system/mt5-processes")
async def get_mt5_processes():
    """获取所有 MT5 terminal64.exe 进程的详细信息"""
    processes = []

    for proc in psutil.process_iter(['pid', 'name', 'create_time']):
        try:
            if proc.info['name'] and 'terminal64.exe' in proc.info['name'].lower():
                # 获取进程详细信息
                try:
                    proc_info = {
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'create_time': proc.info['create_time'],
                        'memory_mb': round(proc.memory_info().rss / 1024 / 1024, 2)
                    }

                    # 尝试获取可执行文件路径和工作目录
                    try:
                        proc_info['exe_path'] = proc.exe()
                        proc_info['cwd'] = proc.cwd()
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass

                    # 尝试获取命令行
                    try:
                        proc_info['cmdline'] = ' '.join(proc.cmdline())
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass

                    processes.append(proc_info)
                except Exception as e:
                    processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'error': str(e)
                    })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return {
        'count': len(processes),
        'processes': processes,
        'timestamp': time.time()
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)

