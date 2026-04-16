"""系统监控API路由"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime
import subprocess
import redis as redis_lib
from cryptography import x509
from cryptography.hazmat.backends import default_backend

from app.core.security import get_current_user_id_optional

router = APIRouter()
logger = logging.getLogger(__name__)

SSL_DOMAINS = [
    "go.hustle2026.xyz",
    "admin.hustle2026.xyz",
    "www.hustle2026.xyz",
]


def check_redis_status() -> Dict[str, Any]:
    try:
        r = redis_lib.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=2)
        r.ping()
        info = r.info()
        return {
            "status": "healthy", "connected": True,
            "version": info.get('redis_version', 'unknown'),
            "uptime_seconds": info.get('uptime_in_seconds', 0),
            "connected_clients": info.get('connected_clients', 0),
            "used_memory_human": info.get('used_memory_human', '0'),
            "error": None
        }
    except redis_lib.ConnectionError as e:
        return {"status": "error", "connected": False, "error": f"无法连接到Redis: {str(e)}"}
    except Exception as e:
        return {"status": "error", "connected": False, "error": str(e)}


def check_feishu_status() -> Dict[str, Any]:
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="127.0.0.1", port=5432, dbname="postgres",
            user="postgres", password="Lk106504"
        )
        cur = conn.cursor()
        cur.execute("SELECT is_enabled, config_data FROM notification_configs WHERE service_type='feishu' LIMIT 1")
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            return {"status": "not_configured", "configured": False, "error": "飞书未配置"}
        is_enabled, config_data = row
        if not is_enabled:
            return {"status": "disabled", "configured": True, "error": None}
        app_id = (config_data or {}).get('app_id', '')
        if not app_id:
            return {"status": "not_configured", "configured": False, "error": "app_id 未设置"}
        return {"status": "healthy", "configured": True, "error": None}
    except Exception as e:
        logger.error(f"检查飞书状态失败: {e}")
        return {"status": "error", "configured": False, "error": str(e)}


def check_mt5_clients() -> List[Dict[str, Any]]:
    try:
        import psycopg2
        import os, httpx
        conn = psycopg2.connect(
            host="127.0.0.1", port=5432, dbname="postgres",
            user="postgres", password="Lk106504"
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT mc.client_name, mc.mt5_login, mc.connection_status, mc.is_active,
                   u.username, mc.bridge_service_port, mc.is_system_service
            FROM mt5_clients mc
            LEFT JOIN accounts a ON mc.account_id = a.account_id
            LEFT JOIN users u ON a.user_id = u.user_id
            ORDER BY mc.client_name
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()

        bridge_host = os.getenv("MT5_BRIDGE_HOST", "http://172.31.14.113").rstrip("/")

        results = []
        for r in rows:
            client_name, mt5_login, db_status, is_active, username, bridge_port, is_system_service = r
            online = False
            # 实时检测 Bridge /health 端点
            if bridge_port:
                try:
                    resp = httpx.get(f"{bridge_host}:{bridge_port}/health", timeout=2.0)
                    if resp.status_code == 200:
                        online = resp.json().get("mt5", False)
                except Exception:
                    pass
            results.append({
                "client_name": client_name, "mt5_login": mt5_login,
                "connection_status": "connected" if online else "disconnected",
                "is_active": is_active,
                "username": username or '--',
                "online": online,
                "is_system_service": bool(is_system_service)
            })
        return results
    except Exception as e:
        logger.error(f"查询MT5客户端失败: {e}")
        return []


def read_cert_bytes(domain: str) -> Optional[bytes]:
    cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    try:
        result = subprocess.run(
            ["sudo", "cat", cert_path],
            capture_output=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    # fallback: direct read
    try:
        from pathlib import Path
        return Path(cert_path).read_bytes()
    except Exception:
        return None


def check_ssl_cert(domain: str) -> Dict[str, Any]:
    cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    cert_bytes = read_cert_bytes(domain)
    if not cert_bytes:
        return {
            "domain": domain, "cert_path": cert_path, "exists": False,
            "status": "error", "days_remaining": None,
            "domain_names": [domain], "error": "未找到证书文件"
        }
    try:
        cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())
        not_after = cert.not_valid_after
        now = datetime.utcnow()
        days_remaining = (not_after - now).days
        if now > not_after:
            status = "expired"
        elif days_remaining <= 7:
            status = "critical"
        elif days_remaining <= 30:
            status = "warning"
        else:
            status = "healthy"
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            domains = [name.value for name in san.value]
        except Exception:
            domains = [domain]
        return {
            "domain": domain, "cert_path": cert_path, "exists": True,
            "status": status, "days_remaining": days_remaining,
            "domain_names": domains,
            "expires_at": not_after.isoformat(), "error": None
        }
    except Exception as e:
        return {
            "domain": domain, "cert_path": cert_path, "exists": True,
            "status": "error", "days_remaining": None,
            "domain_names": [domain], "error": str(e)
        }


@router.get("/status")
async def get_system_status(
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    try:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "redis": check_redis_status(),
            "feishu": check_feishu_status(),
            "ssl_certificate": [check_ssl_cert(d) for d in SSL_DOMAINS],
            "mt5_clients": check_mt5_clients(),
        }
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取系统状态失败: {str(e)}")


@router.get("/ssl/current")
async def get_current_ssl_certificate(
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    return [check_ssl_cert(d) for d in SSL_DOMAINS]
