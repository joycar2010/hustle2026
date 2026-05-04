import os
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import psutil
import redis as redis_lib
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models_auth import User
from app.db.models_ssl import SSLCertificate
from app.db.models_proxy import ProxyPool
from app.db.models import FeishuConfig
from app.db.models_ai import AiConfig, AiConversation, AiMessage
from app.db.session import get_db
from app.config import settings
from app.middleware.permissions import require_admin
from engine.models import Position, EngineState, TradeLog

router = APIRouter(prefix="/api/admin/dashboard", tags=["admin-dashboard"])

_process = psutil.Process(os.getpid())
_start_time = time.time()


def _get_redis_info() -> dict:
    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        info = r.info()
        db_keys = 0
        for key in info:
            if key.startswith("db") and isinstance(info[key], dict):
                db_keys += info[key].get("keys", 0)
        return {
            "connected": True,
            "version": info.get("redis_version", "unknown"),
            "used_memory_human": info.get("used_memory_human", "0B"),
            "connected_clients": info.get("connected_clients", 0),
            "keys": db_keys,
        }
    except Exception:
        return {
            "connected": False,
            "version": "N/A",
            "used_memory_human": "N/A",
            "connected_clients": 0,
            "keys": 0,
        }


def _get_server_info() -> dict:
    uptime_seconds = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    mem = _process.memory_info()
    cpu = _process.cpu_percent(interval=0)

    return {
        "python_uptime": uptime_str,
        "memory_mb": round(mem.rss / 1024 / 1024, 1),
        "cpu_percent": round(cpu, 1),
        "pid": os.getpid(),
        "redis": _get_redis_info(),
    }


def _get_feishu_status(db: Session) -> dict:
    configs = db.query(FeishuConfig).all()
    if not configs:
        return {"connected": False, "token_expires_at": None, "error": "未配置",
                "count": 0, "webhooks": 0}
    webhooks = sum(1 for c in configs if c.webhook_url)
    global_cfg = next((c for c in configs if c.user_id is None), None)
    app_id = getattr(global_cfg, "app_id", "") or "" if global_cfg else ""
    app_secret = getattr(global_cfg, "app_secret", "") or "" if global_cfg else ""
    if not app_id:
        return {"connected": False, "token_expires_at": None, "error": "App ID 未配置",
                "count": len(configs), "webhooks": webhooks}
    try:
        import httpx
        resp = httpx.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret}, timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            return {"connected": False, "token_expires_at": None,
                    "error": data.get("msg", "token获取失败"),
                    "count": len(configs), "webhooks": webhooks}
        expire = data.get("expire", 7200)
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expire)).isoformat()
        return {"connected": True, "token_expires_at": expires_at, "error": None,
                "count": len(configs), "webhooks": webhooks}
    except Exception as e:
        return {"connected": False, "token_expires_at": None, "error": str(e)[:80],
                "count": len(configs), "webhooks": webhooks}


def _get_aicoin_status() -> dict:
    configured = bool(settings.aicoin_api_key and settings.aicoin_api_secret)
    if not configured:
        return {"status": "not_configured", "connected": False, "api_key_set": False}
    try:
        from app.services.aicoin_client import AiCoinClient
        import asyncio
        client = AiCoinClient(settings.aicoin_api_key, settings.aicoin_api_secret)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client.get_coin_list())
            return {"status": "connected", "connected": True, "api_key_set": True}
        except Exception as e:
            return {"status": "error", "connected": False, "api_key_set": True, "error": str(e)[:100]}
        finally:
            loop.close()
    except Exception as e:
        return {"status": "error", "connected": False, "api_key_set": True, "error": str(e)[:100]}


def _get_ai_chat_status(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sites = {}
    for site_name in ("coin", "coinadmin"):
        cfg = db.query(AiConfig).filter(AiConfig.site == site_name).first()
        today_msgs = db.query(func.count(AiMessage.id)).join(
            AiConversation, AiMessage.conversation_id == AiConversation.id
        ).filter(
            AiConversation.site == site_name,
            AiMessage.created_at >= today_start,
        ).scalar() or 0
        total_convs = db.query(func.count(AiConversation.id)).filter(
            AiConversation.site == site_name,
        ).scalar() or 0
        sites[site_name] = {
            "enabled": cfg.is_enabled if cfg else False,
            "provider": cfg.provider if cfg else None,
            "model": cfg.model_name if cfg else None,
            "today_messages": today_msgs,
            "total_conversations": total_convs,
        }
    return sites


def _get_rust_engine_status() -> dict:
    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2, decode_responses=True)
        spread_count = r.hlen("spreads")
        channels = r.pubsub_channels("*")
        channel_list = [c if isinstance(c, str) else c.decode() for c in channels]
        spread_active = "spread:updates" in channel_list
        if spread_count > 0 and spread_active:
            return {"status": "running", "spread_pairs": spread_count, "channel_active": True}
        elif spread_count > 0:
            return {"status": "idle", "spread_pairs": spread_count, "channel_active": False}
        else:
            return {"status": "stopped", "spread_pairs": 0, "channel_active": False}
    except Exception:
        return {"status": "unknown", "spread_pairs": 0, "channel_active": False}


