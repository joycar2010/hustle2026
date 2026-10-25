import json
import logging
import time
import re

import redis as redis_lib
from fastapi import APIRouter, HTTPException, Request, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AiCoinConfig, CustomMonitorSymbol
from app.db.session import SessionLocal
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id
from app.services.aicoin_client import AiCoinClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])

_aicoin: AiCoinClient | None = None


class CustomMonitorCreate(BaseModel):
    spot_symbol: str = Field(min_length=2, max_length=30)
    futures_symbol: str = Field(min_length=2, max_length=30)
    display_symbol: str | None = Field(default=None, max_length=30)
    sort_order: int = Field(default=0, ge=-1000000, le=1000000)
    enabled: bool = True


_BINANCE_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,30}$")


def _normalise_monitor_symbol(value: str, field: str) -> str:
    raw = str(value or "").strip().upper().replace("/", "").replace("_", "").replace("-", "")
    if not raw.endswith("USDT"):
        raw += "USDT"
    asset = raw[:-4]
    if not _BINANCE_SYMBOL_RE.fullmatch(raw) or not asset or asset == "USDT":
        raise HTTPException(status_code=422, detail=f"Invalid {field}: Binance USDT symbol required")
    return raw


def _custom_monitor_response(row: CustomMonitorSymbol) -> dict:
    return {
        "id": row.id, "user_id": row.user_id,
        "spot_symbol": row.spot_symbol, "futures_symbol": row.futures_symbol,
        "display_symbol": row.display_symbol or row.spot_symbol.removesuffix("USDT"),
        "enabled": bool(row.is_active and not row.is_removed),
        "is_active": bool(row.is_active), "is_removed": bool(row.is_removed),
        "sort_order": int(row.sort_order or 0), "created_at": row.created_at, "updated_at": row.updated_at,
    }


