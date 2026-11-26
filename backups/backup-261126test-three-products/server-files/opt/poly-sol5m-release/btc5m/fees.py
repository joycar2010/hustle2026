"""Paper fee estimates and execution impact, not chain-paid invoices."""
from __future__ import annotations


def taker_fee_per_share(price: float, fee_rate: float = 0.07) -> float:
    """fee = rate × p × (1 − p). Makers pay 0."""
    p = min(max(float(price), 0.0), 1.0)
    return float(fee_rate) * p * (1.0 - p)


def taker_fee_usd(price: float, size: float, fee_rate: float = 0.07) -> float:
    return taker_fee_per_share(price, fee_rate) * max(float(size), 0.0)


def paper_slipped_price(
    price: float,
    *,
    tick_size: float = 0.01,
    ticks: float = 1.0,
    pct: float = 0.0,
) -> float:
    """Apply adverse buy-side Paper slippage.

    ``ticks`` models a fixed CLOB tick impact and ``pct`` an optional
    proportional impact.  The larger configured impact is used and prices
    remain inside the usable binary-market range.
    """
    p = min(max(float(price), 0.0), 1.0)
    tick = max(float(tick_size), 0.0)
    move = max(max(float(ticks), 0.0) * tick, p * max(float(pct), 0.0))
    upper = max(0.0, 1.0 - tick)
    return min(upper, p + move)


def paper_slipped_sell_price(
    price: float,
    *,
    tick_size: float = 0.01,
    ticks: float = 1.0,
    pct: float = 0.0,
) -> float:
    """Apply adverse sell-side Paper slippage.

    The existing :func:`paper_slipped_price` models buys.  For a sell, the
    adverse direction is lower proceeds, so the same movement is subtracted.
    Keeping this as a separate helper makes the direction explicit at call
    sites and prevents accidental double subtraction from PnL.
    """
    p = min(max(float(price), 0.0), 1.0)
    tick = max(float(tick_size), 0.0)
    move = max(max(float(ticks), 0.0) * tick, p * max(float(pct), 0.0))
    lower = min(1.0, tick) if tick > 0 else 0.0
    return max(lower, p - move)


def paper_sell_execution(book, size: float, *, tick_size: float = 0.01,
                         ticks: float = 1.0, pct: float = 0.0) -> dict[str, float]:
    """Conservative top-bid execution; never invent unavailable depth.

    The adverse impact is in the effective proceeds. Its audit column must
    not be deducted from PnL again. Maker limit fills do not use this helper.
    """
    from math import isfinite
    bid = float(book.best_bid or 0.0)
    depth = float(book.bid_size or 0.0)
    requested = float(size)
    if not all(isfinite(x) for x in (bid, depth, requested)) or bid <= 0 or depth <= 0 or requested <= 0:
        return {"size": 0.0, "raw_price": max(bid, 0.0) if isfinite(bid) else 0.0,
                "price": 0.0, "slippage_usd": 0.0}
    filled = min(requested, depth)
    price = paper_slipped_sell_price(bid, tick_size=tick_size, ticks=ticks, pct=pct)
    price = min(price, bid)
    return {"size": filled, "raw_price": bid, "price": price,
            "slippage_usd": filled * max(bid - price, 0.0)}


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
