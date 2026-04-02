# -*- coding: utf-8 -*-
"""
Windows Agent V3 - MT5 实例管理与健康监控服务
功能：
1. 远程控制 MT5 实例（启动/停止/重启）
2. MT5 卡顿检测与告警
3. 健康状态监控
4. 与后端 API 集成
"""
import os
import sys
import json
import time
import logging
import psutil
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Body
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
import uvicorn
import httpx
import psycopg2
from psycopg2.extras import RealDictCursor

# ====================== 配置加载 ======================
CONFIG_FILE = Path("C:/MT5Agent/config.json")
INSTANCES_FILE = Path("C:/MT5Agent/instances.json")
LOG_FILE = Path("C:/MT5Agent/logs/agent.log")

# 确保目录存在
CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ====================== 配置管理 ======================
DEFAULT_CONFIG = {
    "agent": {
        "host": "0.0.0.0",
        "port": 8765,
        "api_key": "HustleXAU_MT5_Agent_Key_2026"
    },
    "backend": {
        "url": "https://admin.hustle2026.xyz",
        "username": "",
        "password": "",
        "enabled": False
    },
    "database": {
        "host": "172.31.2.22",
        "port": 5432,
        "database": "postgres",
        "user": "postgres",
        "password": "Lk106504"
    },
    "monitoring": {
        "enabled": True,
        "check_interval": 30,
        "freeze_threshold": 10,
        "cpu_threshold": 95,
        "memory_threshold": 90
    }
}

def load_config() -> Dict:
    """加载配置文件"""
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return DEFAULT_CONFIG

def save_config(config: Dict):
    """保存配置文件"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

config = load_config()
agent_config = config["agent"]
backend_config = config["backend"]
database_config = config.get("database", {})
monitoring_config = config["monitoring"]

# ====================== Pydantic 模型 ======================
class BridgeDeployRequest(BaseModel):
    service_name: str
    mt5_login: str
    mt5_password: str
    mt5_server: str
    mt5_path: str
    service_port: int
    api_key: str = "OQ6bUimHZDmXEZzJKE"

# ====================== 数据库连接 ======================
def get_db_connection():
    """获取数据库连接"""
    try:
        conn = psycopg2.connect(
            host=database_config.get("host", "172.31.2.22"),
            port=database_config.get("port", 5432),
            database=database_config.get("database", "postgres"),
            user=database_config.get("user", "postgres"),
            password=database_config.get("password", "Lk106504")
        )
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return None

def load_instances_from_db() -> Dict:
    """从数据库加载MT5客户端配置"""
    conn = get_db_connection()
    if not conn:
        logger.warning("Database connection failed, falling back to instances.json")
        return load_instances_from_file()

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT
                agent_instance_name,
                client_name,
                mt5_login,
                mt5_password,
                mt5_server,
                password_type
            FROM mt5_clients
            WHERE agent_instance_name IS NOT NULL
            AND is_active = true
        """)

        rows = cursor.fetchall()
        instances = {}

        for row in rows:
            instance_name = row['agent_instance_name']
            # 根据agent_instance_name确定MT5路径
            if instance_name == 'bybit_system_service':
                mt5_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
            elif instance_name == 'mt5-01':
                mt5_path = "D:\\MetaTrader 5-01\\terminal64.exe"
            else:
                # 默认路径
                mt5_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

            instances[instance_name] = {
                "name": row['client_name'],
                "path": mt5_path,
                "account": str(row['mt5_login']),
                "password": row['mt5_password'],
                "server": row['mt5_server'],
                "portable": True
            }

        cursor.close()
        conn.close()

        logger.info(f"Loaded {len(instances)} instances from database")
        return instances

    except Exception as e:
        logger.error(f"Failed to load instances from database: {e}")
        if conn:
            conn.close()
        return load_instances_from_file()

