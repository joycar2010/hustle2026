"""Hedging platform management API — platforms, symbols, hedging pairs CRUD"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from typing import Dict, List, Any, Optional
from pydantic import BaseModel
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.platform import Platform, PlatformSymbol, HedgingPair
from app.models.mt5_client import MT5Client
from app.models.account import Account

router = APIRouter()


# ── Pydantic schemas ───────────────────────────────────────────────
class PlatformUpdate(BaseModel):
    display_name: Optional[str] = None
    platform_name: Optional[str] = None
    platform_type: Optional[str] = None
    api_base_url: Optional[str] = None
    ws_base_url: Optional[str] = None
    account_api_type: Optional[str] = None
    market_api_type: Optional[str] = None
    auth_type: Optional[str] = None
    position_mode: Optional[str] = None
    maker_mechanism: Optional[str] = None
    default_tif: Optional[str] = None
    base_currency: Optional[str] = None
    mt5_template_path: Optional[str] = None
    requires_proxy: Optional[bool] = None
    is_active: Optional[bool] = None


class PlatformCreate(BaseModel):
    platform_id: int
    platform_name: str
    display_name: str = ""
    platform_type: str = "cex"
    api_base_url: str = ""
    ws_base_url: str = ""
    account_api_type: str = ""
    market_api_type: str = ""
    auth_type: str = "hmac_sha256"
    position_mode: str = "hedging"
    maker_mechanism: str = "none"
    default_tif: str = "GTC"
    base_currency: str = "USDT"
    mt5_template_path: Optional[str] = None
    requires_proxy: bool = False
    is_active: bool = True


class SymbolCreate(BaseModel):
    platform_id: int
    symbol: str
    base_asset: str
    quote_asset: str = "USDT"
    contract_unit: float = 1.0
    qty_unit: str = "XAU"
    qty_precision: int = 0
    qty_step: float = 1.0
    min_qty: float = 1.0
    price_precision: int = 2
    price_step: float = 0.01
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.0005
    fee_type: str = "percentage"
    fee_per_lot: float = 0.0
    margin_rate_initial: float = 0.01
    margin_rate_maintenance: float = 0.005
    funding_interval: Optional[str] = None
    swap_type: Optional[str] = None
    trading_hours: Optional[Dict] = None
    is_active: bool = True


class SymbolUpdate(BaseModel):
    symbol: Optional[str] = None
    base_asset: Optional[str] = None
    quote_asset: Optional[str] = None
    contract_unit: Optional[float] = None
    qty_unit: Optional[str] = None
    qty_precision: Optional[int] = None
    qty_step: Optional[float] = None
    min_qty: Optional[float] = None
    price_precision: Optional[int] = None
    price_step: Optional[float] = None
    maker_fee_rate: Optional[float] = None
    taker_fee_rate: Optional[float] = None
    fee_type: Optional[str] = None
    fee_per_lot: Optional[float] = None
    margin_rate_initial: Optional[float] = None
    margin_rate_maintenance: Optional[float] = None
    funding_interval: Optional[str] = None
    swap_type: Optional[str] = None
    trading_hours: Optional[Dict] = None
    is_active: Optional[bool] = None


class PairCreate(BaseModel):
    pair_name: str
    pair_code: str
    account_a_id: Optional[str] = None
    symbol_a_id: str
    account_b_id: Optional[str] = None
    symbol_b_id: str
    conversion_factor: float = 100.0
    usd_usdt_rate: float = 1.0
    usd_usdt_auto_sync: bool = False
    spread_mode: str = "absolute"
    spread_precision: int = 2
    default_spread_target: Optional[float] = None
    max_position_value_usd: Optional[float] = None
    min_hedgeable_qty_a: Optional[float] = None
    min_hedgeable_qty_b: Optional[float] = None
    is_active: bool = True
    sort_order: int = 0


class PairUpdate(BaseModel):
    pair_name: Optional[str] = None
    account_a_id: Optional[str] = None
    symbol_a_id: Optional[str] = None
    account_b_id: Optional[str] = None
    symbol_b_id: Optional[str] = None
    conversion_factor: Optional[float] = None
    usd_usdt_rate: Optional[float] = None
    usd_usdt_auto_sync: Optional[bool] = None
    spread_mode: Optional[str] = None
    spread_precision: Optional[int] = None
    default_spread_target: Optional[float] = None
    max_position_value_usd: Optional[float] = None
    min_hedgeable_qty_a: Optional[float] = None
    min_hedgeable_qty_b: Optional[float] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


# ── Helpers ────────────────────────────────────────────────────────
def _row_to_dict(obj) -> Dict[str, Any]:
    d = {}
    for c in obj.__table__.columns:
        v = getattr(obj, c.name)
        d[c.name] = str(v) if isinstance(v, __import__('uuid').UUID) else v
    return d


# ── Platforms ──────────────────────────────────────────────────────
@router.get("/platforms")
async def list_platforms(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    import httpx as _httpx
    r = await db.execute(select(Platform).order_by(Platform.platform_id))
    platforms = r.scalars().all()

    # For each MT5 platform, find the system-service MT5 client via account.platform_id
    sys_clients_r = await db.execute(
        select(MT5Client, Account.platform_id)
        .join(Account, MT5Client.account_id == Account.account_id)
        .where(MT5Client.is_system_service == True, MT5Client.is_active == True)
    )
    # Build map: platform_id -> system client info
    sys_client_map: Dict[int, Dict] = {}
    for mc, pid in sys_clients_r.all():
        sys_client_map[pid] = {
            "client_id": mc.client_id,
            "client_name": mc.client_name,
            "bridge_url": mc.bridge_url,
            "bridge_service_port": mc.bridge_service_port,
            "connection_status": mc.connection_status,  # DB fallback
            "is_active": mc.is_active,
            "account_id": str(mc.account_id),
        }

    # Real-time health check for each MT5 client bridge (parallel, 2s timeout)
    async def _check_bridge(info: Dict) -> str:
        bridge_url = info.get("bridge_url")
        if not bridge_url:
            return "disconnected"
        try:
            async with _httpx.AsyncClient(timeout=2.0) as hc:
                resp = await hc.get(f"{bridge_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    return "connected" if data.get("mt5") else "disconnected"
        except Exception:
            pass
        return "disconnected"

    import asyncio as _asyncio
    # Run all health checks concurrently
    for pid, info in sys_client_map.items():
        info["connection_status"] = await _asyncio.wait_for(
            _check_bridge(info), timeout=3.0
        ) if info.get("bridge_url") else "disconnected"

    result = []
    for p in platforms:
        d = _row_to_dict(p)
        d["system_mt5_client"] = sys_client_map.get(p.platform_id)
        result.append(d)
    return result


@router.put("/platforms/{platform_id}")
async def update_platform(
    platform_id: int,
    body: PlatformUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    r = await db.execute(select(Platform).where(Platform.platform_id == platform_id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Platform not found")
    for k, v in body.dict(exclude_none=True).items():
        setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return _row_to_dict(p)


@router.post("/platforms")
async def create_platform(
    body: PlatformCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    existing = await db.execute(select(Platform).where(Platform.platform_id == body.platform_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Platform ID already exists")
    p = Platform(**body.dict())
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _row_to_dict(p)


@router.delete("/platforms/{platform_id}")
async def delete_platform(
    platform_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    r = await db.execute(select(Platform).where(Platform.platform_id == platform_id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Platform not found")
    sym_r = await db.execute(select(PlatformSymbol).where(PlatformSymbol.platform_id == platform_id).limit(1))
    if sym_r.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="请先删除关联品种后再删除平台")
    await db.delete(p)
    await db.commit()
    return {"message": "Platform deleted"}


# ── Platform Symbols ───────────────────────────────────────────────
@router.get("/symbols")
async def list_symbols(
    platform_id: Optional[int] = None,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    q = select(PlatformSymbol).order_by(PlatformSymbol.platform_id, PlatformSymbol.symbol)
    if platform_id is not None:
        q = q.where(PlatformSymbol.platform_id == platform_id)
    r = await db.execute(q)
    return [_row_to_dict(s) for s in r.scalars().all()]


@router.post("/symbols")
async def create_symbol(
    body: SymbolCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    s = PlatformSymbol(**body.dict())
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return _row_to_dict(s)


@router.put("/symbols/{symbol_id}")
async def update_symbol(
    symbol_id: str,
    body: SymbolUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    r = await db.execute(select(PlatformSymbol).where(PlatformSymbol.id == symbol_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Symbol not found")
    for k, v in body.dict(exclude_none=True).items():
        setattr(s, k, v)
    await db.commit()
    await db.refresh(s)
    return _row_to_dict(s)


@router.delete("/symbols/{symbol_id}")
async def delete_symbol(
    symbol_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    r = await db.execute(select(PlatformSymbol).where(PlatformSymbol.id == symbol_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Symbol not found")
    await db.delete(s)
    await db.commit()
    return {"message": "Symbol deleted"}


# ── Hedging Pairs ──────────────────────────────────────────────────
@router.get("/pairs")
async def list_pairs(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    r = await db.execute(
        select(HedgingPair).order_by(HedgingPair.sort_order, HedgingPair.pair_code)
    )
    pairs = r.scalars().all()
    result = []
    for p in pairs:
        d = _row_to_dict(p)
        # Attach symbol info
        for side in ('a', 'b'):
            sid = getattr(p, f'symbol_{side}_id')
            if sid:
                sr = await db.execute(select(PlatformSymbol).where(PlatformSymbol.id == sid))
                sym = sr.scalar_one_or_none()
                if sym:
                    d[f'symbol_{side}'] = _row_to_dict(sym)
                    # Attach platform info
                    pr = await db.execute(select(Platform).where(Platform.platform_id == sym.platform_id))
                    plat = pr.scalar_one_or_none()
                    if plat:
                        d[f'platform_{side}'] = _row_to_dict(plat)
        result.append(d)
    return result


@router.post("/pairs")
async def create_pair(
    body: PairCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    data = body.dict()
    for k in ('account_a_id', 'account_b_id', 'symbol_a_id', 'symbol_b_id'):
        if data.get(k):
            data[k] = UUID(data[k]) if isinstance(data[k], str) else data[k]
        elif k.startswith('account'):
            data[k] = None
    p = HedgingPair(**data)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _row_to_dict(p)


@router.put("/pairs/{pair_id}")
async def update_pair(
    pair_id: str,
    body: PairUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    r = await db.execute(select(HedgingPair).where(HedgingPair.id == pair_id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Pair not found")
    for k, v in body.dict(exclude_none=True).items():
        if k in ('account_a_id', 'account_b_id', 'symbol_a_id', 'symbol_b_id') and v:
            v = UUID(v) if isinstance(v, str) else v
        setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return _row_to_dict(p)


@router.delete("/pairs/{pair_id}")
async def delete_pair(
    pair_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    r = await db.execute(select(HedgingPair).where(HedgingPair.id == pair_id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Pair not found")
    await db.delete(p)
    await db.commit()
    return {"message": "Pair deleted"}
