import asyncio
import json
import logging
from typing import Optional

import httpx
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

PREMIUM_INDEX_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
FUNDING_INFO_URL = "https://fapi.binance.com/fapi/v1/fundingInfo"
INTEREST_RATE_URL = "https://www.binance.com/bapi/margin/v1/public/margin/vip/spec/list-all"
SPOT_EXINFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
FUT_EXINFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"

REFRESH_INTERVAL = 8    # 资金费率/mark价 实时刷新(premiumIndex 是低IP权重公开端点,8s 安全且够实时)
STATIC_REFRESH_MULTIPLIER = 38  # 静态数据(资费周期/上限/利率)每 ~5 分钟刷一次(8s×38≈304s)
INTEREST_CACHE_KEY = "market:interest_rates"  # Redis backup for last-good interest rates
UNIVERSE_KEY = "engine:universe"  # Rust 引擎订阅集:现货∩合约 USDT 可交易对(随上/退市动态刷新)


class MarketDataPusher:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._funding_info: dict[str, dict] = {}
        self._interest_rates: dict[str, float] = {}
        self._static_tick = 0
        self._monitored_symbols: set[str] = set()

    async def start(self):
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._running = True
        # Restore last-good interest rates so a restart (or a failed first fetch)
        # never wipes the 息/资倍 columns.
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
                spread_keys = await self._redis.hkeys("spreads")
                self._monitored_symbols = set(spread_keys)

                fetch_static = self._static_tick % STATIC_REFRESH_MULTIPLIER == 0
                if fetch_static:
                    await self._fetch_static_data()

                await self._fetch_and_publish()
                self._static_tick += 1
            except Exception as e:
                logger.warning(f"MarketDataPusher cycle error: {e}")

            await asyncio.sleep(REFRESH_INTERVAL)

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
                    # Only overwrite when the fetch actually returned data — a transient
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

            # 刷新 Rust 引擎订阅宇宙 engine:universe = 现货∩合约 USDT 可交易对。
            # 随币安上/退市动态更新;只在两腿 exchangeInfo 都成功取到时才覆写(避免抖动清空)。
            try:
                spot_resp, fut_resp = await asyncio.gather(
                    client.get(SPOT_EXINFO_URL), client.get(FUT_EXINFO_URL),
                )
                if spot_resp.status_code == 200 and fut_resp.status_code == 200:
                    spot_syms = {
                        s["symbol"] for s in spot_resp.json().get("symbols", [])
                        if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"
                    }
                    fut_syms = {
                        s["symbol"] for s in fut_resp.json().get("symbols", [])
                        if s.get("status") == "TRADING"
                        and s.get("contractType") == "PERPETUAL"
                        and s.get("quoteAsset") == "USDT"
                    }
                    universe = sorted(spot_syms & fut_syms)
                    if universe:  # 非空才写,防 exchangeInfo 异常空集清空订阅
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
            mark_price = float(item.get("markPrice", "0") or 0)   # 合约 mark 价(/spreads 开仓/平仓 基差锚)
            interval = info.get("interval", 8)
            cap = info.get("cap", 0)

            # 资息倍率: funding income vs borrow interest over one funding interval.
            # Signed — negative funding rate means funding is a COST, not income,
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


market_data_pusher = MarketDataPusher()
