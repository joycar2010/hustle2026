"""Discover the live Polymarket BTC 5-minute Up/Down market."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

WINDOW_SEC = 300


@dataclass(frozen=True)
class LiveMarket:
    condition_id: str
    market_slug: str
    title: str
    up_token: str
    down_token: str
    start_ts: float
    end_ts: float
    tick_size: float
    min_size: float
    neg_risk: bool
    enable_order_book: bool

    def t_remaining(self, now: Optional[float] = None) -> float:
        return self.end_ts - (now if now is not None else time.time())

    def t_elapsed(self, now: Optional[float] = None) -> float:
        return (now if now is not None else time.time()) - self.start_ts


def window_start_ts(now: Optional[float] = None) -> int:
    ts = int(now if now is not None else time.time())
    return ts - (ts % WINDOW_SEC)


def _iso_to_unix(value: str) -> float:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).timestamp()


def _parse_market(event: dict, market: dict) -> Optional[LiveMarket]:
    raw_tokens = market.get("clobTokenIds")
    if not raw_tokens:
        return None
    tokens = json.loads(raw_tokens) if isinstance(raw_tokens, str) else raw_tokens
    if len(tokens) != 2:
        return None

    start_iso = market.get("eventStartTime") or event.get("startTime")
    end_iso = market.get("endDate") or event.get("endDate")
    if not start_iso or not end_iso:
        return None

    return LiveMarket(
        condition_id=str(market["conditionId"]),
        market_slug=str(market.get("slug") or event.get("slug") or ""),
        title=str(event.get("title") or market.get("question") or ""),
        up_token=str(tokens[0]),
        down_token=str(tokens[1]),
        start_ts=_iso_to_unix(start_iso),
        end_ts=_iso_to_unix(end_iso),
        tick_size=float(market.get("orderPriceMinTickSize") or 0.01),
        min_size=float(market.get("orderMinSize") or 5),
        neg_risk=bool(market.get("negRisk", False)),
        enable_order_book=bool(market.get("enableOrderBook", True)),
    )


def fetch_market_by_slug(gamma_host: str, slug: str) -> Optional[LiveMarket]:
    url = f"{gamma_host}/events/slug/{slug}"
    r = requests.get(url, timeout=5)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    event = r.json()
    markets = event.get("markets") or []
    if not markets:
        return None
    return _parse_market(event, markets[0])


def fetch_live_market(gamma_host: str, series_slug: str = "btc-up-or-down-5m") -> Optional[LiveMarket]:
    """Return the currently open BTC 5m market, preferring exact slug lookup."""
    now = time.time()
    # Prefer direct slug: btc-updown-5m-<unix_start>
    for offset in (0, -WINDOW_SEC, WINDOW_SEC):
        start = window_start_ts(now + offset)
        slug = f"btc-updown-5m-{start}"
        market = fetch_market_by_slug(gamma_host, slug)
        if market and market.start_ts <= now < market.end_ts and market.enable_order_book:
            return market

    # Fallback: scan series feed
    r = requests.get(
        f"{gamma_host}/events",
        params={
            "series_slug": series_slug,
            "closed": "false",
            "limit": 100,
            "order": "startTime",
            "ascending": "false",
        },
        timeout=8,
    )
    r.raise_for_status()
    candidates: list[LiveMarket] = []
    for event in r.json():
        for market in event.get("markets") or []:
            parsed = _parse_market(event, market)
            if (
                parsed
                and parsed.start_ts <= now < parsed.end_ts
                and parsed.enable_order_book
            ):
                candidates.append(parsed)
    if not candidates:
        return None
    candidates.sort(key=lambda m: m.start_ts, reverse=True)
    return candidates[0]


def next_window_eta(now: Optional[float] = None) -> float:
    ts = now if now is not None else time.time()
    return WINDOW_SEC - (ts % WINDOW_SEC)


def fmt_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