def _get_ws_status() -> dict:
    try:
        from app.api.websocket import manager
        connections = len(manager.active)
    except Exception:
        connections = 0

    streamers = []
    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2, decode_responses=True)
        spread_count = r.hlen("spreads")
        streamers.append({"name": "spread_data", "status": "active" if spread_count > 0 else "idle", "count": spread_count})
        channels = r.pubsub_channels("*")
        channel_list = [c if isinstance(c, str) else c.decode() for c in channels]
        for ch, display in [("position:updates", "position_update"), ("worker:status", "engine_status"), ("balance:updates", "balance_update")]:
            streamers.append({"name": display, "status": "active" if ch in channel_list else "idle", "count": 0})
    except Exception:
        streamers = [
            {"name": "spread_data", "status": "error", "count": 0},
            {"name": "position_update", "status": "error", "count": 0},
            {"name": "engine_status", "status": "error", "count": 0},
            {"name": "balance_update", "status": "error", "count": 0},
        ]
    return {"connections": connections, "streamers": streamers}


@router.get("/overview")
def dashboard_overview(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    now = datetime.now(timezone.utc)

    total_users = db.query(func.count(User.id)).scalar() or 0
    active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0

    open_positions = db.query(func.count(Position.id)).filter(Position.status == "OPEN").scalar() or 0
    total_open_usdt = db.query(func.coalesce(func.sum(Position.open_usdt_amount), 0)).filter(
        Position.status == "OPEN"
    ).scalar()

    total_funding = db.query(func.coalesce(func.sum(Position.cumulative_funding_fee), 0)).filter(
        Position.status == "OPEN"
    ).scalar()
    total_interest = db.query(func.coalesce(func.sum(Position.cumulative_interest), 0)).filter(
        Position.status == "OPEN"
    ).scalar()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_closed = db.query(func.count(Position.id)).filter(
        Position.status == "CLOSED",
        Position.closed_at >= today_start,
    ).scalar() or 0
    today_pnl = db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
        Position.status == "CLOSED",
        Position.closed_at >= today_start,
    ).scalar()

    engine_states = db.query(EngineState).filter(EngineState.scope == "global").all()
    running_engines = sum(1 for e in engine_states if e.status == "RUNNING")

    proxy_total = db.query(func.count(ProxyPool.id)).scalar() or 0
    proxy_active = db.query(func.count(ProxyPool.id)).filter(ProxyPool.status == "active").scalar() or 0
    proxy_error = db.query(func.count(ProxyPool.id)).filter(ProxyPool.status == "error").scalar() or 0

    # SSL cert warnings (expiring within 30 days)
    expiring_certs = db.query(SSLCertificate).filter(
        SSLCertificate.expires_at <= now + timedelta(days=30),
        SSLCertificate.expires_at > now,
        SSLCertificate.status == "active",
    ).all()
    cert_warnings = [
        {
            "id": c.id,
            "domain": c.domain_name,
            "expires_at": str(c.expires_at),
            "days_left": max(0, (c.expires_at.replace(tzinfo=timezone.utc) - now).days),
        }
        for c in expiring_certs
    ]

    # All SSL certs for dashboard display
    all_certs = db.query(SSLCertificate).filter(SSLCertificate.status == "active").all()
    ssl_certs = [
        {
            "id": c.id,
            "domain": c.domain_name,
            "expires_at": str(c.expires_at) if c.expires_at else None,
            "days_left": max(0, (c.expires_at.replace(tzinfo=timezone.utc) - now).days) if c.expires_at else None,
            "status": c.status,
        }
        for c in all_certs
    ]

    # Per-user engine status
    users = db.query(User).filter(User.is_active == True).all()
    engine_users = []
    for u in users:
        es = db.query(EngineState).filter(
            EngineState.user_id == u.id,
            EngineState.scope == "global",
        ).first()
        user_open = db.query(func.count(Position.id)).filter(
            Position.user_id == u.id,
            Position.status == "OPEN",
        ).scalar() or 0
        user_pnl = db.query(func.coalesce(func.sum(Position.realized_pnl), 0)).filter(
            Position.user_id == u.id,
            Position.status == "CLOSED",
        ).scalar()
        last_trade = db.query(TradeLog.created_at).filter(
            TradeLog.user_id == u.id,
        ).order_by(TradeLog.created_at.desc()).first()
        worker_states = db.query(EngineState).filter(
            EngineState.user_id == u.id,
            EngineState.scope != "global",
        ).all()

        engine_users.append({
            "user_id": u.id,
            "username": u.username,
            "status": es.status if es else "STOPPED",
            "worker_count": len(worker_states),
            "open_positions": user_open,
            "total_pnl": str(Decimal(str(user_pnl))),
            "last_trade_at": str(last_trade[0]) if last_trade else None,
        })

    return {
        "users": {"total": total_users, "active": active_users},
        "positions": {
            "open": open_positions,
            "total_usdt": str(Decimal(str(total_open_usdt))),
            "total_funding": str(Decimal(str(total_funding))),
            "total_interest": str(Decimal(str(total_interest))),
        },
        "today": {
            "closed_count": today_closed,
            "pnl": str(Decimal(str(today_pnl))),
        },
        "engines": {
            "running": running_engines,
            "total": len(engine_states),
        },
        "proxies": {
            "total": proxy_total,
            "active": proxy_active,
            "error": proxy_error,
        },
        "cert_warnings": cert_warnings,
        "ssl_certs": ssl_certs,
        "server": _get_server_info(),
        "feishu": _get_feishu_status(db),
        "engine_users": engine_users,
        "aicoin": _get_aicoin_status(),
        "ai_chat": _get_ai_chat_status(db),
        "rust_engine": _get_rust_engine_status(),
        "websocket": _get_ws_status(),
    }
