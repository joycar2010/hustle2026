"""Kalshi daily high-temperature markets as WeatherMarket objects.

Market data and settlement endpoints are public (no key).  Each bracket of a
KXHIGH* series becomes a bot.weather_markets.WeatherMarket, so the existing
ensemble signal (build_signal) and the paper entry hook consume them without
modification.  Tokens are synthetic ("kalshi:<ticker>:yes|no") and
settlement is polled from the same public API into the local resolutions
table.  We never authenticate to or trade on Kalshi -- reference prices and
outcomes only, with all paper orders in our own ledger.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from typing import Optional

import requests

from bot import store
from bot.weather_markets import WeatherMarket

log = logging.getLogger("bot.feeds.kalshi")

KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"
# series -> our CITY_CONFIG key; unknown mappings are skipped silently.
DEFAULT_SERIES = "KXHIGHNY:nyc,KXHIGHCHI:chicago,KXHIGHMIA:miami,KXHIGHLAX:los_angeles,KXHIGHDEN:denver"
_EVENT_DATE_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})-")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def _series_map() -> dict[str, str]:
    raw = os.environ.get("KALSHI_WEATHER_SERIES", DEFAULT_SERIES)
    out: dict[str, str] = {}
    for part in raw.split(","):
        if ":" in part:
            series, city = part.split(":", 1)
            out[series.strip().upper()] = city.strip()
    return out


def _target_date(ticker: str) -> Optional[date]:
    m = _EVENT_DATE_RE.search(ticker)
    if not m:
        return None
    yy, mon, dd = m.groups()
    month = _MONTHS.get(mon)
    if not month:
        return None
    return date(2000 + int(yy), month, int(dd))


def _mid_price(m: dict) -> Optional[float]:
    """Yes-side mid in [0.01, 0.99] dollars, or None when unquoted."""
    bid, ask = m.get("yes_bid"), m.get("yes_ask")
    if bid and ask and 0 < bid <= 100 and 0 < ask <= 100:
        return round((bid + ask) / 200.0, 4)
    last = m.get("last_price")
    if last and 0 < last < 100:
        return round(last / 100.0, 4)
    return None


# Last-fetch observability: how many brackets were scanned vs carried a
# quote.  Temperature series list quotes only during US market hours, so
# "scanned 60 / quoted 0" is a legitimate overnight state, not a failure.
LAST_STATS: dict[str, int] = {"scanned": 0, "quoted": 0}


def fetch_kalshi_weather_markets(timeout: float = 8.0) -> list[WeatherMarket]:
    out: list[WeatherMarket] = []
    scanned = 0
    for series, city_key in _series_map().items():
        try:
            r = requests.get(
                f"{KALSHI_BASE}/markets",
                params={"series_ticker": series, "status": "open", "limit": 100},
                timeout=timeout,
            )
            r.raise_for_status()
            rows = r.json().get("markets") or []
        except Exception as exc:
            log.debug("kalshi series %s fetch failed: %s", series, exc)
            continue
        scanned += len(rows)
        for m in rows:
            ticker = str(m.get("ticker") or "")
            tdate = _target_date(ticker)
            yes_price = _mid_price(m)
            strike_type = str(m.get("strike_type") or "")
            floor_strike = m.get("floor_strike")
            cap_strike = m.get("cap_strike")
            if not ticker or tdate is None or yes_price is None:
                continue
            if strike_type == "greater" and floor_strike is not None:
                kind, threshold, upper = "above", float(floor_strike), None
            elif strike_type == "less" and cap_strike is not None:
                kind, threshold, upper = "below", float(cap_strike), None
            elif floor_strike is not None and cap_strike is not None:
                kind, threshold, upper = "between", float(floor_strike), float(cap_strike)
            else:
                continue
            out.append(WeatherMarket(
                condition_id=f"kalshi:{ticker}",
                market_id=ticker,
                slug=f"kalshi-{ticker.lower()}",
                question=str(m.get("title") or ticker),
                city_key=city_key,
                target_date=tdate,
                metric="high_temp",
                kind=kind,
                threshold_f=threshold,
                upper_threshold_f=upper,
                yes_token=f"kalshi:{ticker}:yes",
                no_token=f"kalshi:{ticker}:no",
                yes_price=yes_price,
                no_price=round(1.0 - yes_price, 4),
                tick_size=0.01,
            ))
    LAST_STATS["scanned"] = scanned
    LAST_STATS["quoted"] = len(out)
    return out


def resolve_kalshi_settlements(timeout: float = 8.0) -> int:
    """Record resolutions for our unresolved kalshi:* paper entries."""
    resolved = 0
    pending = [cid for cid, _slug in store.unresolved_with_slug(True)
               if cid.startswith("kalshi:")]
    for cid in pending[:40]:
        ticker = cid.split(":", 1)[1]
        try:
            r = requests.get(f"{KALSHI_BASE}/markets/{ticker}", timeout=timeout)
            r.raise_for_status()
            m = (r.json() or {}).get("market") or {}
        except Exception:
            continue
        if str(m.get("status")) not in ("finalized", "settled"):
            continue
        result = str(m.get("result") or "").lower()
        if result not in ("yes", "no"):
            continue
        winner = f"{cid}:{result}"
        store.record_resolution(cid, winner)
        log.info("kalshi settled %s -> %s", ticker, result)
        resolved += 1
    return resolved
