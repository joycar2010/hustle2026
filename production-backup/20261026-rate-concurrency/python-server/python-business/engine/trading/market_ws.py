"""Read-only Binance market data supplied by the Rust WebSocket engine.

The Rust engine consumes Binance Spot/Futures ``bookTicker`` streams and writes
validated spread snapshots to the Redis ``spreads`` hash.  Trading code must
use this feed for live prices instead of issuing per-order public REST ticker
requests.  A stale or incomplete snapshot is a hard failure: using an old
price to size a borrow or market order is less safe than waiting for the feed.

This module deliberately does not provide account, borrow, or order methods.
Those operations remain on Binance's signed REST API because Binance does not
offer an equivalent unauthenticated market-data WebSocket operation.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from engine.freshness import configured_spread_max_age_ms


# Keep read-only WS consumers on the same execution freshness fence as the
# spread feed and order executor.
DEFAULT_MAX_AGE_MS = configured_spread_max_age_ms()


class MarketDataUnavailable(RuntimeError):
    """The WS market feed has no complete, fresh quote for a symbol."""


@dataclass(frozen=True)
class WsBookTicker:
    symbol: str
    bid_price: Decimal
    ask_price: Decimal
    ts: int
    # Rust-local receipt time for this leg.  ``ts`` remains Binance event time
    # for API compatibility; freshness decisions must use this field.
    recv_ts_ms: int = 0

    def as_binance_payload(self) -> dict[str, str | int]:
        """Return the field names consumed by existing order code."""
        return {
            "symbol": self.symbol,
            "bidPrice": str(self.bid_price),
            "askPrice": str(self.ask_price),
            "b": str(self.bid_price),
            "a": str(self.ask_price),
            "T": self.ts,
            "E": self.ts,
            "recv_ts_ms": self.recv_ts_ms,
            "source": "binance_ws",
        }


class RedisWsMarketData:
    """Small async reader for the Rust engine's latest WS spread snapshots."""

    def __init__(self, redis=None, max_age_ms: int = DEFAULT_MAX_AGE_MS):
        self._redis = redis
        self._owns_redis = redis is None
        self.max_age_ms = max(1, int(max_age_ms))

    async def _client(self):
        if self._redis is None:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def close(self):
        if self._owns_redis and self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def book_ticker(self, symbol: str, market: str = "spot") -> WsBookTicker:
        symbol = _normalise_symbol(symbol)
        market = market.lower().strip()
        if market not in {"spot", "futures"}:
            raise ValueError(f"unsupported market: {market}")

        raw = await (await self._client()).hget("spreads", symbol)
        if not raw:
            raise MarketDataUnavailable(f"{symbol} {market} WS quote unavailable")

        try:
            parsed: dict[str, Any] = raw if isinstance(raw, dict) else json.loads(raw)
            prefix = "spot" if market == "spot" else "fut"
            bid = _decimal(parsed.get(f"{prefix}_bid"))
            ask = _decimal(parsed.get(f"{prefix}_ask"))
            ts = int(parsed.get("ts", 0) or 0)
            recv_ts_ms = int(parsed.get(f"{prefix}_recv_ts_ms", 0) or 0)
        except (TypeError, ValueError, InvalidOperation, json.JSONDecodeError) as exc:
            raise MarketDataUnavailable(f"{symbol} {market} WS quote malformed") from exc

        now_ms = int(time.time() * 1000)
        # ``ts`` is the exchange event timestamp and can legitimately lag on
        # quiet symbols.  The Rust engine's per-leg local receipt timestamp is
        # the only liveness authority for order pricing.
        age_ms = now_ms - recv_ts_ms
        # A small future tolerance handles clock skew between the Rust host and
        # Python process; a wildly future timestamp is not trusted as fresh.
        if ts <= 0 or recv_ts_ms <= 0 or age_ms > self.max_age_ms or age_ms < -60_000:
            age = "missing" if recv_ts_ms <= 0 else f"{age_ms}ms old"
            raise MarketDataUnavailable(
                f"{symbol} {market} WS quote stale ({age}, max {self.max_age_ms}ms)"
            )
        if bid <= 0 or ask <= 0 or ask < bid:
            raise MarketDataUnavailable(f"{symbol} {market} WS quote invalid prices")
        return WsBookTicker(
            symbol=symbol,
            bid_price=bid,
            ask_price=ask,
            ts=ts,
            recv_ts_ms=recv_ts_ms,
        )

    async def all_book_tickers(self, market: str = "spot") -> dict[str, WsBookTicker]:
        """Read and validate the current snapshot set for read-only dashboards."""
        market = market.lower().strip()
        if market not in {"spot", "futures"}:
            raise ValueError(f"unsupported market: {market}")
        rows = await (await self._client()).hgetall("spreads")
        out: dict[str, WsBookTicker] = {}
        for symbol in rows:
            try:
                out[symbol] = await self.book_ticker(symbol, market)
            except MarketDataUnavailable:
                # Stale/partial symbols are intentionally omitted; callers
                # must never mistake an old snapshot for a live quote.
                continue
        return out


_default_reader = RedisWsMarketData()


async def get_ws_book_ticker(symbol: str, market: str = "spot", *, max_age_ms: int | None = None) -> dict:
    """Read one fresh WS quote using Binance-compatible field names."""
    reader = _default_reader
    if max_age_ms is not None and int(max_age_ms) != reader.max_age_ms:
        # Per-call overrides are used by diagnostics/tests without mutating the
        # process-wide safety default.
        reader = RedisWsMarketData(reader._redis, max_age_ms=int(max_age_ms))
        reader._owns_redis = False
    return (await reader.book_ticker(symbol, market)).as_binance_payload()


async def get_ws_price(symbol: str, market: str = "spot", side: str = "bid") -> Decimal:
    """Return a fresh WS bid/ask for notional and limit-price calculations."""
    quote = await _default_reader.book_ticker(symbol, market)
    side = side.lower().strip()
    if side == "bid":
        return quote.bid_price
    if side == "ask":
        return quote.ask_price
    raise ValueError(f"unsupported side: {side}")


async def get_all_ws_book_tickers(market: str = "spot", *, max_age_ms: int | None = None) -> dict[str, dict]:
    """Return fresh Binance-compatible quotes for dashboard/read-only use."""
    reader = _default_reader
    if max_age_ms is not None and int(max_age_ms) != reader.max_age_ms:
        reader = RedisWsMarketData(reader._redis, max_age_ms=int(max_age_ms))
        reader._owns_redis = False
    return {symbol: quote.as_binance_payload()
            for symbol, quote in (await reader.all_book_tickers(market)).items()}


def _normalise_symbol(symbol: str) -> str:
    value = str(symbol or "").strip().upper().replace("-", "").replace("_", "")
    if not value or not value.endswith("USDT"):
        raise MarketDataUnavailable(f"invalid Binance symbol: {symbol!r}")
    return value


def _decimal(value: Any) -> Decimal:
    if value is None or value == "":
        raise InvalidOperation
    return Decimal(str(value))
