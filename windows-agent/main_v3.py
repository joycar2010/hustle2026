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
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
import uvicorn
import httpx

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
monitoring_config = config["monitoring"]

# ====================== 实例配置管理 ======================
def load_instances() -> Dict:
    """加载实例配置"""
    if not INSTANCES_FILE.exists():
        return {}
    try:
        with open(INSTANCES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_instances(instances: Dict):
    """保存实例配置"""
    with open(INSTANCES_FILE, 'w', encoding='utf-8') as f:
        json.dump(instances, f, indent=2, ensure_ascii=False)

# ====================== MT5 控制器 ======================
class MT5Controller:
    """MT5 实例控制器"""

    @staticmethod
    def is_instance_running(mt5_path: str) -> bool:
        """检查指定路径的 MT5 实例是否运行"""
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

    @staticmethod
    def get_instance_process(mt5_path: str) -> Optional[psutil.Process]:
        """获取指定路径的 MT5 进程对象"""
        target_path = os.path.normpath(mt5_path).lower()
        for proc in psutil.process_iter(['name', 'exe', 'pid']):
            try:
                if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
                    proc_path = os.path.normpath(proc.info['exe']).lower()
                    if proc_path == target_path:
                        return psutil.Process(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return None

    @staticmethod
    def start_instance(instance_config: Dict, wait_seconds: int = 5) -> bool:
        """启动 MT5 实例"""
        mt5_path = instance_config["path"]

        # 检查是否已运行
        if MT5Controller.is_instance_running(mt5_path):
            logger.info(f"Instance {instance_config['name']} is already running")
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

        # 设置创建标志
        creation_flags = 0
        if instance_config.get("create_no_window", False):
            creation_flags = subprocess.CREATE_NO_WINDOW

        try:
            subprocess.Popen(
                cmd,
                cwd=os.path.dirname(mt5_path),
                creationflags=creation_flags,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info(f"Started instance {instance_config['name']}, waiting {wait_seconds}s...")
            time.sleep(wait_seconds)

            if MT5Controller.is_instance_running(mt5_path):
                logger.info(f"Instance {instance_config['name']} started successfully")
                return True
            else:
                logger.error(f"Instance {instance_config['name']} failed to start")
                return False
        except Exception as e:
            logger.error(f"Failed to start instance {instance_config['name']}: {e}")
            return False

    @staticmethod
    def stop_instance(instance_config: Dict, force: bool = True) -> bool:
        """停止 MT5 实例"""
        mt5_path = instance_config["path"]

        if not MT5Controller.is_instance_running(mt5_path):
            logger.info(f"Instance {instance_config['name']} is not running")
            return True

        target_path = os.path.normpath(mt5_path).lower()
        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    if proc.info['name'] == 'terminal64.exe' and proc.info['exe']:
                        proc_path = os.path.normpath(proc.info['exe']).lower()
                        if proc_path == target_path:
                            if force:
                                proc.kill()
                            else:
                                proc.terminate()
                            logger.info(f"Stopped instance {instance_config['name']} (PID: {proc.info['pid']})")
                            time.sleep(2)
                            if not MT5Controller.is_instance_running(mt5_path):
                                return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            logger.error(f"Failed to stop instance {instance_config['name']}")
            return False
        except Exception as e:
            logger.error(f"Error stopping instance {instance_config['name']}: {e}")
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
        proc = MT5Controller.get_instance_process(mt5_path)

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
    """创建/更新实例配置"""
    instances = load_instances()
    instance_name = instance.name.lower().replace(" ", "_")
    instances[instance_name] = instance.dict()
    save_instances(instances)
    logger.info(f"Instance {instance_name} created/updated")
    return {"success": True, "instance_name": instance_name}

@app.delete("/instances/{instance_name}", dependencies=[Depends(verify_api_key)])
def delete_instance(instance_name: str):
    """删除实例配置"""
    instances = load_instances()
    if instance_name not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")

    # 先停止实例
    controller.stop_instance(instances[instance_name])
    del instances[instance_name]
    save_instances(instances)
    logger.info(f"Instance {instance_name} deleted")
    return {"success": True}

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
