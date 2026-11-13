"""Polymarket crypto fee helpers (crypto_fees_v2)."""
from __future__ import annotations


def taker_fee_per_share(price: float, fee_rate: float = 0.07) -> float:
    """fee = rate × p × (1 − p). Makers pay 0."""
    p = min(max(float(price), 0.0), 1.0)
    return float(fee_rate) * p * (1.0 - p)


def taker_fee_usd(price: float, size: float, fee_rate: float = 0.07) -> float:
    return taker_fee_per_share(price, fee_rate) * max(float(size), 0.0)


def maker_rebate_estimate(
    taker_fees_in_window_usd: float,
    *,
    rebate_rate: float = 0.20,
    maker_share: float = 1.0,
) -> float:
    """Rough rebate share of window taker fees (shared among makers)."""
    return max(taker_fees_in_window_usd, 0.0) * rebate_rate * min(max(maker_share, 0.0), 1.0)


def net_edge_after_taker_fee(ask: float, fee_rate: float = 0.07) -> float:
    return 1.0 - float(ask) - taker_fee_per_share(ask, fee_rate)
