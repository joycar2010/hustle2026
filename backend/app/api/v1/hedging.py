"""Hedging platform management API — platforms, symbols, hedging pairs CRUD"""
import httpx
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
    product_type: Optional[str] = "perpetual"


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
    product_type: Optional[str] = None


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


# ── Symbol metadata fetch from platform API ────────────────────────
# Pulls precision/step/fees from the exchange's public instrument endpoint so
# the admin form can auto-fill fields instead of hand-entering. Supported:
#   binance  (perpetual|futures|spot)
#   bybit    (perpetual=linear | futures=inverse | spot)
#   gateio   (perpetual | spot)
#   okx      (perpetual=SWAP | futures=FUTURES | spot=SPOT)
# icmarkets / MT5: fetched from MT5 bridge elsewhere — not handled here.
class FetchSymbolMetaReq(BaseModel):
    platform_id: int
    symbol: str
    product_type: str = "perpetual"   # perpetual|futures|spot|mt5


def _num_precision(step: float) -> int:
    """Derive decimal precision from a step/tick string like 0.001 → 3."""
    if step is None:
        return 0
    ss = f"{float(step):.20f}".rstrip("0").rstrip(".")
    if "." in ss:
        return len(ss.split(".")[1])
    return 0


@router.post("/symbols/fetch-from-platform")
async def fetch_symbol_from_platform(
    req: FetchSymbolMetaReq,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    plat = (await db.execute(select(Platform).where(Platform.platform_id == req.platform_id))).scalar_one_or_none()
    if not plat:
        raise HTTPException(status_code=404, detail="平台不存在")
    name = (plat.platform_name or "").lower()
    sym_raw = (req.symbol or "").strip()
    if not sym_raw:
        raise HTTPException(status_code=400, detail="请先填写符号")
    sym = sym_raw.upper()
    pt = (req.product_type or "perpetual").lower()

    # Proxy (optional) — reuse what accounts use
    proxy = None
    try:
        from app.core.proxy_utils import build_proxy_url
        if getattr(plat, "proxy_config", None):
            proxy = build_proxy_url(plat.proxy_config)
    except Exception:
        proxy = None

    timeout = httpx.Timeout(15.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, proxy=proxy, follow_redirects=True) as cli:
        try:
            if name == "binance":
                if pt in ("perpetual", "futures"):
                    r = await cli.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
                    r.raise_for_status()
                    info = r.json()
                    s_row = next((x for x in info.get("symbols", []) if x.get("symbol") == sym), None)
                    if not s_row:
                        raise HTTPException(status_code=404, detail=f"币安永续未找到 {sym}")
                    filters = {f["filterType"]: f for f in s_row.get("filters", [])}
                    lot = filters.get("LOT_SIZE", {})
                    pf = filters.get("PRICE_FILTER", {})
                    qty_step = float(lot.get("stepSize", 0)) or 0.001
                    price_step = float(pf.get("tickSize", 0)) or 0.01
                    return {
                        "base_asset": s_row.get("baseAsset") or "",
                        "quote_asset": s_row.get("quoteAsset") or "USDT",
                        "contract_unit": 1,
                        "qty_unit": s_row.get("baseAsset") or "",
                        "qty_precision": int(s_row.get("quantityPrecision", _num_precision(qty_step))),
                        "qty_step": qty_step,
                        "min_qty": float(lot.get("minQty", qty_step)),
                        "price_precision": int(s_row.get("pricePrecision", _num_precision(price_step))),
                        "price_step": price_step,
                        "maker_fee_rate": 0.0002,
                        "taker_fee_rate": 0.0005,
                        "margin_rate_initial": float(s_row.get("requiredMarginPercent", 5) or 5) / 100.0,
                        "product_type": "perpetual" if "PERPETUAL" in (s_row.get("contractType") or "") else "futures",
                    }
                elif pt == "spot":
                    r = await cli.get("https://api.binance.com/api/v3/exchangeInfo", params={"symbol": sym})
                    r.raise_for_status()
                    info = r.json()
                    s_row = next((x for x in info.get("symbols", []) if x.get("symbol") == sym), None)
                    if not s_row:
                        raise HTTPException(status_code=404, detail=f"币安现货未找到 {sym}")
                    filters = {f["filterType"]: f for f in s_row.get("filters", [])}
                    lot = filters.get("LOT_SIZE", {})
                    pf = filters.get("PRICE_FILTER", {})
                    qty_step = float(lot.get("stepSize", 0)) or 0.00001
                    price_step = float(pf.get("tickSize", 0)) or 0.01
                    return {
                        "base_asset": s_row.get("baseAsset"),
                        "quote_asset": s_row.get("quoteAsset"),
                        "contract_unit": 1,
                        "qty_unit": s_row.get("baseAsset"),
                        "qty_precision": int(s_row.get("baseAssetPrecision", _num_precision(qty_step))),
                        "qty_step": qty_step,
                        "min_qty": float(lot.get("minQty", qty_step)),
                        "price_precision": int(s_row.get("quoteAssetPrecision", _num_precision(price_step))),
                        "price_step": price_step,
                        "maker_fee_rate": 0.001,
                        "taker_fee_rate": 0.001,
                        "margin_rate_initial": 1.0,
                        "product_type": "spot",
                    }

            if name == "bybit":
                cat = {"perpetual": "linear", "futures": "inverse", "spot": "spot"}.get(pt, "linear")
                r = await cli.get("https://api.bybit.com/v5/market/instruments-info",
                                  params={"category": cat, "symbol": sym})
                r.raise_for_status()
                data = r.json()
                arr = data.get("result", {}).get("list", []) or []
                if not arr:
                    raise HTTPException(status_code=404, detail=f"Bybit({cat}) 未找到 {sym}")
                it = arr[0]
                lot = it.get("lotSizeFilter", {}) or {}
                pf = it.get("priceFilter", {}) or {}
                qty_step = float(lot.get("qtyStep") or lot.get("basePrecision") or 0.001)
                price_step = float(pf.get("tickSize") or 0.01)
                min_qty = float(lot.get("minOrderQty") or lot.get("minTrdAmt") or qty_step)
                return {
                    "base_asset": it.get("baseCoin") or "",
                    "quote_asset": it.get("quoteCoin") or "USDT",
                    "contract_unit": 1,
                    "qty_unit": it.get("baseCoin") or "",
                    "qty_precision": _num_precision(qty_step),
                    "qty_step": qty_step,
                    "min_qty": min_qty,
                    "price_precision": _num_precision(price_step),
                    "price_step": price_step,
                    "maker_fee_rate": 0.0001 if cat != "spot" else 0.001,
                    "taker_fee_rate": 0.0006 if cat != "spot" else 0.001,
                    "margin_rate_initial": 0.05 if cat != "spot" else 1.0,
                    "product_type": "spot" if cat == "spot" else ("futures" if cat == "inverse" else "perpetual"),
                }

            if name == "gateio":
                if pt == "perpetual":
                    # USDT-settled perp
                    settle = "usdt"
                    r = await cli.get(f"https://api.gateio.ws/api/v4/futures/{settle}/contracts/{sym_raw}")
                    r.raise_for_status()
                    it = r.json()
                    qty_step = float(it.get("order_size_min") or 1)  # Gate perp is integer contracts
                    price_step = float(it.get("order_price_round") or 0.01)
                    contract_unit = float(it.get("quanto_multiplier") or 1)
                    base = (it.get("name") or "").split("_")[0]
                    quote = (it.get("name") or "").split("_")[-1] or "USDT"
                    return {
                        "base_asset": base,
                        "quote_asset": quote,
                        "contract_unit": contract_unit,
                        "qty_unit": "Cont",
                        "qty_precision": 0,
                        "qty_step": qty_step,
                        "min_qty": qty_step,
                        "price_precision": _num_precision(price_step),
                        "price_step": price_step,
                        "maker_fee_rate": float(it.get("maker_fee_rate") or 0.00015),
                        "taker_fee_rate": float(it.get("taker_fee_rate") or 0.0005),
                        "margin_rate_initial": float(it.get("leverage_min") and (1.0 / float(it["leverage_max"] or 50)) or 0.02),
                        "product_type": "perpetual",
                    }
                elif pt == "spot":
                    r = await cli.get(f"https://api.gateio.ws/api/v4/spot/currency_pairs/{sym_raw}")
                    r.raise_for_status()
                    it = r.json()
                    price_prec = int(it.get("precision", 6))
                    qty_prec = int(it.get("amount_precision", 6))
                    qty_step = 10 ** (-qty_prec)
                    price_step = 10 ** (-price_prec)
                    return {
                        "base_asset": it.get("base"),
                        "quote_asset": it.get("quote"),
                        "contract_unit": 1,
                        "qty_unit": it.get("base"),
                        "qty_precision": qty_prec,
                        "qty_step": qty_step,
                        "min_qty": float(it.get("min_base_amount") or qty_step),
                        "price_precision": price_prec,
                        "price_step": price_step,
                        "maker_fee_rate": float(it.get("fee") or 0.002) / 100.0,
                        "taker_fee_rate": float(it.get("fee") or 0.002) / 100.0,
                        "margin_rate_initial": 1.0,
                        "product_type": "spot",
                    }

            if name == "okx":
                inst_type = {"perpetual": "SWAP", "futures": "FUTURES", "spot": "SPOT"}.get(pt, "SWAP")
                r = await cli.get("https://www.okx.com/api/v5/public/instruments",
                                  params={"instType": inst_type, "instId": sym_raw})
                r.raise_for_status()
                arr = r.json().get("data", []) or []
                if not arr:
                    raise HTTPException(status_code=404, detail=f"OKX({inst_type}) 未找到 {sym_raw}")
                it = arr[0]
                qty_step = float(it.get("lotSz") or 1)
                price_step = float(it.get("tickSz") or 0.01)
                contract_unit = float(it.get("ctVal") or 1)
                return {
                    "base_asset": it.get("baseCcy") or it.get("ctValCcy") or "",
                    "quote_asset": it.get("quoteCcy") or it.get("settleCcy") or "USDT",
                    "contract_unit": contract_unit,
                    "qty_unit": it.get("ctValCcy") or it.get("baseCcy") or "Cont",
                    "qty_precision": _num_precision(qty_step),
                    "qty_step": qty_step,
                    "min_qty": float(it.get("minSz") or qty_step),
                    "price_precision": _num_precision(price_step),
                    "price_step": price_step,
                    "maker_fee_rate": 0.0002,
                    "taker_fee_rate": 0.0005,
                    "margin_rate_initial": 1.0 / float(it.get("lever") or 50) if it.get("lever") else 0.02,
                    "product_type": "perpetual" if inst_type == "SWAP" else ("futures" if inst_type == "FUTURES" else "spot"),
                }

            raise HTTPException(status_code=400, detail=f"平台 {plat.platform_name} 暂不支持自动拉取，请手动填写（MT5/IC Markets 可在 MT5 终端查询）")

        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"交易所 API 返回 {e.response.status_code}：{e.response.text[:200]}")
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"请求交易所失败：{e}")


