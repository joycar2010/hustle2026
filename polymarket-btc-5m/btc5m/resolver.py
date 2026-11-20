"""Resolve closed BTC 5m markets for PnL booking."""
from __future__ import annotations

import json
from typing import Optional

import requests

from btc5m.markets import LiveMarket


def gamma_winner_side(gamma_host: str, market: LiveMarket) -> Optional[str]:
    """Return UP/DOWN when Gamma marks the market closed with a winner."""
    r = requests.get(f"{gamma_host}/events/slug/{market.market_slug}", timeout=5)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    event = r.json()
    markets = event.get("markets") or []
    if not markets:
        return None
    m = markets[0]
    if not m.get("closed"):
        return None

    # Prefer explicit outcome prices: winning side ~1.0
    raw_prices = m.get("outcomePrices")
    outcomes = m.get("outcomes")
    if raw_prices and outcomes:
        prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
        names = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        if len(prices) == len(names) == 2:
            try:
                nums = [float(p) for p in prices]
            except (TypeError, ValueError):
                nums = []
            if nums and max(nums) >= 0.95:
                winner = names[nums.index(max(nums))].strip().upper()
                if winner in {"UP", "DOWN"}:
                    return winner

    # Fallback: umaResolutionStatus / winner fields when present
    for key in ("winner", "resolvedOutcome", "resolution"):
        val = str(m.get(key) or "").strip().upper()
        if val in {"UP", "DOWN"}:
            return val
    return None


def paper_pnl(side: str, size: float, entry_price: float, winner: str) -> float:
    """Binary payout: winner shares redeem at $1, loser at $0."""
    if side.upper() == winner.upper():
        return size * (1.0 - entry_price)
    return -size * entry_price
