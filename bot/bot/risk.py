"""Risk caps and position sizing."""
from __future__ import annotations

import math
import time
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Optional

import requests

from bot.config import Config
from bot.store import (
    consecutive_losses,
    open_positions_count,
    order_attempts_since,
    realized_pnl_today,
)

PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
ERC20_BALANCE_OF = "0x70a08231"

_balance_cache: tuple[float, Optional[float]] = (0.0, None)


def pusd_balance(cfg: Config, ttl_sec: float = 5.0) -> Optional[float]:
    """Return deposit wallet pUSD balance, cached briefly to avoid RPC spam."""
    global _balance_cache
    ts, val = _balance_cache
    now = time.time()
    if val is not None and now - ts <= ttl_sec:
        return val

    data = ERC20_BALANCE_OF + cfg.funder_address.lower().replace("0x", "").rjust(64, "0")
    try:
        r = requests.post(
            cfg.polygon_rpc,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_call",
                "params": [{"to": PUSD, "data": data}, "latest"],
            },
            timeout=5,
        )
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(body["error"])
        raw = body.get("result")
        if not raw:
            return None
        val = int(raw, 16) / 1e6
        _balance_cache = (now, val)
        return val
    except Exception:
        return None


def account_equity_usd(cfg: Config, dry_run: bool) -> Optional[float]:
    if dry_run:
        return cfg.paper_equity_usd
    balance = pusd_balance(cfg)
    if balance is not None:
        return balance
    return None


def target_order_size(
    cfg: Config,
    *,
    ask_price: float,
    ask_size: float,
    equity_usd: Optional[float],
    fee_per_share: float = 0.0,
    risk_fraction: Optional[float] = None,
) -> float:
    """Size the FOK order by dollar notional, then convert to outcome shares."""
    if equity_usd is None or equity_usd <= 0 or ask_price <= 0:
        return cfg.effective_min_order_notional_usd / ask_price

    budget = (
        cfg.order_fixed_notional_usd
        if cfg.order_fixed_notional_usd > 0
        else equity_usd * (cfg.order_risk_fraction if risk_fraction is None else risk_fraction)
    )
    per_share_cost = ask_price + max(fee_per_share, 0.0)
    # Market BUY orders are submitted by maker notional. Size the minimum from
    # ask_price so the eventual order amount can satisfy the CLOB $1 floor; the
    # fee is still used for the risk-budget target below.
    min_size = math.ceil((cfg.effective_min_order_notional_usd / ask_price) * 10_000) / 10_000
    budget_size = budget / per_share_cost

    if ask_size <= 0:
        return min_size

    size = min(max(budget_size, min_size), ask_size)
    if (
        risk_fraction is not None
        and risk_fraction >= 1.0
        and cfg.order_fixed_notional_usd <= 0
        and ask_size >= budget_size
    ):
        rounded_size = math.ceil((size - 1e-12) * 10_000) / 10_000
    else:
        rounded_size = math.floor((size + 1e-12) * 10_000) / 10_000
    if rounded_size < min_size <= ask_size:
        return min_size
    return rounded_size


def order_amount_usd_from_size(ask_price: float, size: float) -> float:
    """CLOB market BUY maker amount must have at most 2 decimals."""
    if ask_price <= 0 or size <= 0:
        return 0.0
    return math.floor(ask_price * size * 100) / 100


def shares_from_order_amount(ask_price: float, amount_usd: float) -> float:
    if ask_price <= 0 or amount_usd <= 0:
        return 0.0
    return math.floor((amount_usd / ask_price) * 10_000) / 10_000


def _floor_decimal(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_FLOOR)


def _ceil_decimal(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_CEILING)


def _decimal_places(value: Decimal) -> int:
    normalized = value.normalize()
    return max(0, -normalized.as_tuple().exponent)


def _market_rounding_for_tick(tick_size: float) -> tuple[int, int]:
    """Return py-clob-client-v2 market-order price and amount precision."""
    tick = format(Decimal(str(tick_size)).normalize(), "f")
    rounding = {
        "0.1": (1, 3),
        "0.01": (2, 4),
        "0.005": (3, 5),
        "0.0025": (4, 6),
        "0.001": (3, 5),
        "0.0001": (4, 6),
    }
    return rounding.get(tick, (2, 4))


def _client_market_buy_taker_amount(
    ask_price: Decimal,
    amount_usd: Decimal,
    tick_size: float,
) -> Decimal:
    """Mirror py-clob-client-v2 BUY market-order rounding before signing."""
    price_places, amount_places = _market_rounding_for_tick(tick_size)
    raw_price = _floor_decimal(ask_price, price_places)
    if raw_price <= 0:
        return Decimal("0")

    maker_amount = _floor_decimal(amount_usd, 2)
    taker_amount = maker_amount / raw_price
    if _decimal_places(taker_amount) > amount_places:
        taker_amount = _ceil_decimal(taker_amount, amount_places + 4)
        if _decimal_places(taker_amount) > amount_places:
            taker_amount = _floor_decimal(taker_amount, amount_places)
    return taker_amount


