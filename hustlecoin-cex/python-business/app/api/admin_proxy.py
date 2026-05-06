import logging
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models_proxy import ProxyPool, AccountProxyBinding, ProxyHealthLog, IpipgoOrder
from app.db.session import get_db
from app.middleware.permissions import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-proxy"])

IPIPGO_API_URL = "https://www.ipipgo.com/web/api/static-proxy/dynamic"
IPIPGO_KEY = "13957717158"
IPIPGO_SIGN = "ba7c97980567c023880039024549c44b"


class ProxyCreateRequest(BaseModel):
    name: str | None = None
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    protocol: str = "http"
    provider: str = "custom"
    region: str | None = None


class ProxyUpdateRequest(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    protocol: str | None = None
    status: str | None = None
    region: str | None = None


class ProxyBindRequest(BaseModel):
    sub_account_id: int
    proxy_id: int
    platform: str = "binance"


def _proxy_to_dict(p: ProxyPool) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "host": p.host,
        "port": p.port,
        "username": p.username,
        "protocol": p.protocol,
        "provider": p.provider,
        "status": p.status,
        "health_score": p.health_score,
        "last_check_at": str(p.last_check_at) if p.last_check_at else None,
        "region": p.region,
        "created_at": str(p.created_at) if p.created_at else None,
    }


# ---- Proxy Pool CRUD ----

