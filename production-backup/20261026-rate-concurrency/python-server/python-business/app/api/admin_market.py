import json
import logging
import time

import httpx
import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Blacklist,
    PendingBlacklist,
    GlobalRules,
    DelistingMonitorConfig,
)
from app.db.models_auth import User
from app.db.session import get_db
from app.middleware.permissions import require_admin
from app.services.aicoin_client import AiCoinClient
from app.services.aicoin_config import resolve_aicoin_credentials, redact_aicoin_error
from app.services.binance_cms import BinanceCmsError, fetch_articles_sync
from engine.fund.delisting_scanner import (
    extract_symbols,
    matches_delisting_keywords,
    scan_delisting_sources,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/market", tags=["admin-market"])

_aicoin: AiCoinClient | None = None

_PERIOD_TO_SECONDS = {"1": "60", "5": "300", "15": "900", "30": "1800",
                      "60": "3600", "240": "14400", "1440": "86400"}


def _reset_aicoin() -> None:
    """Drop the cached client after an admin credential update."""
    global _aicoin
    _aicoin = None


def _get_aicoin() -> AiCoinClient:
    global _aicoin
    if _aicoin is None:
        credentials = resolve_aicoin_credentials()
        if not credentials.api_key or not credentials.api_secret:
            raise HTTPException(
                status_code=503,
                detail="AiCoin API Key/Secret not configured",
            )
        _aicoin = AiCoinClient(credentials.api_key, credentials.api_secret)
    return _aicoin


def _redis():
    return redis_lib.from_url(settings.redis_url, socket_connect_timeout=2, decode_responses=True)


@router.get("/net-expect")
def net_expect_board(request: Request):
    """净期望收益 E 榜(P0-1):扫所有用户的 engine:{uid}:neteval:{SYMBOL} Redis 键(60s TTL,
    引擎每次开仓评估写入),聚合成榜供 coinadmin market-monitor 展示——哪些币 E>0 可做、哪些被
    成本吃成负、成本线由点差捕获/利息/手续费/摩擦四项构成。shadow 模式下能直接看到"若开会亏多少"。"""
    require_admin(request)
    try:
        r = _redis()
        rows = []
        for key in r.scan_iter("engine:*:neteval:*", count=500):
            try:
                parts = key.split(":")
                uid = int(parts[1]); sym = parts[3]
                d = json.loads(r.get(key) or "{}")
                if not d:
                    continue
                rows.append({
                    "user_id": uid, "symbol": sym,
                    "E": d.get("E"), "notional_usdt": d.get("notional_usdt"),
                    "spread_capture": d.get("spread_capture"), "interest_cost": d.get("interest_cost"),
                    "fee_cost": d.get("fee_cost"), "tick_cost": d.get("tick_cost"),
                    "funding_expect": d.get("funding_expect"),
                    "decision": d.get("decision"), "gate_mode": d.get("gate_mode"),
                    "ts": d.get("ts"),
                })
            except Exception:
                continue
        rows.sort(key=lambda x: (x.get("E") if x.get("E") is not None else -1e9), reverse=True)
        gate_mode = rows[0]["gate_mode"] if rows else None
        return {
            "rows": rows,
            "count": len(rows),
            "positive": sum(1 for x in rows if (x.get("E") or 0) > 0),
            "negative": sum(1 for x in rows if (x.get("E") or 0) <= 0),
            "gate_mode": gate_mode,
        }
    except Exception as e:
        logger.warning(f"net-expect board error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ConfirmBlacklistRequest(BaseModel):
    symbol: str
    reason: str | None = None


class DelistingConfigUpdate(BaseModel):
    enabled: bool | None = None
    interval_sec: int | None = None
    telegram_enabled: bool | None = None
    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None
    telegram_session: str | None = None
    telegram_chat: str | None = None


def _get_delisting_config(db: Session) -> DelistingMonitorConfig:
    config = db.query(DelistingMonitorConfig).filter(DelistingMonitorConfig.id == 1).first()
    if config is None:
        config = DelistingMonitorConfig(id=1, enabled=True, interval_sec=30, telegram_enabled=False)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def _delisting_config_response(config: DelistingMonitorConfig) -> dict:
    return {
        "id": config.id,
        "enabled": bool(config.enabled),
        # The scheduler is intentionally bounded to the requested 30-second
        # cadence; values below 30 are never accepted by the API.
        "interval_sec": max(30, int(config.interval_sec or 30)),
        "telegram_enabled": bool(config.telegram_enabled),
        "telegram_api_id_configured": bool(config.telegram_api_id),
        "telegram_api_hash_configured": bool(config.telegram_api_hash),
        "telegram_session_configured": bool(config.telegram_session),
        "telegram_chat": config.telegram_chat,
        "last_scan_at": config.last_scan_at.isoformat() if config.last_scan_at else None,
        "last_error": config.last_error,
    }


@router.get("/delisting-config")
def get_delisting_config(request: Request, db: Session = Depends(get_db)):
    """Return redacted source settings; secret material is never serialized."""
    require_admin(request)
    return _delisting_config_response(_get_delisting_config(db))


@router.put("/delisting-config")
def update_delisting_config(
    payload: DelistingConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update the optional Telegram source using encrypted model fields.

    Password/phone fields are intentionally absent from the schema.  Empty
    secret values clear a setting; omitted values preserve the previous
    encrypted value.
    """
    require_admin(request)
    config = _get_delisting_config(db)
    values = payload.model_dump(exclude_unset=True)
    secret_fields = {"telegram_api_id", "telegram_api_hash", "telegram_session"}
    if any(field in values and str(values[field] or "").strip() for field in secret_fields) and not settings.encryption_key:
        raise HTTPException(
            status_code=503,
            detail="CEX_ENCRYPTION_KEY is required before storing Telegram credentials",
        )
    if "interval_sec" in values:
        values["interval_sec"] = max(30, min(int(values["interval_sec"] or 30), 3600))
    for field, value in values.items():
        if field in {"telegram_api_id", "telegram_api_hash", "telegram_session"}:
            value = str(value).strip() or None
        if field == "telegram_chat" and value is not None:
            value = str(value).strip() or None
        setattr(config, field, value)
    # Enabling Telegram without all credentials would make the monitor appear
    # healthy while silently doing nothing, so reject it explicitly.
    if config.telegram_enabled and not all((
        config.telegram_api_id,
        config.telegram_api_hash,
        config.telegram_session,
        config.telegram_chat,
    )):
        raise HTTPException(
            status_code=422,
            detail="Telegram requires API ID, API hash, authorized session, and chat; no password is accepted",
        )
    db.commit()
    db.refresh(config)
    return _delisting_config_response(config)


@router.post("/delisting-scan")
async def trigger_delisting_scan(request: Request):
    """Run the same CMS+Telegram pipeline used by the Worker."""
    require_admin(request)
    flagged = await scan_delisting_sources()
    return {"found": flagged, "count": len(flagged)}


# ─── Binance Announcement Scraping ───

@router.get("/announcements")
def get_announcements(request: Request):
    require_admin(request)
    try:
        articles = fetch_articles_sync(page_size=20)
        result = []
        for a in articles:
            title = a.get("title", "")
            is_delist = matches_delisting_keywords(
                " ".join(str(a.get(key) or "") for key in ("title", "content", "description", "summary"))
            )
            result.append({
                "id": a.get("id"),
                "title": title,
                "url": f"https://www.binance.com/zh-CN/support/announcement/{a.get('code', '')}",
                "release_date": a.get("releaseDate"),
                "is_delist": is_delist,
            })
        return result
    except BinanceCmsError as e:
        logger.warning("Binance CMS announcement fetch failed: %s", e)
        return {"error": str(e), "articles": []}
    except Exception as e:
        logger.exception("Unexpected announcement response error")
        return {"error": str(e), "articles": []}


@router.post("/check-delist")
async def check_delist(request: Request):
    """Backward-compatible alias for the unified immediate safety scan."""
    require_admin(request)
    try:
        found = await scan_delisting_sources()
        return {"found": found, "count": len(found)}
    except Exception as e:
        logger.exception("Unexpected delisting response error")
        return {"error": str(e), "found": [], "count": 0}


def _extract_symbols(title: str) -> list[str]:
    """Extract trading pair symbols from announcement title."""
    return sorted(extract_symbols(title))


# ─── Pending Blacklist Management ───

@router.get("/blacklist-pending")
def list_pending(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    items = db.query(PendingBlacklist).filter(
        PendingBlacklist.is_confirmed == False,
    ).order_by(PendingBlacklist.created_at.desc()).all()
    return [
        {
            "id": i.id,
            "symbol": i.symbol,
            "reason": i.reason,
            "source": i.source,
            "announcement_title": i.announcement_title,
            "announcement_url": i.announcement_url,
            "source_event_id": i.source_event_id,
            "created_at": str(i.created_at) if i.created_at else None,
        }
        for i in items
    ]


@router.post("/blacklist-confirm/{item_id}")
def confirm_blacklist(item_id: int, request: Request, db: Session = Depends(get_db)):
    """Confirm a pending blacklist item and distribute to all active users."""
    require_admin(request)

    item = db.query(PendingBlacklist).filter(PendingBlacklist.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.is_confirmed = True
    item.confirmed_by = getattr(request.state, "user_id", None)

    users = db.query(User).filter(User.is_active == True).all()
    distributed = 0
    for u in users:
        existing = db.query(Blacklist).filter(
            Blacklist.user_id == u.id,
            Blacklist.symbol == item.symbol,
        ).first()
        if not existing:
            bl = Blacklist(
                user_id=u.id,
                symbol=item.symbol,
                reason=item.reason or "Binance delisting",
            )
            db.add(bl)
            distributed += 1

    db.commit()
    return {"message": f"Blacklisted {item.symbol} for {distributed} users", "distributed": distributed}


@router.delete("/blacklist-pending/{item_id}")
def dismiss_pending(item_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    item = db.query(PendingBlacklist).filter(PendingBlacklist.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    db.commit()
    return {"message": "Dismissed"}


# ─── AiCoin K-Line ───

@router.get("/kline")
async def get_kline(symbol: str, period: str = "60", size: int = 200, request: Request = None):
    require_admin(request)
    ac = _get_aicoin()
    api_period = _PERIOD_TO_SECONDS.get(period, period)
    try:
        data = await ac.get_kline(symbol, api_period, size)
        return {"data": data}
    except Exception as e:
        logger.warning(f"AiCoin kline error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {redact_aicoin_error(e)}")


# ─── AiCoin Coin Search ───

@router.get("/coin-search")
async def search_coin(q: str, request: Request = None):
    require_admin(request)
    ac = _get_aicoin()
    try:
        data = await ac.search_coin(q)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"AiCoin search error: {e}")
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {redact_aicoin_error(e)}")


# ─── AiCoin Rankings (cached 30s) + 5min change + history scores ───

def _safe_float(val, default=0.0) -> float:
    if not val or val == "-":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _compute_5min_changes(r, price_map: dict[str, float]) -> dict[str, float]:
    """Compare current prices to snapshot from ~5 min ago. Store current snapshot."""
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
    """Accumulate scores: #1 gets +5, top5 get +3, top20 get +1. Return top 20."""
    key = "aicoin:history_scores"
    for i, item in enumerate(gainers_24h[:20]):
        score = 5 if i == 0 else (3 if i < 5 else 1)
        r.zincrby(key, score, item["symbol"])
    raw = r.zrevrange(key, 0, 19, withscores=True)
    return [{"symbol": sym, "score": int(sc)} for sym, sc in raw]


@router.get("/rankings")
async def get_rankings(request: Request):
    require_admin(request)
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
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {redact_aicoin_error(e)}")


@router.delete("/rankings/history")
def reset_history_scores(request: Request):
    require_admin(request)
    try:
        r = _redis()
        r.delete("aicoin:history_scores")
        return {"message": "History scores reset"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── P2-a 跨所标尺(OKX/Bybit 公共行情,只读参照,绝不做腿) ───

_VENUE_CACHE_TTL = 60


async def _fetch_json(cli, url, params=None):
    resp = await cli.get(url, params=params)
    return resp.json()


@router.get("/cross-venue")
async def cross_venue_ruler(request: Request, top: int = 60):
    """跨所标尺(P2):并排对比 Binance / OKX / Bybit / Gate / Bitget 五所同币的现货买卖价差
    + 四所合约资金费(OKX 资金费仅逐合约端点,按需标尺省略)。纯参照标尺,不做任何下单腿。
    资金费全部按【结算周期】归一化成日化%(币安部分币4h/Bybit有1h·2h·4h/Gate按秒/Bitget按小时,
    不归一化跨所对比会差2~8倍——xv采样器同款命门);费差=四所日化最高−最低(最优对)+方向。
    全走公共行情免鉴权,批量端点并发拉(~9次调用),60s redis 缓存,打开页面才算、不常驻轮询。"""
    require_admin(request)
    r = _redis()
    cached = r.get("crossvenue:ruler:v2")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    import asyncio as _aio
    errors = []

    async def _safe(name, coro, default):
        try:
            return await coro
        except Exception as e:
            errors.append(f"{name}:{e}")
            return default

    async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "Mozilla/5.0"}) as cli:
        async def bn_spot_f():
            # Binance Spot prices are already supplied by the Rust Binance WS
            # engine.  Keep this read-only comparison page off public ticker
            # REST so it cannot compete with signed account/trading calls.
            from engine.trading.market_ws import get_all_ws_book_tickers
            quotes = await get_all_ws_book_tickers("spot", max_age_ms=60_000)
            return {s: (_safe_float(t.get("bidPrice")), _safe_float(t.get("askPrice")))
                    for s, t in quotes.items()
                    if s.endswith("USDT") and _safe_float(t.get("bidPrice")) > 0
                    and _safe_float(t.get("askPrice")) > 0}

        async def bn_fund_f():
            # premiumIndex 每期费率 + fundingInfo 例外结算周期(缺省8h) → 日化%
            intervals = {}
            try:
                for x in await _fetch_json(cli, "https://fapi.binance.com/fapi/v1/fundingInfo"):
                    if isinstance(x, dict) and x.get("symbol"):
                        intervals[x["symbol"]] = _safe_float(x.get("fundingIntervalHours"), 8) or 8
            except Exception as e:
                errors.append(f"binance_fundinfo:{e}")
            out = {}
            for t in await _fetch_json(cli, "https://fapi.binance.com/fapi/v1/premiumIndex"):
                s = t.get("symbol", "")
                if s.endswith("USDT") and "_" not in s:
                    out[s] = _safe_float(t.get("lastFundingRate")) * (24 / intervals.get(s, 8)) * 100
            return out

        async def okx_spot_f():
            out = {}
            d = await _fetch_json(cli, "https://www.okx.com/api/v5/market/tickers", {"instType": "SPOT"})
            for t in d.get("data", []):
                inst = t.get("instId", "")
                if inst.endswith("-USDT"):
                    bid = _safe_float(t.get("bidPx")); ask = _safe_float(t.get("askPx"))
                    if bid > 0 and ask > 0:
                        out[inst.replace("-", "")] = (bid, ask)
            return out

        async def bb_spot_f():
            out = {}
            d = await _fetch_json(cli, "https://api.bybit.com/v5/market/tickers", {"category": "spot"})
            for t in d.get("result", {}).get("list", []):
                s = t.get("symbol", "")
                if s.endswith("USDT"):
                    bid = _safe_float(t.get("bid1Price")); ask = _safe_float(t.get("ask1Price"))
                    if bid > 0 and ask > 0:
                        out[s] = (bid, ask)
            return out

        async def bb_fund_f():
            # linear tickers 每期费率 + instruments-info 结算周期(分钟,缺省480) → 日化%
            intervals = {}
            try:
                cursor = ""
                for _ in range(6):
                    params = {"category": "linear", "limit": "1000"}
                    if cursor:
                        params["cursor"] = cursor
                    d = await _fetch_json(cli, "https://api.bybit.com/v5/market/instruments-info", params)
                    res = d.get("result", {})
                    for it in res.get("list", []):
                        s = it.get("symbol", "")
                        if s.endswith("USDT"):
                            intervals[s] = (_safe_float(it.get("fundingInterval"), 480) or 480) / 60.0
                    cursor = res.get("nextPageCursor") or ""
                    if not cursor:
                        break
            except Exception as e:
                errors.append(f"bybit_instruments:{e}")
            out = {}
            d = await _fetch_json(cli, "https://api.bybit.com/v5/market/tickers", {"category": "linear"})
            for t in d.get("result", {}).get("list", []):
                s = t.get("symbol", "")
                if s.endswith("USDT"):
                    out[s] = _safe_float(t.get("fundingRate")) * (24 / intervals.get(s, 8)) * 100
            return out

        async def gt_spot_f():
            out = {}
            for t in await _fetch_json(cli, "https://api.gateio.ws/api/v4/spot/tickers"):
                cp = t.get("currency_pair", "")
                if cp.endswith("_USDT"):
                    bid = _safe_float(t.get("highest_bid")); ask = _safe_float(t.get("lowest_ask"))
                    if bid > 0 and ask > 0:
                        out[cp.replace("_USDT", "USDT")] = (bid, ask)
            return out

        async def gt_fund_f():
            # contracts 批量自带 funding_rate + funding_interval(秒) + in_delisting(下架剔除) → 日化%
            out = {}
            for t in await _fetch_json(cli, "https://api.gateio.ws/api/v4/futures/usdt/contracts"):
                name = t.get("name", "")
                if not name.endswith("_USDT") or t.get("in_delisting"):
                    continue
                itv = _safe_float(t.get("funding_interval"), 28800) or 28800
                out[name.replace("_USDT", "USDT")] = _safe_float(t.get("funding_rate")) * (86400 / itv) * 100
            return out

        async def bg_spot_f():
            out = {}
            d = await _fetch_json(cli, "https://api.bitget.com/api/v2/spot/market/tickers", {})
            for t in d.get("data", []):
                s = t.get("symbol", "")
                if s.endswith("USDT"):
                    bid = _safe_float(t.get("bidPr")); ask = _safe_float(t.get("askPr"))
                    if bid > 0 and ask > 0:
                        out[s] = (bid, ask)
            return out

        async def bg_fund_f():
            # mix tickers 每期费率 + contracts fundInterval(小时,缺省8;仅 normal 态) → 日化%
            intervals = {}
            try:
                d = await _fetch_json(cli, "https://api.bitget.com/api/v2/mix/market/contracts",
                                      {"productType": "USDT-FUTURES"})
                for x in d.get("data", []):
                    s = x.get("symbol", "")
                    if s.endswith("USDT") and x.get("symbolStatus") in (None, "normal"):
                        intervals[s] = _safe_float(x.get("fundInterval"), 8) or 8
            except Exception as e:
                errors.append(f"bitget_contracts:{e}")
            out = {}
            d = await _fetch_json(cli, "https://api.bitget.com/api/v2/mix/market/tickers",
                                  {"productType": "USDT-FUTURES"})
            for t in d.get("data", []):
                s = t.get("symbol", "")
                if s.endswith("USDT") and s in intervals:
                    out[s] = _safe_float(t.get("fundingRate")) * (24 / intervals.get(s, 8)) * 100
            return out

        (bn_spot, bn_fund, okx_spot, bb_spot, bb_fund,
         gt_spot, gt_fund, bg_spot, bg_fund) = await _aio.gather(
            _safe("binance_spot", bn_spot_f(), {}), _safe("binance_fund", bn_fund_f(), {}),
            _safe("okx_spot", okx_spot_f(), {}), _safe("bybit_spot", bb_spot_f(), {}),
            _safe("bybit_fund", bb_fund_f(), {}), _safe("gate_spot", gt_spot_f(), {}),
            _safe("gate_fund", gt_fund_f(), {}), _safe("bitget_spot", bg_spot_f(), {}),
            _safe("bitget_fund", bg_fund_f(), {}))

    def _spr(pair):
        if not pair:
            return None
        bid, ask = pair
        return round((ask - bid) / bid * 100, 4) if bid > 0 else None

    _FUND_NAMES = {"bn": "币安", "bybit": "Bybit", "gate": "Gate", "bitget": "Bitget"}
    rows = []
    for s in bn_spot:  # 以 Binance 现货宇宙为基(=我们在做的币)
        spreads = {
            "bn_spread": _spr(bn_spot.get(s)), "okx_spread": _spr(okx_spot.get(s)),
            "bybit_spread": _spr(bb_spot.get(s)), "gate_spread": _spr(gt_spot.get(s)),
            "bitget_spread": _spr(bg_spot.get(s)),
        }
        venues = sum(1 for v in spreads.values() if v is not None)
        if venues < 2:
            continue   # 至少两所有价才有对比意义
        funds = {"bn": bn_fund.get(s), "bybit": bb_fund.get(s),
                 "gate": gt_fund.get(s), "bitget": bg_fund.get(s)}
        avail = {k: v for k, v in funds.items() if v is not None}
        gap = gap_pair = None
        if len(avail) >= 2:
            hi = max(avail, key=lambda k: avail[k])
            lo = min(avail, key=lambda k: avail[k])
            gap = round(avail[hi] - avail[lo], 5)
            gap_pair = f"{_FUND_NAMES[hi]}→{_FUND_NAMES[lo]}"
        rows.append({
            "symbol": s, **spreads,
            "bn_funding": round(funds["bn"], 5) if funds["bn"] is not None else None,
            "bybit_funding": round(funds["bybit"], 5) if funds["bybit"] is not None else None,
            "gate_funding": round(funds["gate"], 5) if funds["gate"] is not None else None,
            "bitget_funding": round(funds["bitget"], 5) if funds["bitget"] is not None else None,
            "funding_gap": gap,
            "gap_pair": gap_pair,
            "venues": venues,
        })
    # 排序:资金费跨所背离绝对值降序(carry 差异最大的币最有参照意义;None 沉底)
    rows.sort(key=lambda x: abs(x["funding_gap"]) if x["funding_gap"] is not None else -1, reverse=True)
    result = {
        "rows": rows[:top],
        "count": len(rows),
        "errors": errors,
        "note": "现货价差%越大=盘口越宽/流动性越差;资金费均为【日化%】(已按各所结算周期归一,正=多头付)。"
                "费差=四所日化最高−最低,方向=空高费所→多低费所。OKX 资金费仅逐合约端点,标尺省略。仅参照不做腿。",
        "ts": int(time.time() * 1000),
    }
    try:
        r.setex("crossvenue:ruler:v2", _VENUE_CACHE_TTL, json.dumps(result))
    except Exception:
        pass
    return result


# ─── P2-b Portfolio Margin 纸面对比表(只读参照,不动工) ───

@router.get("/pm-compare")
def pm_compare(request: Request, db: Session = Depends(get_db)):
    """PM 纸面评估(P2):当前全仓杠杆 vs 统一账户 Portfolio Margin 的利率/抵押率/保证金效率对比。
    纯纸面参照(未接 papi、本期不动工):本系统持"现货空 + 合约多" delta 中性组合,PM 的组合保证金会把
    两腿净额算保证金 → 保证金占用大幅下降、资金效率提升,是最值得评估的迁移点。数值为 Binance 公布的
    PM 参考参数 + 本账户实配抵押率,供决策参考,非实盘回测。"""
    require_admin(request)
    coll = None
    try:
        gr = db.query(GlobalRules).filter(GlobalRules.user_id.is_(None)).first()
        if gr and getattr(gr, "collateral_ratio", None) is not None:
            coll = float(gr.collateral_ratio)
    except Exception:
        pass
    return {
        "rows": [
            {"dim": "账户模式", "current": "全仓杠杆(逐子账户借币)",
             "pm": "统一账户 Portfolio Margin(USDT 本位组合保证金)"},
            {"dim": "两腿净额", "current": "无 — 现货空腿与合约多腿各自独立占保证金",
             "pm": "现货空 + 合约多 视为对冲组合,按组合净风险算保证金"},
            {"dim": "维持保证金", "current": "两腿分别计:现货杠杆维保 + 合约维保,delta 中性也不互抵",
             "pm": "delta 中性组合维保显著低于两腿独立之和(本系统核心收益点)"},
            {"dim": "抵押折算", "current": f"我方配置抵押率 = {coll if coll is not None else '未配置'}",
             "pm": "分层折算(Binance 公布):USDT=1.00 / BTC·ETH≈0.95 / 主流≈0.90"},
            {"dim": "借币利息", "current": "按 VIP 档杠杆借币小时计息(见规则页实时利率)",
             "pm": "同 VIP 档;组合净额降低实际借入 → 综合利息可能下降"},
            {"dim": "开仓容量", "current": "受各子账户独立保证金 + 借币额度天花板约束",
             "pm": "释放的保证金可提升借币/开仓容量(需实测)"},
        ],
        "verdict": ("本系统结构(现货空 + 合约多)天然 delta 中性,是 PM 组合保证金最能省保证金的形态;"
                    "纸面看迁 PM 可释放大量占用保证金、提升开仓容量。但需接 papi 并改动执行腿路由,"
                    "本期只做纸面对比、不动工。"),
        "caveat": "纸面参考:未接入 Portfolio Margin API(papi),数值为 Binance 公布参数 + 本账户配置,非实盘回测。",
        "collateral_ratio_current": coll,
    }
