"""BTC price signal vs the 5-minute window open.

Resolution uses Chainlink BTC/USD TWAP. We approximate direction with a
multi-venue median (OKX / Coinbase / Kraken) for robustness; optional
consensus requires agreeing side across venues.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
import requests

from btc5m.config import Config
from btc5m.markets import LiveMarket

_open_cache: dict[int, tuple[float, str]] = {}
_spot_cache: dict[str, tuple[float, float]] = {}


@dataclass(frozen=True)
class BtcSignal:
    ts: float
    source: str
    price_to_beat: float
    current_price: float
    delta_usd: float
    signal_side: str
    venue_count: int = 1
    consensus: bool = True

    def allows(self, side: str, *, up_min: float, down_max: float) -> bool:
        if not self.consensus:
            return False
        if side == "UP":
            return self.delta_usd >= up_min
        if side == "DOWN":
            return self.delta_usd <= down_max
        return False

    def describe(self) -> str:
        return (
            f"btc Δ={self.delta_usd:+.2f} px={self.current_price:.2f} "
            f"beat={self.price_to_beat:.2f} side={self.signal_side} "
            f"src={self.source} venues={self.venue_count} "
            f"consensus={'Y' if self.consensus else 'N'}"
        )


def _okx_spot() -> float:
    r = requests.get(
        "https://www.okx.com/api/v5/market/ticker",
        params={"instId": "BTC-USDT"},
        timeout=3,
    )
    r.raise_for_status()
    return float(r.json()["data"][0]["last"])


def _okx_open(start_ts: float) -> float:
    after_ms = int((start_ts + 60) * 1000)
    r = requests.get(
        "https://www.okx.com/api/v5/market/history-candles",
        params={"instId": "BTC-USDT", "bar": "1m", "after": str(after_ms), "limit": "3"},
        timeout=3,
    )
    r.raise_for_status()
    rows = r.json().get("data") or []
    target = int(start_ts * 1000)
    for row in rows:
        if int(row[0]) == target:
            return float(row[1])
    if rows:
        rows = sorted(rows, key=lambda x: abs(int(x[0]) - target))
        return float(rows[0][1])
    raise RuntimeError("okx: no candle for window open")


def _coinbase_spot() -> float:
    r = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=3)
    r.raise_for_status()
    return float(r.json()["data"]["amount"])


def _kraken_spot() -> float:
    r = requests.get(
        "https://api.kraken.com/0/public/Ticker",
        params={"pair": "XBTUSD"},
        timeout=3,
    )
    r.raise_for_status()
    return float(r.json()["result"]["XXBTZUSD"]["c"][0])


def _kraken_open(start_ts: float) -> float:
    r = requests.get(
        "https://api.kraken.com/0/public/OHLC",
        params={"pair": "XBTUSD", "interval": 1, "since": int(start_ts) - 60},
        timeout=3,
    )
    r.raise_for_status()
    rows = r.json()["result"]["XXBTZUSD"]
    target = int(start_ts)
    for row in rows:
        if int(row[0]) == target:
            return float(row[1])
    if rows:
        rows = sorted(rows, key=lambda x: abs(int(x[0]) - target))
        return float(rows[0][1])
    raise RuntimeError("kraken: no candle for window open")


_SPOTTERS = {
    "okx": _okx_spot,
    "coinbase": _coinbase_spot,
    "kraken": _kraken_spot,
}
_OPENERS = {
    "okx": _okx_open,
    "kraken": _kraken_open,
}


def _hosts(cfg: Config) -> list[str]:
    return [h.strip().lower() for h in cfg.price_hosts.split(",") if h.strip()]


def _spot_all(cfg: Config) -> list[tuple[str, float]]:
    now = time.time()
    out: list[tuple[str, float]] = []
    for host in _hosts(cfg):
        fn = _SPOTTERS.get(host)
        if not fn:
            continue
        cached = _spot_cache.get(host)
        if cached and now - cached[0] <= 0.8:
            out.append((host, cached[1]))
            continue
        try:
            px = fn()
            _spot_cache[host] = (now, px)
            out.append((host, px))
        except Exception:  # noqa: BLE001
            continue
    return out


def _open_price(cfg: Config, market: LiveMarket) -> tuple[float, str]:
    key = int(market.start_ts)
    cached = _open_cache.get(key)
    if cached:
        return cached

    errors: list[str] = []
    for host in _hosts(cfg):
        fn = _OPENERS.get(host)
        if not fn:
            continue
        try:
            px = fn(market.start_ts)
            out = (px, host)
            _open_cache[key] = out
            return out
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{host}:{exc}")

    spots = _spot_all(cfg)
    if not spots:
        raise RuntimeError("open price failed: " + "; ".join(errors))
    px = statistics.median([p for _, p in spots])
    out = (px, "median-spot-fallback")
    _open_cache[key] = out
    return out


def _side_from_delta(delta: float, cfg: Config) -> str:
    if delta >= cfg.up_min_delta_usd:
        return "UP"
    if delta <= cfg.down_max_delta_usd:
        return "DOWN"
    return "FLAT"


def fetch_btc_signal(cfg: Config, market: LiveMarket) -> BtcSignal:
    beat, open_src = _open_price(cfg, market)
    spots = _spot_all(cfg)
    if not spots:
        raise RuntimeError("spot price failed on all venues")

    values = [p for _, p in spots]
    spot = statistics.median(values)
    delta = spot - beat
    side = _side_from_delta(delta, cfg)

    # Per-venue sides for consensus (same beat). Directed venues must agree.
    venue_sides = [_side_from_delta(p - beat, cfg) for _, p in spots]
    if cfg.signal_require_consensus and side in {"UP", "DOWN"}:
        directed = [s for s in venue_sides if s != "FLAT"]
        consensus = bool(directed) and all(s == side for s in directed)
    else:
        consensus = True

    names = "+".join(h for h, _ in spots)
    return BtcSignal(
        ts=time.time(),
        source=f"median({names})/{open_src}",
        price_to_beat=beat,
        current_price=spot,
        delta_usd=delta,
        signal_side=side,
        venue_count=len(spots),
        consensus=consensus,
    )