@router.get("/proxies")
def list_proxies(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    proxies = db.query(ProxyPool).order_by(ProxyPool.id).all()
    return [_proxy_to_dict(p) for p in proxies]


@router.post("/proxies")
def create_proxy(data: ProxyCreateRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    proxy = ProxyPool(
        name=data.name,
        host=data.host,
        port=data.port,
        username=data.username,
        password=data.password,
        protocol=data.protocol,
        provider=data.provider,
        region=data.region,
    )
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return _proxy_to_dict(proxy)


@router.put("/proxies/{proxy_id}")
def update_proxy(proxy_id: int, data: ProxyUpdateRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    proxy = db.query(ProxyPool).filter(ProxyPool.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(proxy, field, value)
    db.commit()
    db.refresh(proxy)
    return _proxy_to_dict(proxy)


@router.delete("/proxies/{proxy_id}")
def delete_proxy(proxy_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    proxy = db.query(ProxyPool).filter(ProxyPool.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    db.query(AccountProxyBinding).filter(AccountProxyBinding.proxy_id == proxy_id).delete()
    db.delete(proxy)
    db.commit()
    return {"message": f"Proxy {proxy.host}:{proxy.port} deleted"}


@router.post("/proxies/health-check")
async def batch_health_check(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    proxies = db.query(ProxyPool).filter(ProxyPool.status != "inactive").all()

    results = []
    for proxy in proxies:
        proxy_url = f"{proxy.protocol}://"
        if proxy.username and proxy.password:
            proxy_url += f"{proxy.username}:{proxy.password}@"
        proxy_url += f"{proxy.host}:{proxy.port}"

        start = time.time()
        try:
            async with httpx.AsyncClient(
                proxy=proxy_url,
                timeout=10,
            ) as client:
                resp = await client.get("https://httpbin.org/ip")
                latency = int((time.time() - start) * 1000)
                if resp.status_code == 200:
                    status = "ok"
                    proxy.health_score = min(100, proxy.health_score + 10) if proxy.health_score else 100
                else:
                    status = "error"
                    proxy.health_score = max(0, (proxy.health_score or 100) - 20)
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            status = "error"
            proxy.health_score = max(0, (proxy.health_score or 100) - 30)
            log = ProxyHealthLog(
                proxy_id=proxy.id, status=status, latency_ms=latency,
                error_message=str(e),
            )
            db.add(log)
            results.append({"proxy_id": proxy.id, "status": status, "latency_ms": latency, "error": str(e)})
            continue

        proxy.last_check_at = datetime.now(timezone.utc)
        proxy.status = "active" if status == "ok" else "error"
        log = ProxyHealthLog(proxy_id=proxy.id, status=status, latency_ms=latency)
        db.add(log)
        results.append({"proxy_id": proxy.id, "status": status, "latency_ms": latency})

    db.commit()
    return {"checked": len(results), "results": results}


@router.get("/proxies/{proxy_id}/health-logs")
def proxy_health_logs(proxy_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    logs = db.query(ProxyHealthLog).filter(
        ProxyHealthLog.proxy_id == proxy_id,
    ).order_by(ProxyHealthLog.id.desc()).limit(50).all()
    return [
        {
            "id": log.id,
            "status": log.status,
            "latency_ms": log.latency_ms,
            "error_message": log.error_message,
            "checked_at": str(log.checked_at) if log.checked_at else None,
        }
        for log in logs
    ]


# ---- Account Proxy Bindings ----

@router.get("/proxies/bindings")
def list_bindings(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    bindings = db.query(AccountProxyBinding).order_by(AccountProxyBinding.id).all()
    return [
        {
            "id": b.id,
            "sub_account_id": b.sub_account_id,
            "proxy_id": b.proxy_id,
            "platform": b.platform,
            "is_active": b.is_active,
            "created_at": str(b.created_at) if b.created_at else None,
        }
        for b in bindings
    ]


@router.post("/proxies/bind")
def bind_proxy(data: ProxyBindRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    existing = db.query(AccountProxyBinding).filter(
        AccountProxyBinding.sub_account_id == data.sub_account_id,
        AccountProxyBinding.platform == data.platform,
    ).first()

    if existing:
        existing.proxy_id = data.proxy_id
        existing.is_active = True
    else:
        binding = AccountProxyBinding(
            sub_account_id=data.sub_account_id,
            proxy_id=data.proxy_id,
            platform=data.platform,
        )
        db.add(binding)

    db.commit()
    return {"message": "Proxy bound to account"}


@router.delete("/proxies/bind/{binding_id}")
def unbind_proxy(binding_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    binding = db.query(AccountProxyBinding).filter(AccountProxyBinding.id == binding_id).first()
    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")
    db.delete(binding)
    db.commit()
    return {"message": "Proxy unbound"}


# ---- IPIPGO Integration ----

@router.get("/ipipgo/orders")
async def get_ipipgo_orders(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    orders = db.query(IpipgoOrder).order_by(IpipgoOrder.id.desc()).all()
    return [
        {
            "id": o.id,
            "order_no": o.order_no,
            "product_name": o.product_name,
            "ip_address": o.ip_address,
            "port": o.port,
            "protocol": o.protocol,
            "region": o.region,
            "start_date": str(o.start_date) if o.start_date else None,
            "end_date": str(o.end_date) if o.end_date else None,
            "status": o.status,
            "days_left": o.days_left,
            "synced_at": str(o.synced_at) if o.synced_at else None,
        }
        for o in orders
    ]


@router.post("/ipipgo/sync")
async def sync_ipipgo_orders(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                IPIPGO_API_URL,
                params={"key": IPIPGO_KEY, "sign": IPIPGO_SIGN, "act": "orderlist"},
            )
            data = resp.json()

        if data.get("code") != 0 and data.get("code") != 200:
            raise HTTPException(status_code=502, detail=f"IPIPGO API error: {data.get('msg', 'Unknown error')}")

        orders = data.get("data", {}).get("list", [])
        if not isinstance(orders, list):
            orders = []

        synced = 0
        now = datetime.now(timezone.utc)
        for order in orders:
            order_no = str(order.get("order_no", ""))
            if not order_no:
                continue

            existing = db.query(IpipgoOrder).filter(IpipgoOrder.order_no == order_no).first()

            end_date_str = order.get("end_date") or order.get("expire_time")
            end_date = None
            days_left = None
            if end_date_str:
                try:
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    days_left = max(0, (end_date - now).days)
                except Exception:
                    pass

            start_date_str = order.get("start_date") or order.get("create_time")
            start_date = None
            if start_date_str:
                try:
                    start_date = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            status_val = order.get("status", "pending")
            if isinstance(status_val, int):
                status_val = {1: "active", 2: "expired", 3: "cancelled"}.get(status_val, "pending")

            if existing:
                existing.product_name = order.get("product_name", existing.product_name)
                existing.ip_address = order.get("ip") or order.get("ip_address", existing.ip_address)
                existing.port = order.get("port", existing.port)
                existing.protocol = order.get("protocol", existing.protocol)
                existing.region = order.get("region") or order.get("area", existing.region)
                existing.start_date = start_date or existing.start_date
                existing.end_date = end_date or existing.end_date
                existing.status = status_val
                existing.days_left = days_left
                existing.raw_data = order
                existing.synced_at = now
            else:
                new_order = IpipgoOrder(
                    order_no=order_no,
                    product_name=order.get("product_name"),
                    ip_address=order.get("ip") or order.get("ip_address"),
                    port=order.get("port"),
                    protocol=order.get("protocol"),
                    region=order.get("region") or order.get("area"),
                    start_date=start_date,
                    end_date=end_date,
                    status=status_val,
                    days_left=days_left,
                    raw_data=order,
                    synced_at=now,
                )
                db.add(new_order)
            synced += 1

        db.commit()
        return {"message": f"Synced {synced} IPIPGO orders", "synced": synced}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"IPIPGO sync failed: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")
