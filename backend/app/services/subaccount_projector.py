"""Sub-account response projection: walk response payloads and multiply
monetary fields by the sub's multiplier so subs see their proportional share.

Conservative whitelist — only known monetary/quantity field names are scaled.
Field names that look like rates (price, percent, ratio, *_rate) are NEVER
scaled, since they reflect market conditions not holdings.
"""
from __future__ import annotations
from typing import Any

# Field names whose values are treated as monetary / size and get multiplied.
# Matched case-insensitively against the *exact* dict key.
_SCALE_FIELDS = {
    # balance / asset family
    "balance", "available_balance", "frozen_assets", "frozen_balance",
    "total_assets", "total_assets_usdt", "total_balance", "wallet_balance",
    "net_assets", "equity", "available_equity",
    "binance_net_asset", "bybit_mt5_net_asset",
    # pnl / fee family
    "pnl", "realized_pnl", "unrealized_pnl", "cumulative_pnl", "net_pnl",
    "binance_pnl", "binance_funding", "mt5_pnl", "mt5_swap", "mt5_commission",
    "funding_fee", "commission", "swap",
    "max_drawdown", "max_runup",
    # position size / margin
    "size", "qty", "position_qty", "position_amt", "notional",
    "initial_margin", "maintenance_margin", "margin", "isolated_margin",
    # cash flow
    "amount", "deposit", "withdraw", "transfer",
    # generic profit metrics
    "profit", "estimated_profit",
}

# Field names that must NOT be scaled even if they look monetary
_NEVER_SCALE = {
    "price", "mark_price", "entry_price", "liquidation_price", "avg_price",
    "tick_size", "step_size", "qty_step", "qty_precision", "price_precision",
    "qty_unit", "min_qty", "contract_unit",
    "fee_rate", "maker_fee_rate", "taker_fee_rate", "fee_per_lot",
    "margin_rate", "margin_rate_initial", "margin_rate_maintenance",
    "leverage", "spread", "forward_spread", "reverse_spread",
    "fx_cny_to_usdt", "fx_rate", "usd_usdt_rate",
    "ratio", "percent", "percentage",
    "win_rate", "annualized", "annual_return",
    "shares", "multiplier", "nav_per_share", "nav_per_share_at_join",
    "invested_cny", "invested_usdt", "invested_cny", "invested_usdt",
    # counts
    "count", "trade_count", "win_count", "broadcast_count",
    "platform_id", "user_id", "id", "account_id",
    # timestamps
    "ts", "timestamp", "created_at", "updated_at", "snapshot_time",
    "start_at", "end_at", "create_time", "update_time",
}


def _should_scale(key: str) -> bool:
    k = key.lower()
    if k in _NEVER_SCALE:
        return False
    if k in _SCALE_FIELDS:
        return True
    # Pattern: ends with _pnl / _balance / _amount / _profit / _margin / _equity
    for suffix in ("_pnl", "_balance", "_amount", "_profit", "_margin",
                   "_equity", "_assets", "_value_usdt", "_funding"):
        if k.endswith(suffix):
            return True
    return False


def project_response(obj: Any, multiplier: float) -> Any:
    """Recursively walk dict/list/tuple, scaling matching numeric fields.

    Strings, bools, None are passed through unchanged. Numeric values under
    matching keys are multiplied; others kept verbatim.
    """
    if multiplier is None or multiplier == 1.0:
        return obj
    return _walk(obj, float(multiplier))


def _walk(obj: Any, m: float) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _should_scale(k) and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = float(v) * m
            else:
                out[k] = _walk(v, m)
        return out
    if isinstance(obj, list):
        return [_walk(x, m) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_walk(x, m) for x in obj)
    return obj