def market_buy_amount_and_shares(
    ask_price: float,
    size: float,
    *,
    tick_size: float,
    min_notional_usd: float,
) -> tuple[float, float]:
    """Choose a market BUY amount that satisfies Polymarket's 2/4 precision caps.

    The CLOB rejects market BUY orders when maker USDC has more than 2 decimals
    or taker shares have more than 4 decimals. Search downward by cents so the
    order stays under the risk budget and never raises the user's FOK price.
    """
    if ask_price <= 0 or size <= 0:
        return 0.0, 0.0

    price = Decimal(str(ask_price))
    max_amount = _floor_decimal(price * Decimal(str(size)), 2)
    min_cents = int((Decimal(str(min_notional_usd)) * Decimal("100")).to_integral_value(rounding=ROUND_CEILING))
    max_cents = int((max_amount * Decimal("100")).to_integral_value(rounding=ROUND_FLOOR))

    for cents in range(max_cents, min_cents - 1, -1):
        amount = Decimal(cents) / Decimal("100")
        taker_amount = _client_market_buy_taker_amount(price, amount, tick_size)
        if taker_amount <= 0:
            continue
        if _decimal_places(amount) <= 2 and _decimal_places(taker_amount) <= 4:
            return float(amount), float(taker_amount)

    return 0.0, 0.0


def allowed_to_trade(
    cfg: Config,
    dry_run: bool,
    *,
    equity_usd: Optional[float] = None,
    order_cost_usd: Optional[float] = None,
    risk_fraction: Optional[float] = None,
) -> tuple[bool, str]:
    if cfg.max_orders_per_hour > 0:
        hourly_attempts = order_attempts_since(time.time() - 3600.0, dry_run)
        if hourly_attempts >= cfg.max_orders_per_hour:
            return False, f"hourly order cap ({hourly_attempts}/{cfg.max_orders_per_hour}) reached"

    if cfg.max_open_positions > 0:
        open_positions = open_positions_count(dry_run)
        if open_positions >= cfg.max_open_positions:
            return False, f"max_open_positions ({open_positions}/{cfg.max_open_positions}) reached"

    if equity_usd is None:
        equity_usd = account_equity_usd(cfg, dry_run)
    if equity_usd is None:
        return False, "could not read pUSD balance for live risk check"
    if equity_usd <= 0:
        return False, f"equity ${equity_usd:.2f} <= 0"

    pnl = realized_pnl_today(dry_run)
    if cfg.max_daily_loss_fraction > 0:
        daily_loss_limit = equity_usd * cfg.max_daily_loss_fraction
        if pnl <= -daily_loss_limit:
            return False, f"daily loss ${pnl:.2f} <= -{cfg.max_daily_loss_fraction:.0%} (${daily_loss_limit:.2f})"

    if order_cost_usd is not None:
        effective_risk_fraction = cfg.order_risk_fraction if risk_fraction is None else risk_fraction
        if cfg.order_fixed_notional_usd > 0:
            max_cost = cfg.order_fixed_notional_usd
        else:
            percentage_cost = equity_usd * effective_risk_fraction
            min_order_floor = (
                cfg.effective_min_order_notional_usd
                if equity_usd >= cfg.effective_min_order_notional_usd
                else 0.0
            )
            max_cost = max(percentage_cost, min_order_floor)
        if order_cost_usd > max_cost + 1e-9:
            if cfg.order_fixed_notional_usd > 0:
                return False, f"order cost ${order_cost_usd:.2f} > fixed notional (${max_cost:.2f})"
            return False, f"order cost ${order_cost_usd:.2f} > {effective_risk_fraction:.1%} equity/min floor (${max_cost:.2f})"

    streak = consecutive_losses(dry_run)
    if cfg.consecutive_loss_kill > 0 and streak >= cfg.consecutive_loss_kill:
        return False, f"consecutive losses ({streak}) >= kill threshold"
    return True, "ok"


def daily_realized_profit_stop_reason(
    cfg: Config,
    dry_run: bool,
) -> Optional[str]:
    """Return a stop reason when today's realized profit reaches the live cap."""
    if dry_run or cfg.max_daily_realized_profit_usd <= 0:
        return None

    pnl = realized_pnl_today(dry_run)
    if pnl >= cfg.max_daily_realized_profit_usd:
        return (
            f"daily realized profit ${pnl:.2f} >= "
            f"${cfg.max_daily_realized_profit_usd:.2f}"
        )
    return None
