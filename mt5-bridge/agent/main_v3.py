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
    symbols: list = []  # 产品列表，用于配置 Market Watch 和图表
    mt5_template_path: str = ""  # 平台 MT5 模板目录路径（含 terminal64.exe），空则从 mt5_path 推断

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
                password_type,
                mt5_path,
                bridge_service_port
            FROM mt5_clients
            WHERE agent_instance_name IS NOT NULL
            AND is_active = true
        """)

        rows = cursor.fetchall()
        instances = {}

        for row in rows:
            instance_name = row['agent_instance_name']
            # 优先使用 DB 中的 mt5_path
            mt5_path = row.get('mt5_path')
            if not mt5_path:
                # 兜底：根据 instance_name 猜测路径
                if instance_name == 'bybit_system_service':
                    mt5_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
                elif instance_name == 'mt5-01':
                    mt5_path = "D:\\MetaTrader 5-01\\terminal64.exe"
                elif row.get('bridge_service_port'):
                    # 新部署的实例路径格式
                    mt5_path = f"D:\\MetaTrader 5-{row['bridge_service_port']}\\terminal64.exe"
                else:
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
    """获取 Bridge 服务状态（基于端口监听检测，不依赖 NSSM）"""
    try:
        import socket as _socket
        deploy_dir = Path(f"D:/{service_name}")
        env_file = deploy_dir / ".env"

        # 从 .env 读取端口
        port = None
        if env_file.exists():
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("SERVICE_PORT="):
                        try:
                            port = int(line.strip().split("=", 1)[1])
                        except Exception:
                            pass

        # 检查端口是否监听
        is_running = False
        if port:
            try:
                with _socket.create_connection(("127.0.0.1", port), timeout=1):
                    is_running = True
            except Exception:
                is_running = False

        status = "SERVICE_RUNNING" if is_running else "SERVICE_STOPPED"
        return {
            "service_name": service_name,
            "status": status,
            "is_running": is_running,
            "port": port,
        }
    except Exception as e:
        logger.error(f"Failed to get bridge status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/bridge/{service_name}/start", dependencies=[Depends(verify_api_key)])
def start_bridge(service_name: str):
    """启动 Bridge 服务（直接启动进程，支持 Session 2 桌面模式）"""
    import socket as _socket, time as _time

    deploy_dir = Path(f"D:/{service_name}")
    env_file = deploy_dir / ".env"
    python_exe = deploy_dir / "venv" / "Scripts" / "python.exe"
    app_dir = deploy_dir / "app"

    if not deploy_dir.exists():
        raise HTTPException(status_code=404, detail=f"Bridge 目录不存在: {deploy_dir}")
    if not python_exe.exists():
        raise HTTPException(status_code=404, detail=f"Python 环境不存在: {python_exe}")

    # 读取 .env
    env = dict(os.environ)
    port = None
    try:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
                    if k.strip() == "SERVICE_PORT":
                        try:
                            port = int(v.strip())
                        except Exception:
                            pass
    except Exception as e:
        raise HTTPException(status_code=500, detail=f".env 读取失败: {e}")

    if not port:
        raise HTTPException(status_code=500, detail="无法从 .env 获取 SERVICE_PORT")

    # 检查是否已运行
    try:
        with _socket.create_connection(("127.0.0.1", port), timeout=1):
            return {"service_name": service_name, "operation": "start",
                    "success": True, "message": f"Bridge 已在端口 {port} 运行"}
    except Exception:
        pass

    env["PYTHONUNBUFFERED"] = "1"

    try:
        log_out = open(deploy_dir / "logs" / "stdout.log", "w")
        log_err = open(deploy_dir / "logs" / "stderr.log", "w")
        proc = subprocess.Popen(
            [str(python_exe), "-m", "uvicorn", "main:app",
             "--host", "0.0.0.0", "--port", str(port)],
            cwd=str(app_dir),
            env=env,
            stdout=log_out,
            stderr=log_err,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        log_out.close()
        log_err.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动失败: {e}")

    # 等待端口就绪（最多 15s）
    for _ in range(15):
        _time.sleep(1)
        if proc.poll() is not None:
            raise HTTPException(status_code=500,
                                detail=f"Bridge 进程意外退出，rc={proc.returncode}")
        try:
            with _socket.create_connection(("127.0.0.1", port), timeout=1):
                logger.info(f"Bridge {service_name} started, PID={proc.pid}, port={port}")
                return {"service_name": service_name, "operation": "start",
                        "success": True, "message": f"Bridge 启动成功 (PID={proc.pid}, port={port})"}
        except Exception:
            pass

    raise HTTPException(status_code=500, detail=f"Bridge 启动超时，端口 {port} 未就绪")


@app.post("/bridge/{service_name}/stop", dependencies=[Depends(verify_api_key)])
def stop_bridge(service_name: str):
    """停止 Bridge 服务（按端口查找进程并终止）"""
    import socket as _socket

    deploy_dir = Path(f"D:/{service_name}")
    env_file = deploy_dir / ".env"

    # 读取端口
    port = None
    try:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("SERVICE_PORT="):
                    try:
                        port = int(line.strip().split("=", 1)[1])
                    except Exception:
                        pass
    except Exception as e:
        raise HTTPException(status_code=500, detail=f".env 读取失败: {e}")

    if not port:
        raise HTTPException(status_code=500, detail="无法从 .env 获取 SERVICE_PORT")

    # 检查是否在运行
    try:
        with _socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    except Exception:
        return {"service_name": service_name, "operation": "stop",
                "success": True, "message": "Bridge 已停止"}

    # 用 psutil 找到监听该端口的进程并终止
    killed = []
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr.port == port and conn.status == "LISTEN":
                try:
                    proc = psutil.Process(conn.pid)
                    # 终止整个进程树
                    for child in proc.children(recursive=True):
                        child.kill()
                    proc.kill()
                    killed.append(conn.pid)
                    logger.info(f"Killed bridge process PID={conn.pid} on port {port}")
                except Exception as e:
                    logger.warning(f"Failed to kill PID={conn.pid}: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"进程查找失败: {e}")

    if not killed:
        # 兜底：按 deploy_path 查找 uvicorn 进程
        deploy_str = str(deploy_dir).lower()
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if service_name.lower() in cmdline and "uvicorn" in cmdline:
                    proc.kill()
                    killed.append(proc.pid)
            except Exception:
                pass

    return {"service_name": service_name, "operation": "stop",
            "success": True, "message": f"已终止进程: {killed}" if killed else "进程已停止"}


@app.post("/bridge/{service_name}/restart", dependencies=[Depends(verify_api_key)])
def restart_bridge(service_name: str):
    """重启 Bridge 服务"""
    # 先停止
    try:
        stop_bridge(service_name)
    except Exception:
        pass

    import time as _time
    _time.sleep(2)

    # 再启动
    return start_bridge(service_name)


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
        # 优先用 mt5_template_path（平台配置），其次兜底 D:/MetaTrader 5-template
        if request.mt5_template_path:
            source_mt5_dir = Path(request.mt5_template_path).parent
        else:
            source_mt5_dir = Path("D:/MetaTrader 5-template")  # 兜底默认
        if not source_mt5_dir.exists():
            raise HTTPException(status_code=404, detail=f"MT5模板源目录不存在: {source_mt5_dir}")

        logger.info(f"Copying MT5 client from {source_mt5_dir} to {mt5_client_dir}")
        
        # 使用 robocopy 复制，可以跳过被锁定的文件
        robocopy_cmd = [
            'robocopy',
            str(source_mt5_dir),
            str(mt5_client_dir),
            '/E',      # 复制所有子目录（包括空目录）
            '/R:0',    # 失败时不重试
            '/W:0',    # 重试间隔0秒
            '/COPY:DAT',  # 只复制数据、属性、时间戳
            '/DCOPY:T',   # 只复制目录时间戳
            '/NFL',    # 不记录文件列表
            '/NDL',    # 不记录目录列表
            '/NJH',    # 不显示作业头
            '/NJS',    # 不显示作业摘要
            '/NP',     # 不显示进度百分比
        ]
        
        result = subprocess.run(robocopy_cmd, capture_output=True, text=True, timeout=300)
        
        # robocopy 返回码：0-15 表示成功（可能有部分文件被跳过），16+ 表示致命错误
        if result.returncode >= 16:
            logger.error(f"Robocopy failed with code {result.returncode}: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"MT5目录复制失败: {result.stderr}")
        
        logger.info(f"MT5 client copied successfully (robocopy exit code: {result.returncode})")

        # 修改 MT5 配置文件 - common.ini（UTF-16-LE with BOM，保持 MT5 原生格式）
        common_ini_path = mt5_client_dir / "Config" / "common.ini"
        try:
            # 确保 Config 目录存在
            (mt5_client_dir / "Config").mkdir(parents=True, exist_ok=True)

            if common_ini_path.exists():
                # 读取已有文件（UTF-16-LE with BOM）
                with open(common_ini_path, 'rb') as f:
                    raw = f.read()
                text = raw.decode('utf-16-le')
                if text.startswith('\ufeff'):
                    text = text[1:]
                lines = text.splitlines()
                new_lines = []
                for line in lines:
                    if line.strip().startswith('Login='):
                        new_lines.append(f'Login={request.mt5_login}')
                    elif line.strip().startswith('Server='):
                        new_lines.append(f'Server={request.mt5_server}')
                    else:
                        new_lines.append(line)
                output = '\r\n'.join(new_lines) + '\r\n'
            else:
                # 无 common.ini（IC Markets 等新模板），从头创建
                output = f'[Common]\r\nLogin={request.mt5_login}\r\nServer={request.mt5_server}\r\nProxyEnable=0\r\nProxyType=0\r\nProxyAddress=\r\nCertInstall=0\r\nNewsEnable=1\r\n[Charts]\r\nProfileLast=Default\r\nMaxBars=100000\r\nPrintColor=0\r\nSaveDeleted=0\r\nTradeHistory=1\r\nTradeLevels=1\r\n[Experts]\r\nAllowDllImport=0\r\nEnabled=1\r\nAccount=1\r\nProfile=1\r\n'

            # 写回 UTF-16-LE with BOM
            with open(common_ini_path, 'wb') as f:
                f.write(b'\xff\xfe')  # BOM
                f.write(output.encode('utf-16-le'))

            logger.info(f"Updated MT5 common.ini (UTF-16-LE): Login={request.mt5_login}, Server={request.mt5_server}")
        except Exception as e:
            logger.warning(f"Failed to update common.ini: {e}, continuing anyway")

        # 清理旧的账户数据（让 MT5 重新登录）
        accounts_dat = mt5_client_dir / "Config" / "accounts.dat"
        if accounts_dat.exists():
            accounts_dat.unlink()
            logger.info("Cleared old accounts.dat")

        # 清理旧的服务器数据（不删！保留模板中已配置的服务器列表）
        # servers_dat 包含该平台的服务器信息，删除后 MT5 需要重新发现，会导致无法自动连接
        # servers_dat = mt5_client_dir / "Config" / "servers.dat"

        # 新的 MT5 客户端路径
        new_mt5_path = str(mt5_client_dir / "terminal64.exe")

        # ==================== 1.5 配置产品/符号（Chart Profiles） ====================
        if request.symbols:
            try:
                # 配置 Default chart profile — 每个产品一个图表窗口
                charts_dir = mt5_client_dir / "Profiles" / "Charts" / "Default"
                charts_dir.mkdir(parents=True, exist_ok=True)

                # 删除旧的 chart 文件
                for old_chr in charts_dir.glob("chart*.chr"):
                    old_chr.unlink()

                # 为每个产品创建图表文件（UTF-16-LE with BOM）
                for idx, symbol in enumerate(request.symbols):
                    chr_content = (
                        f'<chart>\r\n'
                        f'id={128968168864101562 + idx}\r\n'
                        f'symbol={symbol}\r\n'
                        f'period_type=0\r\n'
                        f'period_size=1\r\n'
                        f'digits=2\r\n'
                        f'tick_size=0.000000\r\n'
                        f'scale_fix=0\r\n'
                        f'</chart>\r\n'
                    )
                    chr_path = charts_dir / f"chart{idx+1:02d}.chr"
                    with open(chr_path, 'wb') as f:
                        f.write(b'\xff\xfe')
                        f.write(chr_content.encode('utf-16-le'))

                # 更新 terminal.ini 的 MarketWatch 符号列表（确保 Market Watch 窗口显示这些产品）
                terminal_ini_path = mt5_client_dir / "Config" / "terminal.ini"
                if terminal_ini_path.exists():
                    with open(terminal_ini_path, 'rb') as f:
                        raw = f.read()
                    text = raw.decode('utf-16-le') if raw[:2] == b'\xff\xfe' else raw.decode('utf-8', errors='replace')
                    if text.startswith('\ufeff'):
                        text = text[1:]

                    # 在文件末尾添加/更新 Symbols 配置
                    lines = text.splitlines()
                    # 移除旧的 [SymbolsSelected] 部分
                    new_lines = []
                    skip = False
                    for line in lines:
                        if line.strip() == '[SymbolsSelected]':
                            skip = True
                            continue
                        if skip and line.startswith('['):
                            skip = False
                        if not skip:
                            new_lines.append(line)

                    # 添加新的 [SymbolsSelected] 部分
                    new_lines.append('[SymbolsSelected]')
                    for symbol in request.symbols:
                        new_lines.append(f'{symbol}=1')

                    output = '\r\n'.join(new_lines) + '\r\n'
                    with open(terminal_ini_path, 'wb') as f:
                        f.write(b'\xff\xfe')
                        f.write(output.encode('utf-16-le'))

                logger.info(f"Configured {len(request.symbols)} symbols in chart profiles: {request.symbols}")
            except Exception as e:
                logger.warning(f"Failed to configure symbols: {e}, continuing anyway")

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
            ['C:/nssm/nssm.exe', 'install', request.service_name, uvicorn_path],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'AppParameters', f'main:app --host 0.0.0.0 --port {request.service_port}'],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'AppDirectory', app_dir],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'AppExit', 'Default', 'Restart'],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'AppEnvironmentExtra', ':PYTHONUNBUFFERED=1'],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'AppStdout', str(deploy_dir / 'logs' / 'stdout.log')],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'AppStderr', str(deploy_dir / 'logs' / 'stderr.log')],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'AppRotateFiles', '1'],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'AppRotateOnline', '1'],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'AppRotateSeconds', '86400'],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'AppRotateBytes', '10485760'],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'DisplayName', request.service_name],
            ['C:/nssm/nssm.exe', 'set', request.service_name, 'Start', 'SERVICE_AUTO_START'],
        ]

        for cmd in nssm_commands:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                logger.error(f"NSSM command failed: {' '.join(cmd)}, error: {result.stderr}")
                raise HTTPException(status_code=500, detail=f"服务配置失败: {result.stderr}")

        logger.info(f"Bridge service {request.service_name} configured successfully")

        # 启动服务
        result = subprocess.run(['C:/nssm/nssm.exe', 'start', request.service_name], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.warning(f"Failed to start service: {result.stderr}")

        # ==================== 3.5 首次启动 MT5 写入登录凭证 ====================
        # MT5 不在 common.ini 存密码，需要启动一次让它自动登录并保存 accounts.dat
        try:
            mt5_exe = mt5_client_dir / "terminal64.exe"
            if mt5_exe.exists():
                # 用命令行参数传入完整凭证启动 MT5（/portable 模式）
                mt5_cmd = [
                    str(mt5_exe), '/portable',
                    f'/login:{request.mt5_login}',
                    f'/password:{request.mt5_password}',
                    f'/server:{request.mt5_server}',
                ]
                logger.info(f"Starting MT5 for initial login: {request.mt5_login}@{request.mt5_server}")
                mt5_proc = subprocess.Popen(mt5_cmd, cwd=str(mt5_client_dir))

                # 等待 MT5 启动并登录保存凭证（给足时间让它连接服务器并写入 accounts.dat）
                time.sleep(15)

                # 关闭 MT5（凭证已保存到 accounts.dat）
                mt5_proc.terminate()
                try:
                    mt5_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    mt5_proc.kill()
                logger.info(f"MT5 initial login completed, credentials saved to accounts.dat")
        except Exception as e:
            logger.warning(f"Failed to perform MT5 initial login: {e}")

        # ==================== 4. 创建桌面快捷方式 ====================
        try:
            desktop_path = Path("C:/Users/Administrator/Desktop")
            if not desktop_path.exists():
                logger.warning(f"Desktop path not found: {desktop_path}")
            else:
                # 快捷方式名称：MT5 登录账号+服务端口
                shortcut_name = f"MT5 {request.mt5_login}+{request.service_port}.lnk"
                shortcut_path = desktop_path / shortcut_name

                # 转换路径为 Windows 格式
                win_shortcut_path = str(shortcut_path).replace('/', '\\')
                win_target_path = new_mt5_path.replace('/', '\\')
                win_working_dir = str(mt5_client_dir).replace('/', '\\')

                # 使用 PowerShell 创建快捷方式（更可靠）
                ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{win_shortcut_path}")
$Shortcut.TargetPath = "{win_target_path}"
$Shortcut.Arguments = "/portable /login:{request.mt5_login} /password:{request.mt5_password} /server:{request.mt5_server}"
$Shortcut.WorkingDirectory = "{win_working_dir}"
$Shortcut.IconLocation = "{win_target_path}"
$Shortcut.Description = "MT5 Client - {request.mt5_login} on port {request.service_port}"
$Shortcut.Save()
"""
                result = subprocess.run(
                    ['powershell', '-Command', ps_script],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    logger.info(f"Created desktop shortcut: {shortcut_path}")
                else:
                    logger.warning(f"Failed to create shortcut: {result.stderr}")
        except Exception as e:
            logger.warning(f"Failed to create desktop shortcut: {e}")

        # ==================== 5. 添加 Windows 防火墙入站规则 ====================
        try:
            fw_rule_name = f"MT5Bridge-{request.service_port}"
            # 先删除同名旧规则（避免重复）
            subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={fw_rule_name}'],
                capture_output=True, text=True, timeout=10
            )
            result = subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                 f'name={fw_rule_name}', 'dir=in', 'action=allow', 'protocol=TCP',
                 f'localport={request.service_port}'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                logger.info(f"Firewall rule added: {fw_rule_name} (TCP {request.service_port} inbound)")
            else:
                logger.warning(f"Failed to add firewall rule: {result.stderr}")
        except Exception as e:
            logger.warning(f"Failed to add firewall rule: {e}")

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
            # 清理防火墙规则
            subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name=MT5Bridge-{request.service_port}'],
                capture_output=True, text=True, timeout=10
            )
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

        # 1. 停止 NSSM 服务
        try:
            subprocess.run(['C:/nssm/nssm.exe', 'stop', service_name], capture_output=True, text=True, timeout=15)
            logger.info(f"Stopped service: {service_name}")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Failed to stop service: {e}")

        # 1.5 强制杀掉所有使用该部署目录的进程（Python/uvicorn/nssm子进程）
        try:
            deploy_str = str(deploy_dir).replace('/', '\\')
            # 方法1: 用 psutil 扫描所有进程
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline', 'cwd']):
                try:
                    info = proc.info
                    cmdline = ' '.join(info.get('cmdline') or [])
                    exe = info.get('exe') or ''
                    cwd = info.get('cwd') or ''
                    if (service_name in cmdline or deploy_str.lower() in cmdline.lower()
                        or deploy_str.lower() in exe.lower()
                        or deploy_str.lower() in cwd.lower()):
                        proc.kill()
                        logger.info(f"Killed process: PID={proc.pid}, name={info.get('name')}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            # 方法2: 用 taskkill 按服务端口号杀（bridge 服务的 uvicorn 进程）
            if mt5_client_port:
                try:
                    subprocess.run(
                        ['powershell', '-Command',
                         f'$p = Get-NetTCPConnection -LocalPort {mt5_client_port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess; if ($p) {{ Stop-Process -Id $p -Force }}'],
                        capture_output=True, text=True, timeout=10)
                except Exception:
                    pass
            time.sleep(3)
        except Exception as e:
            logger.warning(f"Failed to kill processes: {e}")

        # 2. 删除服务
        try:
            result = subprocess.run(['C:/nssm/nssm.exe', 'remove', service_name, 'confirm'],
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                logger.info(f"Removed service: {service_name}")
            else:
                logger.warning(f"Failed to remove service: {result.stderr}")
        except Exception as e:
            logger.warning(f"Failed to remove service: {e}")

        # 3. 删除 Bridge 部署目录（带重试 + 强制进程清理）
        if deploy_dir.exists():
            for attempt in range(5):
                try:
                    shutil.rmtree(deploy_dir)
                    logger.info(f"Removed Bridge deployment directory: {deploy_dir}")
                    break
                except Exception as e:
                    logger.warning(f"rmtree attempt {attempt+1} failed: {e}")
                    # 用 taskkill 强制杀掉所有可能锁文件的进程
                    try:
                        # 查找使用该目录的句柄
                        handle_result = subprocess.run(
                            ['powershell', '-Command',
                             f'Get-Process python* | Where-Object {{ $_.Path -and $_.Path -like "*{service_name}*" }} | Stop-Process -Force'],
                            capture_output=True, text=True, timeout=10)
                        # 也杀 uvicorn
                        subprocess.run(
                            ['powershell', '-Command',
                             f'Get-Process | Where-Object {{ $_.MainWindowTitle -match "{service_name}" -or ($_.Path -and $_.Path -like "*{service_name}*") }} | Stop-Process -Force'],
                            capture_output=True, text=True, timeout=10)
                    except Exception:
                        pass
                    time.sleep(3 + attempt * 2)  # 递增等待

        # 4. 删除 MT5 客户端目录（如果提供了端口号）
        if mt5_client_port:
            mt5_client_dir = Path(f"D:/MetaTrader 5-{mt5_client_port}")
            if mt5_client_dir.exists():
                # 先杀掉该目录下的所有进程（terminal64.exe + 子进程）
                mt5_dir_str = str(mt5_client_dir).replace('/', '\\').lower()
                for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                    try:
                        exe = (proc.info.get('exe') or '').lower()
                        cmdline = ' '.join(proc.info.get('cmdline') or []).lower()
                        if mt5_dir_str in exe or mt5_dir_str in cmdline:
                            proc.kill()
                            logger.info(f"Killed MT5 process: PID={proc.pid}, exe={exe}")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

            # 也杀掉使用该 mt5_login 的 terminal64.exe（可能从其他路径启动）
            if mt5_login:
                for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                    try:
                        if (proc.info.get('name') or '').lower() != 'terminal64.exe':
                            continue
                        cmdline = ' '.join(proc.info.get('cmdline') or [])
                        exe_path = proc.info.get('exe') or ''
                        # 检查进程的 common.ini 是否包含该 login
                        proc_dir = Path(exe_path).parent if exe_path else None
                        if proc_dir:
                            common_ini = proc_dir / "Config" / "common.ini"
                            if common_ini.exists():
                                try:
                                    raw = common_ini.read_bytes()
                                    text = raw.decode('utf-16-le', errors='ignore')
                                    if f'Login={mt5_login}' in text:
                                        proc.kill()
                                        logger.info(f"Killed MT5 terminal (login={mt5_login}): PID={proc.pid}, exe={exe_path}")
                                except Exception:
                                    pass
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            time.sleep(3)  # 等进程完全退出

            if mt5_client_dir.exists():
                # 删除 MT5 客户端目录
                import shutil as _shutil
                _shutil.rmtree(mt5_client_dir, ignore_errors=True)
                if mt5_client_dir.exists():
                    # 二次尝试
                    time.sleep(2)
                    _shutil.rmtree(mt5_client_dir, ignore_errors=True)
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

        # 6. 删除 Windows 防火墙入站规则
        if mt5_client_port:
            try:
                fw_rule_name = f"MT5Bridge-{mt5_client_port}"
                result = subprocess.run(
                    ['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={fw_rule_name}'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    logger.info(f"Firewall rule removed: {fw_rule_name}")
                else:
                    logger.warning(f"Failed to remove firewall rule: {result.stderr}")
            except Exception as e:
                logger.warning(f"Failed to remove firewall rule: {e}")

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

    # 延迟启动 Bridge 服务（等待 MT5 终端启动）
    asyncio.create_task(_auto_start_bridges())


async def _auto_start_bridges():
    """开机后自动启动所有已部署的 Bridge 服务（在用户会话中）"""
    import asyncio, socket

    # 等待 30s，让 MT5 终端进程有时间先启动
    await asyncio.sleep(30)

    bridge_base = Path("D:/")
    started = []

    for svc_dir in sorted(bridge_base.glob("hustle-mt5-*")):
        svc = svc_dir.name
        env_file = svc_dir / ".env"
        python_exe = svc_dir / "venv" / "Scripts" / "python.exe"
        app_dir = svc_dir / "app"

        if not env_file.exists() or not python_exe.exists() or not app_dir.exists():
            continue

        # 读取端口
        port = None
        try:
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("SERVICE_PORT="):
                        port = int(line.strip().split("=", 1)[1])
                        break
        except Exception:
            continue

        if not port:
            continue

        # 检查端口是否已监听
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                logger.info(f"[AutoStart] {svc}:{port} already running")
                continue
        except Exception:
            pass  # 未监听，需要启动

        # 加载 .env
        env = dict(os.environ)
        try:
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()
        except Exception as e:
            logger.warning(f"[AutoStart] {svc}: .env read error: {e}")
            continue

        env["PYTHONUNBUFFERED"] = "1"

        # 启动 Bridge 进程
        try:
            log_out = open(svc_dir / "logs" / "stdout.log", "w")
            log_err = open(svc_dir / "logs" / "stderr.log", "w")
            proc = subprocess.Popen(
                [str(python_exe), "-m", "uvicorn", "main:app",
                 "--host", "0.0.0.0", "--port", str(port)],
                cwd=str(app_dir),
                env=env,
                stdout=log_out,
                stderr=log_err,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            log_out.close()
            log_err.close()
            started.append(f"{svc}:{port} (PID={proc.pid})")
            logger.info(f"[AutoStart] Started {svc} on port {port}, PID={proc.pid}")
        except Exception as e:
            logger.error(f"[AutoStart] Failed to start {svc}: {e}")

        await asyncio.sleep(2)  # 间隔启动，避免同时争用 MT5 API

    if started:
        logger.info(f"[AutoStart] Started {len(started)} bridge(s): {', '.join(started)}")
    else:
        logger.info("[AutoStart] No bridges needed starting")

# ====================== 主程序入口 ======================
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=agent_config["host"],
        port=agent_config["port"],
        log_level="info"
    )