def load_instances_from_file() -> Dict:
    """从文件加载实例配置（备用方案）"""
    if not INSTANCES_FILE.exists():
        return {}
    try:
        with open(INSTANCES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

# ====================== 实例配置管理 ======================
def load_instances() -> Dict:
    """加载实例配置 - 优先从数据库加载"""
    return load_instances_from_db()

# ====================== MT5 控制器 ======================
class MT5Controller:
    """MT5 实例控制器"""

    @staticmethod
    def is_instance_running(mt5_path: str, account: str = None) -> bool:
        """
        检查指定路径的 MT5 实例是否正在运行

        注意：由于 MT5 进程启动后命令行参数可能不保留，
        我们主要依赖路径匹配。账户参数仅用于日志记录。
        """
        target_path = os.path.normpath(mt5_path).lower()
        logger.debug(f"Checking if instance is running: path={target_path}, account={account}")

        for proc in psutil.process_iter(['name', 'exe', 'cmdline']):
            try:
                if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
                    proc_path = os.path.normpath(proc.info['exe']).lower()

                    if proc_path == target_path:
                        logger.info(f"Instance running: path={target_path}, account={account}, cmdline={proc.info.get('cmdline', [])}")
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        logger.info(f"Instance NOT running: path={target_path}, account={account}")
        return False

    @staticmethod
    def get_instance_process(mt5_path: str, account: str = None) -> Optional[psutil.Process]:
        """
        获取指定路径的 MT5 进程对象

        注意：主要依赖路径匹配，账户参数仅用于日志记录
        """
        target_path = os.path.normpath(mt5_path).lower()
        for proc in psutil.process_iter(['name', 'exe', 'pid', 'cmdline']):
            try:
                if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
                    proc_path = os.path.normpath(proc.info['exe']).lower()
                    if proc_path == target_path:
                        logger.info(f"Found process: PID={proc.info['pid']}, path={target_path}, account={account}")
                        return psutil.Process(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return None

    @staticmethod
    def start_instance(instance_config: Dict, wait_seconds: int = 5) -> bool:
        """启动 MT5 实例"""
        mt5_path = instance_config["path"]
        account = instance_config.get("account")

        # 检查是否已运行（使用路径+账户匹配）
        if MT5Controller.is_instance_running(mt5_path, account):
            logger.info(f"Instance {instance_config['name']} (account: {account}) is already running")
            return True

        # 检查路径
        if not os.path.exists(mt5_path):
            logger.error(f"MT5 path not found: {mt5_path}")
            return False

        # 构造启动命令
        cmd = [mt5_path]
        if instance_config.get("portable", True):
            cmd.append("/portable")

        # 添加登录参数（如果配置了）
        if instance_config.get("account"):
            cmd.append(f"/login:{instance_config['account']}")
        if instance_config.get("password"):
            cmd.append(f"/password:{instance_config['password']}")
        if instance_config.get("server"):
            cmd.append(f"/server:{instance_config['server']}")
        if instance_config.get("is_investor", False):
            cmd.append("/investor")

        try:
            # 使用任务计划程序在用户会话中启动进程
            # 这样可以确保 MT5 窗口显示在用户桌面上
            task_name = f"MT5_Start_{instance_config['name']}_{int(time.time())}"
            cmd_str = ' '.join([f'"{c}"' if ' ' in c else c for c in cmd])

            # 创建临时任务
            create_task_cmd = [
                'schtasks', '/create',
                '/tn', task_name,
                '/tr', cmd_str,
                '/sc', 'once',
                '/st', '00:00',
                '/rl', 'HIGHEST',
                '/f'
            ]

            result = subprocess.run(create_task_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to create task: {result.stderr}")
                return False

            # 立即运行任务
            run_task_cmd = ['schtasks', '/run', '/tn', task_name]
            result = subprocess.run(run_task_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to run task: {result.stderr}")
                subprocess.run(['schtasks', '/delete', '/tn', task_name, '/f'], capture_output=True)
                return False

            logger.info(f"Started instance {instance_config['name']} via task scheduler, waiting {wait_seconds}s...")
            time.sleep(wait_seconds)

            # 删除临时任务
            subprocess.run(['schtasks', '/delete', '/tn', task_name, '/f'], capture_output=True)

            if MT5Controller.is_instance_running(mt5_path, account):
                logger.info(f"Instance {instance_config['name']} (account: {account}) started successfully")
                return True
            else:
                logger.error(f"Instance {instance_config['name']} (account: {account}) failed to start")
                return False
        except Exception as e:
            logger.error(f"Failed to start instance {instance_config['name']}: {e}")
            return False

    @staticmethod
    def stop_instance(instance_config: Dict, force: bool = True) -> bool:
        """
        停止 MT5 实例

        注意：主要依赖路径匹配，不再检查账户参数
        """
        mt5_path = instance_config["path"]
        account = instance_config.get("account")

        logger.info(f"Attempting to stop instance: {instance_config['name']}, path={mt5_path}, account={account}")

        if not MT5Controller.is_instance_running(mt5_path, account):
            logger.info(f"Instance {instance_config['name']} (account: {account}) is not running")
            return True

        target_path = os.path.normpath(mt5_path).lower()
        stopped = False

        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                try:
                    if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
                        proc_path = os.path.normpath(proc.info['exe']).lower()
                        if proc_path == target_path:
                            logger.info(f"Found matching process: PID={proc.info['pid']}, cmdline={proc.info.get('cmdline', [])}")

                            # 停止进程
                            logger.info(f"Stopping process: PID={proc.info['pid']}, force={force}")
                            if force:
                                proc.kill()
                            else:
                                proc.terminate()
                            logger.info(f"Stopped instance {instance_config['name']} (account: {account}, PID: {proc.info['pid']})")
                            stopped = True
                            time.sleep(2)

                            if not MT5Controller.is_instance_running(mt5_path, account):
                                logger.info(f"Verified: instance {instance_config['name']} is no longer running")
                                return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

            if not stopped:
                logger.error(f"No matching process found to stop for {instance_config['name']} (account: {account})")
            else:
                logger.error(f"Process was stopped but still appears to be running: {instance_config['name']}")
            return False
        except Exception as e:
            logger.error(f"Error stopping instance {instance_config['name']} (account: {account}): {e}")
            return False

    @staticmethod
    def restart_instance(instance_config: Dict, wait_seconds: int = 5) -> bool:
        """重启 MT5 实例"""
        logger.info(f"Restarting instance: {instance_config['name']}")
        if not MT5Controller.stop_instance(instance_config):
            return False
        return MT5Controller.start_instance(instance_config, wait_seconds)

# ====================== MT5 健康监控 ======================
class MT5HealthMonitor:
    """MT5 健康状态监控器"""

    def __init__(self):
        self.last_check_time = {}
        self.freeze_count = {}
        self.last_cpu_percent = {}
        self.last_memory_percent = {}

    def check_instance_health(self, instance_name: str, instance_config: Dict) -> Dict:
        """检查实例健康状态"""
        mt5_path = instance_config["path"]
        account = instance_config.get("account")
        proc = MT5Controller.get_instance_process(mt5_path, account)

        health_status = {
            "instance_name": instance_name,
            "is_running": proc is not None,
            "is_frozen": False,
            "cpu_high": False,
            "memory_high": False,
            "details": {}
        }

        if not proc:
            return health_status

        try:
            # CPU 使用率
            cpu_percent = proc.cpu_percent(interval=1)
            health_status["details"]["cpu_percent"] = cpu_percent
            if cpu_percent > monitoring_config["cpu_threshold"]:
                health_status["cpu_high"] = True

            # 内存使用率
            memory_info = proc.memory_info()
            memory_percent = proc.memory_percent()
            health_status["details"]["memory_mb"] = memory_info.rss / 1024 / 1024
            health_status["details"]["memory_percent"] = memory_percent
            if memory_percent > monitoring_config["memory_threshold"]:
                health_status["memory_high"] = True

            # 卡顿检测（通过 CPU 使用率变化判断）
            if instance_name in self.last_cpu_percent:
                cpu_change = abs(cpu_percent - self.last_cpu_percent[instance_name])
                if cpu_change < 0.1 and cpu_percent > 80:
                    # CPU 高但没有变化，可能卡顿
                    self.freeze_count[instance_name] = self.freeze_count.get(instance_name, 0) + 1
                    if self.freeze_count[instance_name] >= monitoring_config["freeze_threshold"]:
                        health_status["is_frozen"] = True
                else:
                    self.freeze_count[instance_name] = 0

            self.last_cpu_percent[instance_name] = cpu_percent
            self.last_memory_percent[instance_name] = memory_percent
            self.last_check_time[instance_name] = datetime.now()

            # 进程信息
            health_status["details"]["pid"] = proc.pid
            health_status["details"]["status"] = proc.status()
            health_status["details"]["num_threads"] = proc.num_threads()

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.error(f"Error checking health for {instance_name}: {e}")

        return health_status

# ====================== 后端 API 集成 ======================
class BackendAPIClient:
    """后端 API 客户端"""

    def __init__(self):
        self.access_token = None
        self.token_expiry = None

    async def get_token(self) -> Optional[str]:
        """获取访问令牌"""
        if not backend_config["enabled"]:
            return None

        if self.access_token and self.token_expiry and datetime.now() < self.token_expiry:
            return self.access_token

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{backend_config['url']}/api/v1/auth/login",
                    json={
                        "username": backend_config["username"],
                        "password": backend_config["password"]
                    },
                    timeout=10.0
                )
                if response.status_code == 200:
                    data = response.json()
                    self.access_token = data["access_token"]
                    self.token_expiry = datetime.now() + timedelta(hours=23)
                    logger.info("Backend API token obtained")
                    return self.access_token
        except Exception as e:
            logger.error(f"Failed to get backend token: {e}")
        return None

    async def send_alert(self, title: str, message: str, severity: str = "Warning"):
        """发送告警到后端"""
        if not backend_config["enabled"]:
            return

        token = await self.get_token()
        if not token:
            return

        try:
            async with httpx.AsyncClient() as client:
                # 获取管理员用户列表
                users_response = await client.get(
                    f"{backend_config['url']}/api/v1/users",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10.0
                )
                if users_response.status_code != 200:
                    return

                users_data = users_response.json()
                admin_user_ids = [
                    user["user_id"] for user in users_data.get("users", [])
                    if user.get("role") in ["admin", "super_admin"]
                ]

                if not admin_user_ids:
                    return

                # 发送通知
                template_key = {
                    "Error": "mt5_client_error",
                    "Warning": "mt5_client_warning",
                    "Info": "mt5_client_info"
                }.get(severity, "mt5_client_warning")

                notify_response = await client.post(
                    f"{backend_config['url']}/api/v1/notifications/send",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "template_key": template_key,
                        "user_ids": admin_user_ids,
                        "variables": {
                            "title": title,
                            "content": message,
                            "hostname": os.environ.get("COMPUTERNAME", "Unknown"),
                            "severity": severity
                        }
                    },
                    timeout=10.0
                )
                if notify_response.status_code == 200:
                    logger.info(f"Alert sent to backend: {title}")
        except Exception as e:
            logger.error(f"Failed to send alert to backend: {e}")

# ====================== 全局实例 ======================
controller = MT5Controller()
health_monitor = MT5HealthMonitor()
backend_client = BackendAPIClient()

# ====================== FastAPI 应用 ======================
app = FastAPI(title="MT5 Windows Agent V3", version="3.0.0")

# API 认证
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: Optional[str] = Depends(API_KEY_HEADER)):
    if api_key != agent_config["api_key"]:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True

# ====================== 数据模型 ======================
class InstanceConfig(BaseModel):
    name: str
    path: str
    account: Optional[str] = None
    password: Optional[str] = None
    server: Optional[str] = None
    is_investor: bool = False
    portable: bool = True
    create_no_window: bool = False

class OperationResponse(BaseModel):
    instance_name: str
    operation: str
    success: bool
    message: str

class InstanceStatus(BaseModel):
    instance_name: str
    display_name: str
    is_running: bool
    health_status: Optional[Dict] = None

# ====================== API 端点 ======================
@app.get("/debug/processes", dependencies=[Depends(verify_api_key)])
def debug_processes():
    """调试端点：列出所有MT5进程"""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
        try:
            if proc.info['name'] == 'terminal64.exe':
                processes.append({
                    "pid": proc.info['pid'],
                    "exe": proc.info.get('exe'),
                    "cmdline": proc.info.get('cmdline', [])
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return {"processes": processes, "count": len(processes)}


@app.get("/health")
def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "agent": "MT5 Windows Agent V3",
        "version": "3.0.0",
        "session": os.environ.get("SESSIONNAME", "Unknown")
    }

@app.get("/instances", response_model=List[InstanceStatus], dependencies=[Depends(verify_api_key)])
def get_all_instances():
    """获取所有实例状态"""
    instances = load_instances()
    status_list = []
    for name, cfg in instances.items():
        is_running = controller.is_instance_running(cfg["path"])
        health_status = None
        if is_running and monitoring_config["enabled"]:
            health_status = health_monitor.check_instance_health(name, cfg)
        status_list.append(InstanceStatus(
            instance_name=name,
            display_name=cfg["name"],
            is_running=is_running,
            health_status=health_status
        ))
    return status_list

@app.get("/instances/{instance_name}", response_model=InstanceStatus, dependencies=[Depends(verify_api_key)])
def get_instance_status(instance_name: str):
    """获取单个实例状态"""
    instances = load_instances()
    if instance_name not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")

    cfg = instances[instance_name]
    is_running = controller.is_instance_running(cfg["path"])
    health_status = None
    if is_running and monitoring_config["enabled"]:
        health_status = health_monitor.check_instance_health(instance_name, cfg)

    return InstanceStatus(
        instance_name=instance_name,
        display_name=cfg["name"],
        is_running=is_running,
        health_status=health_status
    )

@app.post("/instances", dependencies=[Depends(verify_api_key)])
def create_instance(instance: InstanceConfig):
    """创建/更新实例配置 - 已禁用，请在数据库中管理MT5客户端"""
    raise HTTPException(
        status_code=501,
        detail="Instance management via API is disabled. Please manage MT5 clients in the database."
    )

@app.delete("/instances/{instance_name}", dependencies=[Depends(verify_api_key)])
def delete_instance(instance_name: str):
    """删除实例配置 - 已禁用，请在数据库中管理MT5客户端"""
    raise HTTPException(
        status_code=501,
        detail="Instance management via API is disabled. Please manage MT5 clients in the database."
    )

@app.post("/instances/{instance_name}/start", response_model=OperationResponse, dependencies=[Depends(verify_api_key)])
def start_instance(instance_name: str, wait_seconds: int = 5):
    """启动实例"""
    instances = load_instances()
    if instance_name not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")

    cfg = instances[instance_name]
    success = controller.start_instance(cfg, wait_seconds)
    return OperationResponse(
        instance_name=instance_name,
        operation="start",
        success=success,
        message=f"Instance {cfg['name']} {'started successfully' if success else 'failed to start'}"
    )

@app.post("/instances/{instance_name}/stop", response_model=OperationResponse, dependencies=[Depends(verify_api_key)])
def stop_instance(instance_name: str, force: bool = True):
    """停止实例"""
    instances = load_instances()
    if instance_name not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")

    cfg = instances[instance_name]
    success = controller.stop_instance(cfg, force)
    return OperationResponse(
        instance_name=instance_name,
        operation="stop",
        success=success,
        message=f"Instance {cfg['name']} {'stopped successfully' if success else 'failed to stop'}"
    )

@app.post("/instances/{instance_name}/restart", response_model=OperationResponse, dependencies=[Depends(verify_api_key)])
def restart_instance(instance_name: str, wait_seconds: int = 5):
    """重启实例"""
    instances = load_instances()
    if instance_name not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")

    cfg = instances[instance_name]
    success = controller.restart_instance(cfg, wait_seconds)
    return OperationResponse(
        instance_name=instance_name,
        operation="restart",
        success=success,
        message=f"Instance {cfg['name']} {'restarted successfully' if success else 'failed to restart'}"
    )

@app.get("/logs", dependencies=[Depends(verify_api_key)])
def get_logs(lines: int = 100):
    """获取日志文件最后N行"""
    try:
        if not LOG_FILE.exists():
            return {"logs": [], "message": "Log file not found"}

        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return {
                "logs": [line.strip() for line in last_lines],
                "total_lines": len(all_lines),
                "returned_lines": len(last_lines)
            }
    except Exception as e:
        logger.error(f"Failed to read logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {str(e)}")

# ====================== Bridge 实例控制 ======================
@app.get("/bridge/{service_name}/status", dependencies=[Depends(verify_api_key)])
def get_bridge_status(service_name: str):
    """获取 Bridge 服务状态"""
    try:
        result = subprocess.run(
            ['nssm', 'status', service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        status = result.stdout.strip()
        is_running = status == "SERVICE_RUNNING"

        return {
            "service_name": service_name,
            "status": status,
            "is_running": is_running
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Command timeout")
    except Exception as e:
        logger.error(f"Failed to get bridge status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bridge/{service_name}/start", dependencies=[Depends(verify_api_key)])
def start_bridge(service_name: str):
    """启动 Bridge 服务"""
    try:
        result = subprocess.run(
            ['nssm', 'start', service_name],
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=10
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        message = stdout or stderr or "Operation completed"

        # Check if already running or if there's a startup issue
        # returncode 1 with "START:" = already running (success)
        # returncode 1 with "Unexpected status" = startup failed (failure)
        already_running = result.returncode == 1 and "START:" in message and "Unexpected" not in message
        startup_failed = "Unexpected status" in message or "SERVICE_STOPPED" in message

        success = result.returncode == 0 or already_running

        logger.info(f"Bridge {service_name} start: returncode={result.returncode}, success={success}, startup_failed={startup_failed}")

        if startup_failed:
            return {
                "service_name": service_name,
                "operation": "start",
                "success": False,
                "message": f"Service failed to start: {message}"
            }

        return {
            "service_name": service_name,
            "operation": "start",
            "success": success,
            "message": "Service is already running" if already_running else ("Service started successfully" if success else message)
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Command timeout")
    except Exception as e:
        logger.error(f"Failed to start bridge: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bridge/{service_name}/stop", dependencies=[Depends(verify_api_key)])
def stop_bridge(service_name: str):
    """停止 Bridge 服务"""
    try:
        result = subprocess.run(
            ['nssm', 'stop', service_name],
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=10
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        message = stdout or stderr or "Operation completed"

        # Check if already stopped
        already_stopped = result.returncode != 0 and "STOP:" in message

        success = result.returncode == 0 or already_stopped

        logger.info(f"Bridge {service_name} stop: returncode={result.returncode}, success={success}")
        return {
            "service_name": service_name,
            "operation": "stop",
            "success": success,
            "message": "Service is already stopped" if already_stopped else message
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Command timeout")
    except Exception as e:
        logger.error(f"Failed to stop bridge: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bridge/{service_name}/restart", dependencies=[Depends(verify_api_key)])
def restart_bridge(service_name: str):
    """重启 Bridge 服务"""
    try:
        result = subprocess.run(
            ['nssm', 'restart', service_name],
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=15
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        message = stdout or stderr or "Operation completed"

        success = result.returncode == 0

        logger.info(f"Bridge {service_name} restart: returncode={result.returncode}, success={success}")
        return {
            "service_name": service_name,
            "operation": "restart",
            "success": success,
            "message": message
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Command timeout")
    except Exception as e:
        logger.error(f"Failed to restart bridge: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/bridge/deploy", dependencies=[Depends(verify_api_key)])
def deploy_bridge(request: BridgeDeployRequest):
    """
    部署新的 Bridge 实例和 MT5 客户端

    Args:
        request: 部署请求参数

    Returns:
        部署结果
    """
    import shutil
    import configparser

    try:
        # ==================== 1. 部署 MT5 客户端 ====================
        # 生成新的 MT5 客户端目录名
        mt5_client_dir = Path(f"D:/MetaTrader 5-{request.service_port}")

        if mt5_client_dir.exists():
            raise HTTPException(status_code=400, detail=f"MT5客户端目录已存在: {mt5_client_dir}")

        # 复制整个 MT5 客户端目录
        source_mt5_dir = Path("D:/MetaTrader 5-01")  # 源模板目录
        if not source_mt5_dir.exists():
            raise HTTPException(status_code=404, detail=f"MT5源目录不存在: {source_mt5_dir}")

        logger.info(f"Copying MT5 client from {source_mt5_dir} to {mt5_client_dir}")
        shutil.copytree(source_mt5_dir, mt5_client_dir)
        logger.info(f"MT5 client copied successfully")

        # 修改 MT5 配置文件 - common.ini
        common_ini_path = mt5_client_dir / "Config" / "common.ini"
        if common_ini_path.exists():
            # 读取配置
            config = configparser.ConfigParser()
            config.read(common_ini_path, encoding='utf-8')

            # 修改登录信息
            if 'Common' not in config:
                config['Common'] = {}

            config['Common']['Login'] = str(request.mt5_login)
            config['Common']['Server'] = request.mt5_server
            # 注意：密码通常不直接存储在配置文件中，MT5 会在首次登录时加密存储

            # 保存配置
            with open(common_ini_path, 'w', encoding='utf-8') as f:
                config.write(f)

            logger.info(f"Updated MT5 configuration: Login={request.mt5_login}, Server={request.mt5_server}")

        # 清理旧的账户数据（让 MT5 重新登录）
        accounts_dat = mt5_client_dir / "Config" / "accounts.dat"
        if accounts_dat.exists():
            accounts_dat.unlink()
            logger.info("Cleared old accounts.dat")

        # 清理旧的服务器数据
        servers_dat = mt5_client_dir / "Config" / "servers.dat"
        if servers_dat.exists():
            servers_dat.unlink()
            logger.info("Cleared old servers.dat")

        # 新的 MT5 客户端路径
        new_mt5_path = str(mt5_client_dir / "terminal64.exe")

        # ==================== 2. 部署 Bridge 服务 ====================
        deploy_dir = Path(f"D:/{request.service_name}")
        if deploy_dir.exists():
            raise HTTPException(status_code=400, detail=f"Bridge部署目录已存在: {deploy_dir}")

        deploy_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created Bridge deployment directory: {deploy_dir}")

        # 创建子目录
        (deploy_dir / "app").mkdir(exist_ok=True)
        (deploy_dir / "logs").mkdir(exist_ok=True)
        (deploy_dir / "venv").mkdir(exist_ok=True)

        # 创建 .env 配置文件（使用新的 MT5 路径）
        env_content = f"""# Bridge 实例配置
API_KEY={request.api_key}
MT5_LOGIN={request.mt5_login}
MT5_PASSWORD={request.mt5_password}
MT5_SERVER={request.mt5_server}
MT5_PATH={new_mt5_path}
SERVICE_PORT={request.service_port}
INSTANCE_NAME={request.service_name}
"""
        with open(deploy_dir / ".env", "w", encoding="utf-8") as f:
            f.write(env_content)
        logger.info(f"Created .env file with MT5 path: {new_mt5_path}")

        # 复制 Bridge 应用代码（从模板目录）
        template_dir = Path("D:/hustle-mt5-template")
        if template_dir.exists():
            shutil.copytree(template_dir / "app", deploy_dir / "app", dirs_exist_ok=True)
            shutil.copytree(template_dir / "venv", deploy_dir / "venv", dirs_exist_ok=True)
            if (template_dir / "requirements.txt").exists():
                shutil.copy(template_dir / "requirements.txt", deploy_dir / "requirements.txt")
            logger.info(f"Copied Bridge application from template")
        else:
            logger.warning(f"Template directory not found: {template_dir}")

        # ==================== 3. 配置 Windows 服务 ====================
        uvicorn_path = str(deploy_dir / "venv" / "Scripts" / "uvicorn.exe")
        app_dir = str(deploy_dir / "app")

        nssm_commands = [
            ['nssm', 'install', request.service_name, uvicorn_path],
            ['nssm', 'set', request.service_name, 'AppParameters', f'main:app --host 0.0.0.0 --port {request.service_port}'],
            ['nssm', 'set', request.service_name, 'AppDirectory', app_dir],
            ['nssm', 'set', request.service_name, 'AppExit', 'Default', 'Restart'],
            ['nssm', 'set', request.service_name, 'AppEnvironmentExtra', ':PYTHONUNBUFFERED=1'],
            ['nssm', 'set', request.service_name, 'AppStdout', str(deploy_dir / 'logs' / 'stdout.log')],
            ['nssm', 'set', request.service_name, 'AppStderr', str(deploy_dir / 'logs' / 'stderr.log')],
            ['nssm', 'set', request.service_name, 'AppRotateFiles', '1'],
            ['nssm', 'set', request.service_name, 'AppRotateOnline', '1'],
            ['nssm', 'set', request.service_name, 'AppRotateSeconds', '86400'],
            ['nssm', 'set', request.service_name, 'AppRotateBytes', '10485760'],
            ['nssm', 'set', request.service_name, 'DisplayName', request.service_name],
            ['nssm', 'set', request.service_name, 'Start', 'SERVICE_AUTO_START'],
        ]

        for cmd in nssm_commands:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                logger.error(f"NSSM command failed: {' '.join(cmd)}, error: {result.stderr}")
                raise HTTPException(status_code=500, detail=f"服务配置失败: {result.stderr}")

        logger.info(f"Bridge service {request.service_name} configured successfully")

        # 启动服务
        result = subprocess.run(['nssm', 'start', request.service_name], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.warning(f"Failed to start service: {result.stderr}")

        # ==================== 4. 创建桌面快捷方式 ====================
        try:
            import win32com.client

            desktop_path = Path("C:/Users/Administrator/Desktop")
            if not desktop_path.exists():
                logger.warning(f"Desktop path not found: {desktop_path}")
            else:
                # 快捷方式名称：MT5 登录账号+服务端口
                shortcut_name = f"MT5 {request.mt5_login}+{request.service_port}.lnk"
                shortcut_path = desktop_path / shortcut_name

                # 创建快捷方式
                shell = win32com.client.Dispatch("WScript.Shell")
                shortcut = shell.CreateShortCut(str(shortcut_path))
                shortcut.TargetPath = new_mt5_path
                shortcut.Arguments = "/portable"
                shortcut.WorkingDirectory = str(mt5_client_dir)
                shortcut.IconLocation = new_mt5_path
                shortcut.Description = f"MT5 Client - {request.mt5_login} on port {request.service_port}"
                shortcut.save()

                logger.info(f"Created desktop shortcut: {shortcut_path}")
        except Exception as e:
            logger.warning(f"Failed to create desktop shortcut: {e}")

        return {
            "success": True,
            "service_name": request.service_name,
            "deploy_dir": str(deploy_dir),
            "mt5_client_dir": str(mt5_client_dir),
            "mt5_path": new_mt5_path,
            "service_port": request.service_port,
            "message": "MT5客户端和Bridge实例部署成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to deploy: {e}")
        # 清理失败的部署
        try:
            if 'deploy_dir' in locals() and deploy_dir.exists():
                shutil.rmtree(deploy_dir)
            if 'mt5_client_dir' in locals() and mt5_client_dir.exists():
                shutil.rmtree(mt5_client_dir)
        except:
            pass
        raise HTTPException(status_code=500, detail=f"部署失败: {str(e)}")


@app.delete("/bridge/{service_name}", dependencies=[Depends(verify_api_key)])
def delete_bridge(service_name: str, mt5_client_port: int = None, mt5_login: str = None):
    """
    删除 Bridge 实例和 MT5 客户端

    Args:
        service_name: 服务名称
        mt5_client_port: MT5客户端端口号（用于定位客户端目录）
        mt5_login: MT5登录账号（用于删除桌面快捷方式）

    Returns:
        删除结果
    """
    import shutil

    try:
        deploy_dir = Path(f"D:/{service_name}")

        # 1. 停止服务
        try:
            subprocess.run(['nssm', 'stop', service_name], capture_output=True, text=True, timeout=10)
            logger.info(f"Stopped service: {service_name}")
        except Exception as e:
            logger.warning(f"Failed to stop service: {e}")

        # 2. 删除服务
        try:
            result = subprocess.run(['nssm', 'remove', service_name, 'confirm'],
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                logger.info(f"Removed service: {service_name}")
            else:
                logger.warning(f"Failed to remove service: {result.stderr}")
        except Exception as e:
            logger.warning(f"Failed to remove service: {e}")

        # 3. 删除 Bridge 部署目录
        if deploy_dir.exists():
            shutil.rmtree(deploy_dir)
            logger.info(f"Removed Bridge deployment directory: {deploy_dir}")

        # 4. 删除 MT5 客户端目录（如果提供了端口号）
        if mt5_client_port:
            mt5_client_dir = Path(f"D:/MetaTrader 5-{mt5_client_port}")
            if mt5_client_dir.exists():
                # 先确保 MT5 进程已停止
                mt5_exe = mt5_client_dir / "terminal64.exe"
                if mt5_exe.exists():
                    for proc in psutil.process_iter(['name', 'exe']):
                        try:
                            if proc.info['exe'] and Path(proc.info['exe']).resolve() == mt5_exe.resolve():
                                proc.kill()
                                logger.info(f"Killed MT5 process: PID={proc.pid}")
                                time.sleep(2)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

                # 删除 MT5 客户端目录
                shutil.rmtree(mt5_client_dir)
                logger.info(f"Removed MT5 client directory: {mt5_client_dir}")

        # 5. 删除桌面快捷方式（如果提供了登录账号和端口号）
        if mt5_login and mt5_client_port:
            try:
                desktop_path = Path("C:/Users/Administrator/Desktop")
                shortcut_name = f"MT5 {mt5_login}+{mt5_client_port}.lnk"
                shortcut_path = desktop_path / shortcut_name

                if shortcut_path.exists():
                    shortcut_path.unlink()
                    logger.info(f"Removed desktop shortcut: {shortcut_path}")
            except Exception as e:
                logger.warning(f"Failed to remove desktop shortcut: {e}")

        return {
            "success": True,
            "service_name": service_name,
            "message": "Bridge实例和MT5客户端删除成功"
        }

    except Exception as e:
        logger.error(f"Failed to delete: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# ====================== 后台监控任务 ======================
async def monitoring_task():
    """后台健康监控任务"""
    logger.info("Health monitoring task started")
    while True:
        try:
            if not monitoring_config["enabled"]:
                await asyncio.sleep(60)
                continue

            instances = load_instances()
            for name, cfg in instances.items():
                if not controller.is_instance_running(cfg["path"]):
                    continue

                health_status = health_monitor.check_instance_health(name, cfg)

                # 检测卡顿
                if health_status["is_frozen"]:
                    logger.warning(f"Instance {name} is frozen!")
                    await backend_client.send_alert(
                        title=f"MT5 Instance Frozen: {cfg['name']}",
                        message=f"Instance {cfg['name']} appears to be frozen.\n"
                                f"CPU: {health_status['details'].get('cpu_percent', 0):.1f}%\n"
                                f"Memory: {health_status['details'].get('memory_percent', 0):.1f}%",
                        severity="Error"
                    )

                # 检测高 CPU
                if health_status["cpu_high"]:
                    logger.warning(f"Instance {name} has high CPU usage!")
                    await backend_client.send_alert(
                        title=f"MT5 High CPU: {cfg['name']}",
                        message=f"Instance {cfg['name']} CPU usage is {health_status['details']['cpu_percent']:.1f}%",
                        severity="Warning"
                    )

                # 检测高内存
                if health_status["memory_high"]:
                    logger.warning(f"Instance {name} has high memory usage!")
                    await backend_client.send_alert(
                        title=f"MT5 High Memory: {cfg['name']}",
                        message=f"Instance {cfg['name']} memory usage is {health_status['details']['memory_percent']:.1f}%",
                        severity="Warning"
                    )

            await asyncio.sleep(monitoring_config["check_interval"])
        except Exception as e:
            logger.error(f"Error in monitoring task: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    """启动时执行"""
    logger.info("=" * 60)
    logger.info("MT5 Windows Agent V3 Starting...")
    logger.info(f"Listen: http://{agent_config['host']}:{agent_config['port']}")
    logger.info(f"API Docs: http://{agent_config['host']}:{agent_config['port']}/docs")
    logger.info(f"Monitoring: {'Enabled' if monitoring_config['enabled'] else 'Disabled'}")
    logger.info(f"Backend Integration: {'Enabled' if backend_config['enabled'] else 'Disabled'}")
    logger.info("=" * 60)

    # 启动后台监控任务
    asyncio.create_task(monitoring_task())

# ====================== 主程序入口 ======================
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=agent_config["host"],
        port=agent_config["port"],
        log_level="info"
    )