@router.get("/custom-monitors")
def list_custom_monitors(request: Request, include_removed: bool = False, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    query = db.query(CustomMonitorSymbol).filter(CustomMonitorSymbol.user_id == user_id)
    if not include_removed:
        query = query.filter(CustomMonitorSymbol.is_active.is_(True), CustomMonitorSymbol.is_removed.is_(False))
    rows = query.order_by(CustomMonitorSymbol.sort_order, CustomMonitorSymbol.id).all()
    return {"items": [_custom_monitor_response(row) for row in rows], "total": len(rows)}


@router.post("/custom-monitors", status_code=status.HTTP_201_CREATED)
def create_custom_monitor(payload: CustomMonitorCreate, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    spot = _normalise_monitor_symbol(payload.spot_symbol, "spot_symbol")
    futures = _normalise_monitor_symbol(payload.futures_symbol, "futures_symbol")
    if spot == futures:
        raise HTTPException(status_code=422, detail="spot_symbol and futures_symbol must differ")
    display = (payload.display_symbol or spot.removesuffix("USDT")).strip().upper()
    row = db.query(CustomMonitorSymbol).filter_by(user_id=user_id, spot_symbol=spot, futures_symbol=futures).first()
    if row is None:
        row = CustomMonitorSymbol(user_id=user_id, spot_symbol=spot, futures_symbol=futures, display_symbol=display, sort_order=payload.sort_order, is_active=payload.enabled, is_removed=False)
        db.add(row)
    else:
        row.display_symbol, row.sort_order, row.is_active, row.is_removed = display, payload.sort_order, payload.enabled, False
    try:
        db.commit(); db.refresh(row)
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail="Custom monitor mapping already exists") from exc
    return _custom_monitor_response(row)


@router.delete("/custom-monitors/{monitor_id}")
def remove_custom_monitor(monitor_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    row = db.query(CustomMonitorSymbol).filter_by(id=monitor_id, user_id=user_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Custom monitor not found")
    row.is_active, row.is_removed = False, True
    db.commit()
    return {"message": "Custom monitor removed", "id": row.id}


def _reset_aicoin():
    global _aicoin
    _aicoin = None


def _get_aicoin() -> AiCoinClient:
    global _aicoin
    if _aicoin is None:
        api_key = ""
        api_secret = ""
        try:
            db = SessionLocal()
            cfg = db.query(AiCoinConfig).first()
            if cfg and cfg.api_key:
                api_key = cfg.api_key
                api_secret = cfg.api_secret or ""
            db.close()
        except Exception:
            pass
        if not api_key:
            api_key = settings.aicoin_api_key
            api_secret = settings.aicoin_api_secret
        if not api_key:
            raise HTTPException(status_code=500, detail="AiCoin API key not configured")
        _aicoin = AiCoinClient(api_key, api_secret)
    return _aicoin


def _redis():
    return redis_lib.from_url(settings.redis_url, socket_connect_timeout=2, decode_responses=True)


def _safe_float(val, default=0.0) -> float:
    if not val or val == "-":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ─── K-Line ───

_PERIOD_TO_SECONDS = {"1": "60", "5": "300", "15": "900", "30": "1800",
                      "60": "3600", "240": "14400", "1440": "86400"}


@router.get("/kline")
async def get_kline(symbol: str, period: str = "60", size: int = 200, request: Request = None):
    get_current_user_id(request)
    ac = _get_aicoin()
    api_period = _PERIOD_TO_SECONDS.get(period, period)
    try:
        data = await ac.get_kline(symbol, api_period, size)
        return {"data": data}
    except Exception as e:
        logger.warning(f"AiCoin kline error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")


# ─── Coin Search ───

@router.get("/coin-search")
async def search_coin(q: str, request: Request = None):
    get_current_user_id(request)
    ac = _get_aicoin()
    try:
        data = await ac.search_coin(q)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"AiCoin search error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")


# ─── Rankings (shares cache with admin endpoint) ───

def _compute_5min_changes(r, price_map: dict[str, float]) -> dict[str, float]:
    import math
    now_bucket = int(time.time()) // 300
    prev_bucket = now_bucket - 1
    prev_key = f"aicoin:prices:{prev_bucket}"
    curr_key = f"aicoin:prices:{now_bucket}"

    r.hset(curr_key, mapping={k: str(v) for k, v in price_map.items()})
    r.expire(curr_key, 600)

    prev_prices = r.hgetall(prev_key)
    changes = {}
    for coin_key, cur_price in price_map.items():
        prev_str = prev_prices.get(coin_key)
        if prev_str and cur_price > 0:
            prev_price = float(prev_str)
            if prev_price > 0:
                pct = ((cur_price - prev_price) / prev_price) * 100
                if not math.isnan(pct) and not math.isinf(pct):
                    changes[coin_key] = round(pct, 4)
    return changes


def _update_history_scores(r, gainers_24h: list[dict]) -> list[dict]:
    key = "aicoin:history_scores"
    for i, item in enumerate(gainers_24h[:20]):
        score = 5 if i == 0 else (3 if i < 5 else 1)
        r.zincrby(key, score, item["symbol"])
    raw = r.zrevrange(key, 0, 19, withscores=True)
    return [{"symbol": sym, "score": int(sc)} for sym, sc in raw]


@router.get("/rankings")
async def get_rankings(request: Request):
    get_current_user_id(request)
    try:
        r = _redis()
        cached = r.get("aicoin:rankings")
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    ac = _get_aicoin()
    try:
        coin_list = await ac.get_coin_list()
        coin_map = {}
        for c in coin_list:
            coin_map[c.get("coin_key", "")] = c.get("show", c.get("coin_key", "").upper())

        keys = [c.get("coin_key", "") for c in coin_list if c.get("coin_key")]
        if not keys:
            return {"gainers": [], "losers": [], "gainers_5min": [], "historical": []}

        ticker_data = await ac.get_coin_ticker(",".join(keys))

        items = []
        price_map = {}
        for info in ticker_data:
            if not isinstance(info, dict):
                continue
            coin_key = info.get("coin_key", "")
            change_24h = _safe_float(info.get("degree_24h_usd") or info.get("degree_24h_cny"))
            change_7d = _safe_float(info.get("degree_7day_usd") or info.get("degree_7day_cny"))
            price = _safe_float(info.get("price_usd") or info.get("price_cny"))
            vol = _safe_float(info.get("vol_24h") or info.get("trade_24h_usd"))
            if not coin_key or price == 0:
                continue

            symbol = coin_map.get(coin_key, coin_key.upper())
            price_map[coin_key] = price
            items.append({
                "symbol": symbol,
                "coin_key": coin_key,
                "price": price,
                "change_24h": change_24h,
                "change_7d": change_7d,
                "vol_24h": vol,
            })

        gainers = sorted(items, key=lambda x: x["change_24h"], reverse=True)[:20]
        losers = sorted(items, key=lambda x: x["change_24h"])[:20]

        gainers_5min = []
        historical = []
        try:
            r = _redis()
            changes_5m = _compute_5min_changes(r, price_map)
            if changes_5m:
                items_5m = []
                for it in items:
                    ch = changes_5m.get(it["coin_key"])
                    if ch is not None:
                        items_5m.append({**it, "change_5min": ch})
                gainers_5min = sorted(items_5m, key=lambda x: x["change_5min"], reverse=True)[:20]
            historical = _update_history_scores(r, gainers)
        except Exception as exc:
            logger.warning(f"Redis history/5min error: {exc}")

        result = {
            "gainers": gainers,
            "losers": losers,
            "gainers_5min": gainers_5min,
            "historical": historical,
        }
        try:
            r = _redis()
            r.setex("aicoin:rankings", 30, json.dumps(result))
        except Exception:
            pass
        return result
    except Exception as e:
        logger.warning(f"AiCoin rankings error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")
