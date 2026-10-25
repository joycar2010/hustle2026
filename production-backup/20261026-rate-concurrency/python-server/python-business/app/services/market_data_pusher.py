import asyncio
import json
import logging
import re
import time
from typing import Optional

import httpx
import redis.asyncio as aioredis
from sqlalchemy import func

from app.config import settings
from app.db.session import SessionLocal
from app.services.eligible_universe import database_eligible_symbols, exchange_eligible_symbols

logger = logging.getLogger(__name__)

PREMIUM_INDEX_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
FUNDING_INFO_URL = "https://fapi.binance.com/fapi/v1/fundingInfo"
INTEREST_RATE_URL = "https://www.binance.com/bapi/margin/v1/public/margin/vip/spec/list-all"
SPOT_EXINFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
FUT_EXINFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"

REFRESH_INTERVAL = 8    # èµ„é‡‘è´¹çŽ‡/markä»· å®žæ—¶åˆ·æ–°(premiumIndex æ˜¯ä½ŽIPæƒé‡å…¬å¼€ç«¯ç‚¹,8s å®‰å…¨ä¸”å¤Ÿå®žæ—¶)
STATIC_REFRESH_MULTIPLIER = 4  # 8s loop; exchangeInfo/universe refresh stays under 30s
INTEREST_CACHE_KEY = "market:interest_rates"  # Redis backup for last-good interest rates
UNIVERSE_KEY = "engine:universe"  # Rust: spot+margin+USDT perpetual and DB-approved symbols
# Existing positions may outlive the exchange execution universe (for example
# after a delisting gate removes a symbol).  Keep their two-legged quotes on a
# separate, short-lived feed key so the Rust engine can close/repay them
# without ever widening the new-action universe.
EXIT_UNIVERSE_KEY = "engine:exit-universe"
EXIT_UNIVERSE_TTL_SEC = 90
_TERMINAL_POSITION_STATUSES = ("CLOSED", "FAILED")
_USDT_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,26}USDT$")

# ç‚¹å·®åœæ›´ç›‘æŽ§:rust ç‚¹å·®å¼•æ“ŽæŸåˆ†ç‰‡åŠå¼€/æŽ‰çº¿ â†’ å¤§ç‰‡å¸çš„ç‚¹å·®åœæ›´(å®žæµ‹ Aâ€“M æ®µå†»ç»“ 9.6h æ— äººçŸ¥)ã€‚
# å£å¾„æ ¡å‡†(å®žæµ‹å¥åº·ç¨³æ€):bookTicker ä»…åœ¨ä¹°å–ä¸€ä»·å˜åŠ¨æ—¶æŽ¨,å¤§é‡éžæ´»è·ƒå¸æœ¬å°±é•¿æ—¶é—´ä¸å˜ä»· â†’
# fresh<60s ç¨³æ€ä»… ~65%(ä¸å¯ç”¨ä½œé˜ˆå€¼,ä¼šç‹‚è¯¯æŠ¥);ä½† fresh<30min=100%(å¥åº·æ€æ¯ä¸ªå¸ 30min å†…å¿…æ›´æ–°)ã€‚
# æ•…æ”¹ç”¨ã€Œé•¿çª—å£åœæ›´æ¯”ä¾‹ã€:å•å¸ ts è¶… STALE_WINDOW_MS(10min)ç®—åœæ›´;åœæ›´å¸ / universe è¶…é˜ˆå€¼ä¸”æŒç»­
# >1 åˆ†é’Ÿ â†’ è·‘é©¬ç¯+é£žä¹¦å‘Šè­¦ã€‚å¥åº·ç¨³æ€åœæ›´æ¯”ä¾‹ ~12%,å•åˆ†ç‰‡æ•´æ­» ~55% â†’ é˜ˆå€¼ 40% ä¸¤è¾¹éƒ½ç•™è¶³ä½™é‡ã€‚
STALE_WINDOW_MS = 600_000         # å•å¸ ts è¶…æ­¤(10min)ç®—ã€Œåœæ›´ã€
STALE_ALERT_FRACTION = 0.40       # åœæ›´å¸ / universe > æ­¤æ¯”ä¾‹è§¦å‘(å¥åº·~12%,å•åˆ†ç‰‡æ­»~55%)
STALE_ALERT_SUSTAIN_SEC = 60      # æŒç»­ >1 åˆ†é’Ÿæ‰å‘Šè­¦(æ»¤çž¬æ€)
STALE_ALERT_COOLDOWN_SEC = 600    # å‘Šè­¦å†·å´ 10 åˆ†é’Ÿ(é—®é¢˜æŒç»­æœŸé—´ä¸åˆ·å±)


