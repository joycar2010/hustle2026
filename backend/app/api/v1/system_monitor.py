"""系统监控API路由"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime
from pathlib import Path
import subprocess
import redis
import requests
import httpx
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user_id_optional
from app.core.database import get_db
from app.models.mt5_client import MT5Client
from app.models.mt5_instance import MT5Instance
from app.models.account import Account
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)

# 配置路径
NGINX_SSL_CERT_PATH = Path("C:/nginx/ssl/fullchain.pem")
NGINX_SSL_KEY_PATH = Path("C:/nginx/ssl/privkey.pem")


def check_redis_status() -> Dict[str, Any]:
    """检查Redis连接状态"""
    try:
        # 尝试连接Redis
        r = redis.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=2)
        r.ping()
        info = r.info()

        return {
            "status": "healthy",
            "connected": True,
            "version": info.get('redis_version', 'unknown'),
            "uptime_seconds": info.get('uptime_in_seconds', 0),
            "connected_clients": info.get('connected_clients', 0),
            "used_memory_human": info.get('used_memory_human', '0'),
            "error": None
        }
    except redis.ConnectionError as e:
        return {
            "status": "error",
            "connected": False,
            "error": f"无法连接到Redis: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "connected": False,
            "error": str(e)
        }


def check_feishu_status() -> Dict[str, Any]:
    """检查飞书通知服务状态"""
    try:
        from app.services.feishu_service import get_feishu_service

        feishu = get_feishu_service()
        if not feishu:
            return {
                "status": "not_configured",
                "configured": False,
                "error": "飞书服务未初始化"
            }

        # 检查是否有app_id和app_secret
        if not feishu.app_id or not feishu.app_secret:
            return {
                "status": "not_configured",
                "configured": False,
                "error": "飞书服务未配置"
            }

        # 服务已配置
        return {
            "status": "healthy",
            "configured": True,
            "error": None
        }

    except Exception as e:
        logger.error(f"检查飞书服务状态失败: {e}")
        return {
            "status": "error",
            "configured": False,
            "error": str(e)
        }


def check_nginx_ssl_certificate() -> Dict[str, Any]:
    """检查Nginx SSL证书状态"""
    try:
        if not NGINX_SSL_CERT_PATH.exists():
            return {
                "status": "error",
                "exists": False,
                "error": "证书文件不存在"
            }

        # 读取并解析证书
        cert_content = NGINX_SSL_CERT_PATH.read_bytes()
        cert = x509.load_pem_x509_certificate(cert_content, default_backend())

        # 获取证书信息
        not_before = cert.not_valid_before
        not_after = cert.not_valid_after
        now = datetime.utcnow()

        # 计算剩余天数
        days_remaining = (not_after - now).days

        # 确定状态
        if now > not_after:
            status = "expired"
        elif days_remaining <= 7:
            status = "critical"
        elif days_remaining <= 30:
            status = "warning"
        else:
            status = "healthy"

        # 获取域名
        try:
            san_extension = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            domains = [name.value for name in san_extension.value]
        except:
            domains = []

        # 获取颁发者
        issuer = cert.issuer.rfc4514_string()

        return {
            "status": status,
            "exists": True,
            "domain_names": domains,
            "issuer": issuer,
            "issued_at": not_before.isoformat(),
            "expires_at": not_after.isoformat(),
            "days_remaining": days_remaining,
            "is_valid": now < not_after,
            "cert_path": str(NGINX_SSL_CERT_PATH),
            "key_path": str(NGINX_SSL_KEY_PATH),
            "error": None
        }

    except Exception as e:
        logger.error(f"检查SSL证书失败: {e}")
        return {
            "status": "error",
            "exists": NGINX_SSL_CERT_PATH.exists(),
            "error": str(e)
        }


async def check_mt5_clients_status(db: AsyncSession) -> List[Dict[str, Any]]:
    """检查所有 MT5 客户端状态"""
    try:
        # 获取所有活跃的 MT5 客户端（排除系统服务账户）
        result = await db.execute(
            select(MT5Client, Account, User)
            .join(Account, MT5Client.account_id == Account.account_id)
            .join(User, Account.user_id == User.user_id)
            .where(MT5Client.is_active == True)
            .where(MT5Client.is_system_service == False)
        )
        clients_data = result.all()

        client_statuses = []
        for client, account, user in clients_data:
            # 获取关联的实例
            instance_result = await db.execute(
                select(MT5Instance)
                .where(MT5Instance.client_id == client.client_id)
                .where(MT5Instance.is_active == True)
                .limit(1)
            )
            instance = instance_result.scalar_one_or_none()

            # 检查进程状态
            process_running = False
            mt5_connected = False
            if instance:
                try:
                    # 调用 Windows Agent 检查进程健康
                    async with httpx.AsyncClient(timeout=2.0) as http_client:
                        health_resp = await http_client.get(
                            f"http://{instance.server_ip}:9000/instances/{instance.service_port}/health"
                        )
                        if health_resp.status_code == 200:
                            health_data = health_resp.json()
                            process_running = health_data.get("running", False)
                            mt5_connected = health_data.get("mt5_connected", False)
                except Exception as e:
                    logger.debug(f"Failed to check instance health for client {client.client_id}: {e}")

            client_statuses.append({
                "client_id": str(client.client_id),
                "client_name": client.client_name,
                "mt5_login": str(client.mt5_login),
                "mt5_server": client.mt5_server,
                "connection_status": client.connection_status,
                "online": client.connection_status == "connected" and mt5_connected,
                "process_running": process_running,
                "last_connected_at": client.last_connected_at.isoformat() if client.last_connected_at else None,
                "username": user.username if user else None,
            })

        return client_statuses

    except Exception as e:
        logger.error(f"检查 MT5 客户端状态失败: {e}")
        return []


@router.get("/status")
async def get_system_status(
    current_user_id: Optional[str] = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db)
):
    """获取系统各组件状态（包含 MT5 客户端状态）"""
    try:
        # 获取 MT5 客户端状态
        mt5_clients = await check_mt5_clients_status(db)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "redis": check_redis_status(),
            "feishu": check_feishu_status(),
            "ssl_certificate": [check_nginx_ssl_certificate()],  # 返回数组以保持兼容性
            "mt5_clients": mt5_clients
        }
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取系统状态失败: {str(e)}")


@router.get("/ssl/current")
async def get_current_ssl_certificate(
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """获取当前使用的SSL证书信息"""
    try:
        cert_info = check_nginx_ssl_certificate()
        return cert_info
    except Exception as e:
        logger.error(f"获取SSL证书信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取SSL证书信息失败: {str(e)}")
