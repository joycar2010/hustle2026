"""Crypto price direction filter for 5-minute Up/Down markets.

LIVE Chainlink TWAP markets should use Polymarket RTDS TWAP for both the
current price and the market-start price-to-beat. The legacy Binance path is
kept as an explicit fallback/debug source only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests

from bot.config import Config
from bot.markets import LiveMarket
from bot.rtds_signal import get_rtds_twap_signal_data


@dataclass(frozen=True)
class BtcSignal:
    ts: float
    symbol: str
    source: str
    price_to_beat: float
    current_price: float
    delta_usd: float
    signal_side: str
    threshold_usd: float
    up_min_delta_usd: float
    up_max_delta_usd: float
    down_min_delta_usd: float
    down_max_delta_usd: float
    source_ts: Optional[float] = None
    age_sec: Optional[float] = None
    feed_id: str = ""

    def allows(self, side: Optional[str]) -> bool:
        if side == "UP":
            if self.delta_usd <= self.up_min_delta_usd:
                return False
            return self.up_max_delta_usd <= 0 or self.delta_usd <= self.up_max_delta_usd
        if side == "DOWN":
            return self.delta_usd < self.down_max_delta_usd and (
                self.down_min_delta_usd >= 0
                or self.delta_usd >= self.down_min_delta_usd
            )
        return False

    def describe(self) -> str:
        prefix = self.symbol.replace("USDT", "").lower()
        down_rule = (
            f"down={self.down_min_delta_usd:.2f}..{self.down_max_delta_usd:.2f}"
            if self.down_min_delta_usd < 0
            else f"down<={self.down_max_delta_usd:.2f}"
        )
        age = f" age={self.age_sec:.2f}s" if self.age_sec is not None else ""
        return (
            f"{prefix}_delta={self.delta_usd:+.2f} "
            f"price={self.current_price:.2f} beat={self.price_to_beat:.2f} "
            f"signal={self.signal_side} "
            f"up>={self.up_min_delta_usd:.2f}"
            + (f"..{self.up_max_delta_usd:.2f}" if self.up_max_delta_usd > 0 else "")
            + f" {down_rule} "
            f"source={self.source}{age}"
        )


_open_cache: dict[tuple[str, int], tuple[float, str]] = {}
_current_cache: dict[str, tuple[float, float, str]] = {}


def _hosts(cfg: Config) -> list[str]:
    return [h.strip().rstrip("/") for h in cfg.btc_price_hosts.split(",") if h.strip()]


def _fetch_open_price(host: str, symbol: str, market_start_ts: float) -> float:
    start_ms = int(market_start_ts * 1000)
    r = requests.get(
        f"{host}/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": "1m",
            "startTime": start_ms,
            "limit": 1,
        },
        timeout=2,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise ValueError("empty kline response")
    return float(rows[0][1])


def _fetch_current_price(host: str, symbol: str) -> float:
    r = requests.get(
        f"{host}/api/v3/ticker/price",
        params={"symbol": symbol},
        timeout=2,
    )
    r.raise_for_status()
    return float(r.json()["price"])


def _get_open_price(cfg: Config, market: LiveMarket, symbol: str) -> tuple[float, str]:
    market_start_sec = int(market.start_ts)
    key = (symbol, market_start_sec)
    cached = _open_cache.get(key)
    if cached:
        return cached

    errors: list[str] = []
    for host in _hosts(cfg):
        try:
            price = _fetch_open_price(host, symbol, market.start_ts)
            out = (price, host)
            _open_cache[key] = out
            return out
        except Exception as e:
            errors.append(f"{host}: {e}")
    raise RuntimeError("; ".join(errors) or "no price hosts configured")


def _get_current_price(cfg: Config, symbol: str, max_age_sec: float = 0.75) -> tuple[float, str]:
    now = time.time()
    cached = _current_cache.get(symbol)
    if cached and now - cached[0] <= max_age_sec:
        return cached[1], cached[2]

    errors: list[str] = []
    for host in _hosts(cfg):
        try:
            price = _fetch_current_price(host, symbol)
            _current_cache[symbol] = (now, price, host)
            return price, host
        except Exception as e:
            errors.append(f"{host}: {e}")
    raise RuntimeError("; ".join(errors) or "no price hosts configured")


def _build_signal(
    *,
    symbol: str,
    source: str,
    price_to_beat: float,
    current_price: float,
    threshold_usd: float,
    up_min_delta_usd: float,
    up_max_delta_usd: float,
    down_min_delta_usd: float,
    down_max_delta_usd: float,
    source_ts: Optional[float] = None,
    age_sec: Optional[float] = None,
    feed_id: str = "",
) -> BtcSignal:
    delta = current_price - price_to_beat
    threshold = max(threshold_usd, 0.0)
    up_min = up_min_delta_usd
    up_max = up_max_delta_usd
    if down_min_delta_usd < 0:
        down_min = min(down_min_delta_usd, down_max_delta_usd)
        down_max = max(down_min_delta_usd, down_max_delta_usd)
    else:
        down_min = 0.0
        down_max = down_max_delta_usd
    up_allowed = delta >= up_min and (up_max <= 0 or delta <= up_max)
    down_allowed = delta <= down_max and (down_min >= 0 or delta >= down_min)
    if up_allowed:
        side = "UP"
    elif down_allowed:
        side = "DOWN"
    else:
        side = "FLAT"
    return BtcSignal(
        ts=time.time(),
        symbol=symbol,
        source=source,
        price_to_beat=price_to_beat,
        current_price=current_price,
        delta_usd=delta,
        signal_side=side,
        threshold_usd=threshold,
        up_min_delta_usd=up_min,
        up_max_delta_usd=up_max,
        down_min_delta_usd=down_min,
        down_max_delta_usd=down_max,
        source_ts=source_ts,
        age_sec=age_sec,
        feed_id=feed_id,
    )


def _fetch_binance_symbol_signal(
    cfg: Config,
    market: LiveMarket,
    *,
    symbol: str,
    threshold_usd: float,
    up_min_delta_usd: float,
    up_max_delta_usd: float,
    down_min_delta_usd: float,
    down_max_delta_usd: float,
) -> BtcSignal:
    price_to_beat, open_source = _get_open_price(cfg, market, symbol)
    current_price, current_source = _get_current_price(cfg, symbol)
    source = current_source if current_source == open_source else f"{open_source}->{current_source}"
    return _build_signal(
        symbol=symbol,
        source=source,
        price_to_beat=price_to_beat,
        current_price=current_price,
        threshold_usd=threshold_usd,
        up_min_delta_usd=up_min_delta_usd,
        up_max_delta_usd=up_max_delta_usd,
        down_min_delta_usd=down_min_delta_usd,
        down_max_delta_usd=down_max_delta_usd,
    )


def fetch_symbol_signal(
    cfg: Config,
    market: LiveMarket,
    *,
    symbol: str,
    threshold_usd: float,
    up_min_delta_usd: float,
    up_max_delta_usd: float,
    down_min_delta_usd: float,
    down_max_delta_usd: float,
) -> BtcSignal:
    source = cfg.price_signal_source.strip().lower()
    if source in ("rtds", "polymarket-rtds", "chainlink-rtds", "polymarket"):
        data = get_rtds_twap_signal_data(cfg, market, price_symbol=symbol)
        return _build_signal(
            symbol=symbol,
            source=data.source,
            price_to_beat=data.price_to_beat,
            current_price=data.current_price,
            threshold_usd=threshold_usd,
            up_min_delta_usd=up_min_delta_usd,
            up_max_delta_usd=up_max_delta_usd,
            down_min_delta_usd=down_min_delta_usd,
            down_max_delta_usd=down_max_delta_usd,
            source_ts=data.source_ts,
            age_sec=data.age_sec,
            feed_id=data.feed_id,
        )
    if source in ("binance", "binance-proxy", "proxy"):
        return _fetch_binance_symbol_signal(
            cfg,
            market,
            symbol=symbol,
            threshold_usd=threshold_usd,
            up_min_delta_usd=up_min_delta_usd,
            up_max_delta_usd=up_max_delta_usd,
            down_min_delta_usd=down_min_delta_usd,
            down_max_delta_usd=down_max_delta_usd,
        )
    raise ValueError(f"unsupported PRICE_SIGNAL_SOURCE={cfg.price_signal_source!r}")


def fetch_btc_signal(cfg: Config, market: LiveMarket) -> BtcSignal:
    return fetch_symbol_signal(
        cfg,
        market,
        symbol=cfg.btc_price_symbol,
        threshold_usd=cfg.btc_delta_threshold_usd,
        up_min_delta_usd=cfg.btc_up_min_delta_usd,
        up_max_delta_usd=cfg.btc_up_max_delta_usd,
        down_min_delta_usd=cfg.btc_down_min_delta_usd,
        down_max_delta_usd=cfg.btc_down_max_delta_usd,
    )


def fetch_eth_signal(cfg: Config, market: LiveMarket) -> BtcSignal:
    return fetch_symbol_signal(
        cfg,
        market,
        symbol=cfg.eth_price_symbol,
        threshold_usd=cfg.eth_delta_threshold_usd,
        up_min_delta_usd=cfg.eth_up_min_delta_usd,
        up_max_delta_usd=cfg.eth_up_max_delta_usd,
        down_min_delta_usd=cfg.eth_down_min_delta_usd,
        down_max_delta_usd=cfg.eth_down_max_delta_usd,
    )