# ── Batch import: fetch + upsert directly into platform_symbols ──────
class ImportSymbolsReq(BaseModel):
    platform_id: int
    product_type: str = "perpetual"
    symbols: List[str]  # one or many


@router.post("/symbols/import-from-platform")
async def import_symbols_from_platform(
    req: ImportSymbolsReq,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Fetch instrument metadata from the exchange and UPSERT into
    platform_symbols — the one-click 导入 flow replacing manual entry.

    Returns {imported: [...], skipped: [...], errors: {sym: msg}}.
    """
    if not req.symbols:
        raise HTTPException(status_code=400, detail="请至少提供一个符号")

    imported: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    for raw in req.symbols:
        sym = (raw or "").strip()
        if not sym:
            continue
        try:
            meta = await fetch_symbol_from_platform(
                FetchSymbolMetaReq(platform_id=req.platform_id, symbol=sym, product_type=req.product_type),
                user_id=user_id, db=db,
            )
        except HTTPException as he:
            errors[sym] = str(he.detail)
            continue
        except Exception as e:
            errors[sym] = str(e)
            continue

        # Upsert — match by (platform_id, symbol)
        existing = (await db.execute(
            select(PlatformSymbol).where(
                PlatformSymbol.platform_id == req.platform_id,
                PlatformSymbol.symbol == sym,
            )
        )).scalar_one_or_none()

        fields = {
            "platform_id": req.platform_id,
            "symbol": sym,
            "base_asset": meta.get("base_asset") or "",
            "quote_asset": meta.get("quote_asset") or "USDT",
            "contract_unit": meta.get("contract_unit") or 1,
            "qty_unit": meta.get("qty_unit") or "",
            "qty_precision": int(meta.get("qty_precision") or 0),
            "qty_step": meta.get("qty_step") or 0,
            "min_qty": meta.get("min_qty") or 0,
            "price_precision": int(meta.get("price_precision") or 0),
            "price_step": meta.get("price_step") or 0,
            "maker_fee_rate": meta.get("maker_fee_rate") or 0,
            "taker_fee_rate": meta.get("taker_fee_rate") or 0,
            "margin_rate_initial": meta.get("margin_rate_initial") or 0,
            "product_type": meta.get("product_type") or req.product_type,
            "is_active": True,
        }

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            await db.commit()
            await db.refresh(existing)
            imported.append({**_row_to_dict(existing), "_action": "updated"})
        else:
            row = PlatformSymbol(**fields)
            db.add(row)
            await db.commit()
            await db.refresh(row)
            imported.append({**_row_to_dict(row), "_action": "created"})

    return {"imported": imported, "errors": errors, "total": len(imported)}


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
