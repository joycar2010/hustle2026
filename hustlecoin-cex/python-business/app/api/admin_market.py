import json
import logging
import time

import httpx
import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Blacklist, PendingBlacklist, AiCoinConfig
from app.db.models_auth import User
from app.db.session import get_db, SessionLocal
from app.middleware.permissions import require_admin
from app.services.aicoin_client import AiCoinClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/market", tags=["admin-market"])

_aicoin: AiCoinClient | None = None

_PERIOD_TO_SECONDS = {"1": "60", "5": "300", "15": "900", "30": "1800",
                      "60": "3600", "240": "14400", "1440": "86400"}


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


# ─── Binance Announcement Scraping ───

@router.get("/announcements")
def get_announcements(request: Request):
    require_admin(request)
    try:
        resp = httpx.get(
            "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
            params={
                "type": 1,
                "catalogId": 48,
                "pageNo": 1,
                "pageSize": 20,
            },
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        data = resp.json()
        articles = data.get("data", {}).get("catalogs", [{}])[0].get("articles", [])
        result = []
        for a in articles:
            title = a.get("title", "")
            is_delist = any(kw in title.lower() for kw in [
                "delist", "remove", "下线", "退市", "摘牌",
                "will delist", "delisting",
            ])
            result.append({
                "id": a.get("id"),
                "title": title,
                "url": f"https://www.binance.com/zh-CN/support/announcement/{a.get('code', '')}",
                "release_date": a.get("releaseDate"),
                "is_delist": is_delist,
            })
        return result
    except Exception as e:
        return {"error": str(e), "articles": []}


@router.post("/check-delist")
def check_delist(request: Request, db: Session = Depends(get_db)):
    """Scan Binance announcements for delisting notices and create pending blacklist entries."""
    require_admin(request)
    try:
        resp = httpx.get(
            "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
            params={"type": 1, "catalogId": 48, "pageNo": 1, "pageSize": 30},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        data = resp.json()
        articles = data.get("data", {}).get("catalogs", [{}])[0].get("articles", [])

        delist_keywords = ["delist", "remove", "下线", "退市", "摘牌", "delisting"]
        found = []
        for a in articles:
            title = a.get("title", "")
            if not any(kw in title.lower() for kw in delist_keywords):
                continue

            symbols = _extract_symbols(title)
            url = f"https://www.binance.com/zh-CN/support/announcement/{a.get('code', '')}"
            for sym in symbols:
                existing = db.query(PendingBlacklist).filter(
                    PendingBlacklist.symbol == sym,
                    PendingBlacklist.is_confirmed == False,
                ).first()
                if not existing:
                    pb = PendingBlacklist(
                        symbol=sym,
                        reason=f"Binance announcement: {title[:200]}",
                        source="binance_announcement",
                        announcement_title=title,
                        announcement_url=url,
                    )
                    db.add(pb)
                    found.append(sym)

        db.commit()
        return {"found": found, "count": len(found)}
    except Exception as e:
        return {"error": str(e), "found": [], "count": 0}


def _extract_symbols(title: str) -> list[str]:
    """Extract trading pair symbols from announcement title."""
    import re
    patterns = [
        r'\b([A-Z]{2,10})USDT\b',
        r'\b([A-Z]{2,10})/USDT\b',
        r'\b([A-Z]{2,10})BTC\b',
    ]
    symbols = set()
    for p in patterns:
        for m in re.finditer(p, title.upper()):
            base = m.group(1)
            if base not in ("THE", "AND", "FOR", "ALL", "NEW", "BNB", "WILL"):
                symbols.add(f"{base}USDT")
    return list(symbols)


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
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")


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
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")


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
        raise HTTPException(status_code=502, detail=f"AiCoin API error: {e}")


@router.delete("/rankings/history")
def reset_history_scores(request: Request):
    require_admin(request)
    try:
        r = _redis()
        r.delete("aicoin:history_scores")
        return {"message": "History scores reset"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