def _oldest_local_receive_ms(item: dict) -> int:
    """Return the oldest Rust-local quote receipt, or zero for legacy data."""
    try:
        spot = int(item.get("spot_recv_ts_ms", 0) or 0)
        futures = int(item.get("fut_recv_ts_ms", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return min(spot, futures) if spot > 0 and futures > 0 else 0


def _load_active_position_symbols() -> set[str]:
    """Read the global set of symbols that still have a non-terminal Position.

    This is deliberately independent of tenant rules and of ``engine:universe``:
    an account may be disabled or a symbol may be delisted while its existing
    hedge still needs an exit quote.  The query is read-only; a failed refresh
    leaves the previous Redis value in place until its TTL expires.
    """
    # Keep the import local so the API-only process can import this service
    # during startup before the engine model module has been initialized.
    from engine.models import Position, canonical_position_symbol

    db = SessionLocal()
    try:
        rows = (
            db.query(Position.symbol)
            .filter(
                Position.symbol.isnot(None),
                # Legacy rows may contain lowercase/whitespace status values;
                # normalize before excluding terminal positions so they do not
                # keep an exit-only stream alive forever.
                func.upper(func.trim(func.coalesce(Position.status, ""))).notin_(
                    _TERMINAL_POSITION_STATUSES
                ),
            )
            .distinct()
            .all()
        )
        symbols: set[str] = set()
        for (raw_symbol,) in rows:
            symbol = canonical_position_symbol(raw_symbol)
            # The Rust/Binance feed is USDT-only.  Ignore malformed legacy rows
            # instead of accidentally subscribing to an arbitrary stream name.
            if _USDT_SYMBOL_RE.fullmatch(symbol):
                symbols.add(symbol)
        return symbols
    finally:
        db.close()


class MarketDataPusher:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._funding_info: dict[str, dict] = {}
        self._interest_rates: dict[str, float] = {}
        self._static_tick = 0
        self._monitored_symbols: set[str] = set()
        self._high_stale_since: Optional[float] = None  # åœæ›´æ¯”ä¾‹æŒç»­è¶…é˜ˆèµ·å§‹(monotonic)
        self._last_stale_alert_mono: float = -1e9       # ä¸Šæ¬¡åœæ›´å‘Šè­¦æ—¶é—´(å†·å´)

    async def start(self):
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._running = True
        # Restore last-good interest rates so a restart (or a failed first fetch)
        # never wipes the æ¯/èµ„å€ columns.
        try:
            cached = await self._redis.get(INTEREST_CACHE_KEY)
            if cached:
                self._interest_rates = json.loads(cached)
                logger.info(f"Restored {len(self._interest_rates)} cached interest rates")
        except Exception as e:
            logger.warning(f"Failed to restore interest rate cache: {e}")
        logger.info("MarketDataPusher started")

        while self._running:
            try:
                # Refresh before reading/publishing market metadata so a
                # newly delisted active Position gets an exit-only stream on
                # the first successful cycle.  The key is intentionally
                # separate from UNIVERSE_KEY and never affects opening gates.
                await self._publish_exit_universe()
                spread_keys = await self._redis.hkeys("spreads")
                self._monitored_symbols = set(spread_keys)

                fetch_static = self._static_tick % STATIC_REFRESH_MULTIPLIER == 0
                if fetch_static:
                    await self._fetch_static_data()

                await self._fetch_and_publish()
                await self._check_freshness_and_alert()
                self._static_tick += 1
            except Exception as e:
                logger.warning(f"MarketDataPusher cycle error: {e}")

            await asyncio.sleep(REFRESH_INTERVAL)

    async def _publish_exit_universe(self) -> None:
        """Publish non-terminal Position symbols with a bounded lease."""
        if self._redis is None:
            return
        try:
            symbols = await asyncio.to_thread(_load_active_position_symbols)
            payload = json.dumps(sorted(symbols), separators=(",", ":"))
            await self._redis.set(
                EXIT_UNIVERSE_KEY,
                payload,
                ex=EXIT_UNIVERSE_TTL_SEC,
            )
        except Exception as exc:
            # Do not replace a last-good set with an empty value on a transient
            # DB/Redis failure.  Its short TTL bounds stale subscriptions.
            logger.warning("Failed to refresh exit-only WS universe: %s", exc)

    async def stop(self):
        self._running = False
        if self._redis:
            await self._redis.aclose()

    async def _fetch_static_data(self):
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(FUNDING_INFO_URL)
                if resp.status_code == 200:
                    for item in resp.json():
                        sym = item.get("symbol", "")
                        self._funding_info[sym] = {
                            "interval": item.get("fundingIntervalHours", 8),
                            "cap": float(item.get("adjustedFundingRateCap", "0.003")),
                        }
                    logger.debug(f"Fetched funding info: {len(self._funding_info)} symbols")
            except Exception as e:
                logger.warning(f"Failed to fetch funding info: {e}")

            try:
                resp = await client.get(INTEREST_RATE_URL)
                if resp.status_code == 200:
                    data = resp.json()
                    fresh: dict[str, float] = {}
                    for item in data.get("data", []):
                        asset = item.get("assetName", "")
                        vip0 = next((s for s in item.get("specs", []) if s.get("vipLevel") == "0"), None)
                        if vip0:
                            fresh[asset] = float(vip0.get("dailyInterestRate", "0"))
                    # Only overwrite when the fetch actually returned data â€” a transient
                    # empty/500 response must not wipe the last-good rates.
                    if fresh:
                        self._interest_rates.update(fresh)
                        try:
                            await self._redis.set(INTEREST_CACHE_KEY, json.dumps(self._interest_rates))
                        except Exception:
                            pass
                    logger.debug(f"Fetched interest rates: {len(fresh)} assets")
            except Exception as e:
                logger.warning(f"Failed to fetch interest rates: {e}")

            # åˆ·æ–° Rust å¼•æ“Žè®¢é˜…å®‡å®™ engine:universe = çŽ°è´§âˆ©åˆçº¦ USDT å¯äº¤æ˜“å¯¹ã€‚
            # éšå¸å®‰ä¸Š/é€€å¸‚åŠ¨æ€æ›´æ–°;åªåœ¨ä¸¤è…¿ exchangeInfo éƒ½æˆåŠŸå–åˆ°æ—¶æ‰è¦†å†™(é¿å…æŠ–åŠ¨æ¸…ç©º)ã€‚
            try:
                spot_resp, fut_resp = await asyncio.gather(
                    client.get(SPOT_EXINFO_URL, params={"permissions":"MARGIN","showPermissionSets":"false"}), client.get(FUT_EXINFO_URL),
                )
                if spot_resp.status_code == 200 and fut_resp.status_code == 200:
                    spot_json = spot_resp.json()
                    fut_json = fut_resp.json()
                    spot_payload = spot_json.get("symbols")
                    fut_payload = fut_json.get("symbols")
                    if not isinstance(spot_payload, list) or not isinstance(fut_payload, list):
                        raise ValueError("exchangeInfo response missing symbols list")
                    exchange_set = exchange_eligible_symbols(spot_payload, fut_payload)

                    def _db_filter() -> set[str]:
                        db = SessionLocal()
                        try:
                            return database_eligible_symbols(db, exchange_set)
                        finally:
                            db.close()

                    universe = sorted(await asyncio.to_thread(_db_filter))
                    # A valid empty intersection is authoritative: clear the
                    # feed so a delisted/disabled symbol cannot remain in the
                    # Rust subscription set.  Malformed/failed responses are
                    # rejected above and therefore preserve last-good data.
                    await self._redis.set(UNIVERSE_KEY, json.dumps(universe))
                    logger.debug(f"Refreshed engine:universe: {len(universe)} symbols")
            except Exception as e:
                logger.warning(f"Failed to refresh engine:universe: {e}")

    async def _fetch_and_publish(self):
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(PREMIUM_INDEX_URL)
                if resp.status_code != 200:
                    return
                premium_data = resp.json()
            except Exception as e:
                logger.warning(f"Failed to fetch premium index: {e}")
                return

        market_data = {}
        for item in premium_data:
            symbol = item.get("symbol", "")
            if symbol not in self._monitored_symbols:
                continue

            asset = symbol.replace("USDT", "")
            info = self._funding_info.get(symbol, {})
            interest = self._interest_rates.get(asset, 0)
            funding_rate = float(item.get("lastFundingRate", "0"))
            mark_price = float(item.get("markPrice", "0") or 0)   # åˆçº¦ mark ä»·(/spreads å¼€ä»“/å¹³ä»“ åŸºå·®é”š)
            interval = info.get("interval", 8)
            cap = info.get("cap", 0)

            # èµ„æ¯å€çŽ‡: funding income vs borrow interest over one funding interval.
            # Signed â€” negative funding rate means funding is a COST, not income,
            # so the ratio must be negative (do not abs()).
            ratio = 0.0
            if interest > 0 and funding_rate != 0:
                interest_per_interval = (interest / 24) * interval
                if interest_per_interval > 0:
                    ratio = round(funding_rate / interest_per_interval, 2)

            market_data[symbol] = {
                "funding_rate": funding_rate,
                "mark_price": mark_price,
                "funding_interval": interval,
                "funding_cap": cap,
                "daily_interest": interest,
                "ratio": ratio,
                "next_funding_time": item.get("nextFundingTime", 0),
            }

        if market_data:
            await self._redis.publish("market:updates", json.dumps(market_data))

    async def _check_freshness_and_alert(self):
        """ç‚¹å·®åœæ›´ç›‘æŽ§:åœæ›´å¸(ts>10min)/universe > STALE_ALERT_FRACTION ä¸”æŒç»­ >STALE_ALERT_SUSTAIN_SEC,
        è·‘é©¬ç¯+é£žä¹¦å‘Šè­¦(å†·å´ STALE_ALERT_COOLDOWN_SEC)ã€‚æœ¬å¯åœ¨æŸåˆ†ç‰‡å†»ç»“çš„ ~1 åˆ†é’Ÿå†…å°±å‘çŽ°,è€Œéž 9.6h åŽã€‚"""
        try:
            h = await self._redis.hgetall("spreads")
            if not h:
                return
            uni_raw = await self._redis.get(UNIVERSE_KEY)
            universe_n = len(json.loads(uni_raw)) if uni_raw else len(h)
            if universe_n < 50:
                return
            now = int(time.time() * 1000)
            stale = 0
            for v in h.values():
                try:
                    item = json.loads(v)
                    # A spread is live only when *both* Rust WS legs have a
                    # recent local receipt. Exchange event ``ts`` is allowed
                    # to lag on quiet symbols and is not suitable for this
                    # feed-health alarm; legacy snapshots without the fields
                    # are conservatively counted stale.
                    oldest = _oldest_local_receive_ms(item)
                    if oldest <= 0 or now - oldest > STALE_WINDOW_MS:
                        stale += 1
                except Exception:
                    pass
            frac = stale / universe_n
            mono = time.monotonic()
            if frac > STALE_ALERT_FRACTION:
                if self._high_stale_since is None:
                    self._high_stale_since = mono
                if (mono - self._high_stale_since) >= STALE_ALERT_SUSTAIN_SEC \
                        and (mono - self._last_stale_alert_mono) >= STALE_ALERT_COOLDOWN_SEC:
                    self._last_stale_alert_mono = mono
                    await self._send_stale_alert(stale, universe_n, frac)
            else:
                self._high_stale_since = None
        except Exception as e:
            logger.warning(f"freshness check error: {e}")

    async def _send_stale_alert(self, stale: int, universe_n: int, frac: float):
        title = "âš ï¸è¡Œæƒ…ç‚¹å·®åœæ›´å‘Šè­¦"
        content = (f"ç‚¹å·®åœæ›´å¸(>10min) {stale}/{universe_n}({frac * 100:.0f}%) è¶…é˜ˆå€¼ä¸”æŒç»­ >1 åˆ†é’Ÿ â€” "
                   f"rust ç‚¹å·®å¼•æ“Ž(cex-engine @10.0.1.95)ç–‘ä¼¼åŠå¼€/åˆ†ç‰‡æŽ‰çº¿,è¯·ç«‹å³æ£€æŸ¥")
        logger.warning(f"SPREAD FEED STALE ALERT: {content}")
        # è·‘é©¬ç¯(notification:broadcast,å‰ç«¯è®¢é˜…)
        try:
            await self._redis.publish("notification:broadcast", json.dumps({
                "title": title, "content": content, "priority": 1,
                "color": "#ef4444", "blink": True, "sound": "none",
            }))
        except Exception as e:
            logger.warning(f"stale alert marquee failed: {e}")
        # é£žä¹¦(å…¨å±€ FeishuConfig webhook,user_id=None)
        try:
            def _get_webhook():
                from app.db.session import SessionLocal
                from app.db.models import FeishuConfig
                db = SessionLocal()
                try:
                    fc = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
                    return fc.webhook_url if fc else None
                finally:
                    db.close()
            url = await asyncio.to_thread(_get_webhook)
            if url:
                async with httpx.AsyncClient(timeout=10) as c:
                    await c.post(url, json={"msg_type": "text",
                                            "content": {"text": f"{title}\n{content}"}})
        except Exception as e:
            logger.warning(f"stale alert feishu failed: {e}")


market_data_pusher = MarketDataPusher()
