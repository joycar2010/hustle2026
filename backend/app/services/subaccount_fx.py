"""CNY → USDT snapshot conversion for sub-account creation.

Priority order:
  1. OKX C2C best-seller USDT/CNY (most representative of real purchase cost)
  2. Fallback: CFETS USD/CNY midprice × user-configured usd_usdt_rate
  3. Fallback: last Redis-cached value (< 24h)
  4. Final fallback: hardcoded 7.20 (admin will override)
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from typing import Optional, Tuple

import httpx

from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)

_FX_CACHE_KEY = "subacc:fx:cny_to_usdt"
_FX_CACHE_TTL = 3600 * 12  # 12h
_HARD_FALLBACK_CNY_PER_USDT = Decimal("7.20")


async def _try_okx_c2c(cli: httpx.AsyncClient) -> Optional[Decimal]:
    """Best-sell price of USDT in CNY from OKX P2P — reflects real retail cost."""
    try:
        r = await cli.get(
            "https://www.okx.com/v3/c2c/tradingOrders/books",
            params={"quoteCurrency": "CNY", "baseCurrency": "USDT",
                    "side": "sell", "paymentMethod": "all", "userType": "all",
                    "showTrade": "false", "showFollow": "false", "showAlert": "false",
                    "urgent": "false", "sortType": "price_asc"},
        )
        r.raise_for_status()
        data = r.json().get("data", {}).get("sell", [])
        if data:
            return Decimal(str(data[0].get("price")))
    except Exception as e:
        logger.debug(f"[fx] okx c2c failed: {e}")
    return None


async def _try_binance_c2c(cli: httpx.AsyncClient) -> Optional[Decimal]:
    try:
        r = await cli.post(
            "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
            json={"asset": "USDT", "fiat": "CNY", "tradeType": "BUY",
                  "page": 1, "rows": 5, "payTypes": [], "publisherType": None},
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        prices = [Decimal(str(d["adv"]["price"])) for d in data if d.get("adv")]
        if prices:
            return min(prices)  # buy-USDT lowest offer
    except Exception as e:
        logger.debug(f"[fx] binance c2c failed: {e}")
    return None


async def get_cny_per_usdt(*, force: bool = False) -> Tuple[Decimal, str]:
    """Return (cny_per_usdt, source_tag). ~7.x typically.

    source_tag examples: 'okx_c2c', 'binance_c2c', 'cache', 'hardcoded'
    """
    # Cache short-circuit
    if not force:
        try:
            rc = redis_client.client
            if rc is not None:
                raw = await rc.get(_FX_CACHE_KEY)
                if raw:
                    d = json.loads(raw)
                    if time.time() - d["ts"] < _FX_CACHE_TTL:
                        return Decimal(d["rate"]), f"cache({d['source']})"
        except Exception:
            pass

    rate: Optional[Decimal] = None
    source = "hardcoded"
    timeout = httpx.Timeout(10.0, connect=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as cli:
            rate = await _try_okx_c2c(cli)
            if rate:
                source = "okx_c2c"
            else:
                rate = await _try_binance_c2c(cli)
                if rate:
                    source = "binance_c2c"
    except Exception as e:
        logger.warning(f"[fx] live fetch failed: {e}")

    if rate is None:
        rate = _HARD_FALLBACK_CNY_PER_USDT

    # Persist the live value (not hardcoded) as last-known
    if source != "hardcoded":
        try:
            rc = redis_client.client
            if rc is not None:
                await rc.set(_FX_CACHE_KEY, json.dumps({
                    "rate": str(rate), "source": source, "ts": int(time.time()),
                }), ex=_FX_CACHE_TTL * 2)
        except Exception:
            pass

    return rate, source


async def cny_to_usdt(cny: Decimal) -> Tuple[Decimal, Decimal, str]:
    """Return (usdt_amount, fx_rate_cny_per_usdt, source_tag)."""
    rate, source = await get_cny_per_usdt()
    usdt = (Decimal(cny) / rate).quantize(Decimal("0.00000001"))
    return usdt, rate, source
