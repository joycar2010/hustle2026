"""Main event loop. Dry-run by default; --live to actually trade."""
from __future__ import annotations

import argparse
import copy
import logging
import math
import re
import time
import threading
from bot.exit_supervisor import PriorityOrderGate, IndependentExitSupervisor
from bot.execution_costs import FeeSchedule, estimate_execution, evaluate_net_exit
from dataclasses import dataclass, replace
from typing import Optional

from bot import config, store
from bot.live_execution import LiveExecutionGuard
from bot.paper_profit import invalidate_paper_profit_cache
from bot.book import TopOfBook, fetch_book
from bot.kelly_shadow import SHADOW as KELLY_SHADOW
from bot.kelly_sizing import SIZING as KELLY_SIZING
from bot.loss_recovery import (
    RecoveryDecision,
    evaluate as evaluate_loss_cap_recovery,
    record_entry as record_loss_recovery_entry,
)
from bot.btc_signal import BtcSignal, fetch_btc_signal
from bot.markets import LiveMarket, fetch_live_market
from bot.orders import (
    CollateralBalance,
    OrderResult,
    build_client,
    get_collateral_balance_allowance,
    place_buy_fok,
    place_buy_market_fok,
    place_buy_maker,
    place_sell_fak,
    place_sell_fok,
    place_sell_maker,
    reconcile_recent_trade,
)
from bot.resolver import closed_market_winner_side, resolve_pending
from bot.rtds_signal import ensure_rtds_client
from bot.risk import (
    account_equity_usd,
    allowed_to_trade,
    daily_realized_profit_stop_reason,
    market_buy_amount_and_shares,
    target_order_size,
)
from bot.strategy import (
    Decision,
    StrategyState,
    buy_window_upper_sec,
    decide,
    btc_signal_allows_entry,
    btc_signal_entry_description,
    entry_price_bounds,
    entry_risk_fraction,
    price_source_guard_reason,
    required_net_edge,
    taker_fee_per_share,
)

log = logging.getLogger("bot")

CLOB_BUY_MIN_PRICE = 0.01
CLOB_BUY_MAX_PRICE = 0.99


def entry_guard_reversal_reason(
    cfg: config.Config,
    *,
    previous: Optional[tuple[float, float]],
    current_ts: float,
    current_delta: Optional[float],
    side: str,
) -> Optional[str]:
    """P1 guard against a rapid BTC delta reversal before entry."""
    if not bool(getattr(cfg, "entry_guard_enabled", True)):
        return None
    if current_delta is None or previous is None:
        return None
    previous_ts, previous_delta = previous
    window = max(float(getattr(cfg, "entry_guard_reversal_window_sec", 8.0)), 0.0)
    elapsed = max(float(current_ts) - float(previous_ts), 0.0)
    if window > 0 and elapsed > window:
        return None
    move = abs(float(current_delta) - float(previous_delta))
    max_move = max(float(getattr(cfg, "entry_guard_max_delta_move_usd", 20.0)), 0.0)
    sign_flip = (
        abs(float(previous_delta)) > 1e-9
        and abs(float(current_delta)) > 1e-9
        and float(previous_delta) * float(current_delta) < 0
    )
    if sign_flip and (max_move <= 0 or move >= max_move):
        return (
            f"{side} BTC delta reversed {previous_delta:+.2f}->{current_delta:+.2f} "
            f"in {elapsed:.1f}s; waiting for fresh confirmation"
        )
    if max_move > 0 and move >= max_move:
        return (
            f"{side} BTC delta moved {previous_delta:+.2f}->{current_delta:+.2f} "
            f"({move:.2f}) in {elapsed:.1f}s; waiting for fresh confirmation"
        )
    return None


def entry_guard_depth_reason(
    cfg: config.Config,
    *,
    visible_ask_size: Optional[float],
    requested_size: float,
) -> Optional[str]:
    """P1 guard requiring visible ask depth for the planned entry size."""
    if not bool(getattr(cfg, "entry_guard_enabled", True)):
        return None
    try:
        visible = float(visible_ask_size or 0.0)
        requested = max(float(requested_size or 0.0), 0.0)
    except (TypeError, ValueError):
        return "entry book depth unavailable"
    ratio = max(float(getattr(cfg, "entry_guard_min_depth_ratio", 1.0)), 0.0)
    required = requested * ratio
    if required > 0 and visible + 1e-9 < required:
        return (
            f"visible ask depth={visible:.4f} < required={required:.4f} "
            f"(size={requested:.4f}, ratio={ratio:.2f})"
        )
    return None


def _clob_min_exit_size(cfg: config.Config) -> float:
    """Return the smallest live sell size accepted by the CLOB."""
    try:
        configured = float(getattr(cfg, "effective_min_order_size_shares", 5.0))
    except (TypeError, ValueError):
        configured = 5.0
    return max(configured, 5.0)


def _profit_exit_enabled(cfg: config.Config) -> bool:
    """Support both the execution names and the historical take-profit names."""
    return bool(
        getattr(cfg, "profit_exit_enabled", False)
        or getattr(cfg, "take_profit_enabled", False)
    )


def _profit_target_fraction(cfg: config.Config) -> float:
    if getattr(cfg, "profit_exit_enabled", False):
        return max(float(getattr(cfg, "profit_target_fraction", 0.05)), 0.0)
    return max(float(getattr(cfg, "take_profit_min_gain_fraction", 0.05)), 0.0)


def _profit_exit_fraction(cfg: config.Config) -> float:
    if getattr(cfg, "profit_exit_enabled", False):
        return min(max(float(getattr(cfg, "profit_exit_fraction", 1.0)), 0.0), 1.0)
    return min(max(float(getattr(cfg, "take_profit_exit_fraction", 0.50)), 0.0), 1.0)


def retry_chase_block_reason(
    *,
    retry_side: Optional[str],
    retry_reference_price: Optional[float],
    order_limit_price: float,
    fresh_ask: float,
    tick_size: float,
    max_retry_price_drift_ticks: int,
) -> Optional[str]:
    """Return the retry price guard reason, or None when retrying is allowed.

    A negative drift setting disables this guard. Other entry safeguards still
    run after this check, including the configured price zone and time window.
    """
    if (
        max_retry_price_drift_ticks < 0
        or retry_side is None
        or retry_reference_price is None
    ):
        return None
    max_retry_drift = max(max_retry_price_drift_ticks, 0) * tick_size
    if order_limit_price <= retry_reference_price + max_retry_drift + 1e-9:
        return None
    return (
        f"retry limit={order_limit_price:.2f} > first_attempt={retry_reference_price:.2f} "
        f"+ drift={max_retry_drift:.2f}; fresh_ask={fresh_ask:.2f}"
    )


def buy_limit_price(
    *,
    fresh_ask: float,
    price_buffer: float,
    price_cap: float,
) -> float:
    """Apply the buy buffer without exceeding the configured price cap.

    At the cap itself, submit the cap directly. For the current BTC strategy
    this means an ask of 0.99 submits at 0.99 rather than attempting 1.00.
    """
    if fresh_ask >= price_cap - 1e-9:
        return price_cap
    return min(fresh_ask + max(price_buffer, 0.0), price_cap)


def _update_buy_retry_state(
    *,
    condition_id: str,
    retry_slot: str,
    retry_key: tuple[str, str, str],
    side: Optional[str],
    entry_rule: Optional[str],
    filled_size: float,
    bought_this_window: set[str],
    buy_retry_sides: dict[tuple[str, str], str],
    buy_retry_entry_rules: dict[tuple[str, str], str],
    buy_retry_reference_prices: dict[tuple[str, str, str], float],
) -> bool:
    """Update local buy state without treating failed orders as filled buys."""
    if filled_size > 0:
        buy_retry_sides.pop((condition_id, retry_slot), None)
        buy_retry_entry_rules.pop((condition_id, retry_slot), None)
        buy_retry_reference_prices.pop(retry_key, None)
        bought_this_window.add(condition_id)
        return True

    if side is not None:
        buy_retry_sides[(condition_id, retry_slot)] = side
        if entry_rule == "strong_normal_reverse":
            buy_retry_entry_rules[(condition_id, retry_slot)] = entry_rule
    return False


def _runtime_config_for_asset(cfg: config.Config, asset: str) -> config.Config:
    """Map the shared strategy engine onto BTC or ETH 5-minute markets."""
    asset = asset.upper()
    if asset == "BTC":
        return cfg
    if asset != "ETH":
        raise ValueError(f"unsupported asset: {asset}")
    return replace(
        cfg,
        series_slug=cfg.eth_series_slug,
        btc_delta_filter_enabled=cfg.eth_delta_filter_enabled,
        btc_delta_threshold_usd=cfg.eth_delta_threshold_usd,
        btc_up_min_delta_usd=cfg.eth_up_min_delta_usd,
        btc_up_max_delta_usd=cfg.eth_up_max_delta_usd,
        btc_down_min_delta_usd=cfg.eth_down_min_delta_usd,
        btc_down_max_delta_usd=cfg.eth_down_max_delta_usd,
        btc_price_symbol=cfg.eth_price_symbol,
        high_price_btc_delta_usd=cfg.eth_high_price_delta_usd,
        early_strong_delta_entry_up_min_delta_usd=cfg.eth_early_strong_delta_up_min_delta_usd,
        early_strong_delta_entry_down_max_delta_usd=cfg.eth_early_strong_delta_down_max_delta_usd,
        early_strong_delta_entry_risk_fraction=cfg.eth_early_strong_delta_risk_fraction,
        strong_delta_entry_up_min_delta_usd=cfg.eth_strong_delta_up_min_delta_usd,
        strong_delta_entry_down_max_delta_usd=cfg.eth_strong_delta_down_max_delta_usd,
        strong_delta_entry_risk_fraction=cfg.eth_strong_delta_risk_fraction,
        late_edge_entry_up_min_delta_usd=cfg.eth_late_edge_up_min_delta_usd,
        late_edge_entry_down_max_delta_usd=cfg.eth_late_edge_down_max_delta_usd,
        late_edge_entry_delta_filter_enabled=cfg.eth_late_edge_delta_filter_enabled,
        late_edge_entry_confirm_checks=cfg.eth_late_edge_confirm_checks,
        late_edge_entry_risk_fraction=cfg.eth_late_edge_risk_fraction,
        order_risk_fraction=cfg.eth_order_risk_fraction,
        stable_delta_entry_min_abs_delta_usd=cfg.eth_stable_delta_min_abs_usd,
        stable_delta_entry_max_abs_delta_usd=cfg.eth_stable_delta_max_abs_usd,
        stable_delta_entry_max_delta_move_usd=cfg.eth_stable_delta_max_move_usd,
        stable_delta_entry_risk_fraction=cfg.eth_order_risk_fraction,
        stable_delta_entry_enabled=cfg.eth_stable_delta_trade_enabled,
    )


def _opposite_side(side: str) -> str:
    return "DOWN" if side == "UP" else "UP"


def _effective_buy_sides(orders: list[dict]) -> set[str]:
    return {
        str(order.get("side") or "").upper()
        for order in orders
        if str(order.get("side") or "").upper() in ("UP", "DOWN")
    }


def _locked_market_side(orders: list[dict]) -> Optional[str]:
    """Return the only effective entry side, or None if unlocked/conflicted."""
    sides = _effective_buy_sides(orders)
    return next(iter(sides)) if len(sides) == 1 else None


def _book_for_side(side: str, book_up: TopOfBook, book_down: TopOfBook) -> TopOfBook:
    return book_up if side == "UP" else book_down


def _token_for_side(current: LiveMarket, side: str) -> str:
    return current.up_token if side == "UP" else current.down_token


def _strong_buy_order_for_market(
    current: LiveMarket,
    dry_run: bool,
) -> Optional[dict]:
    orders = store.effective_buy_orders_for_market(current.condition_id, dry_run)
    strong_orders = [
        order
        for order in orders
        if str(order.get("entry_rule") or "") in _STRONG_SCALE_ENTRY_RULES
    ]
    return strong_orders[-1] if strong_orders else None


def _strong_normal_reverse_decision_for_side(
    cfg: config.Config,
    current: LiveMarket,
    book_up: TopOfBook,
    book_down: TopOfBook,
    t_rem: float,
    side: str,
    reason: str,
) -> Decision:
    book = _book_for_side(side, book_up, book_down)
    ask = book.best_ask
    min_price = cfg.strong_normal_reverse_min_price
    max_price = cfg.strong_normal_reverse_max_price
    if ask is None:
        return Decision(
            action="SKIP_SCALE_REVERSE",
            side=side,
            token_id=_token_for_side(current, side),
            reason=f"{reason}; reverse {side} has no ask",
            entry_rule="strong_normal_reverse",
            risk_fraction=cfg.strong_normal_reverse_risk_fraction,
        )
    if ask < min_price or ask > max_price:
        return Decision(
            action="SKIP_SCALE_REVERSE",
            side=side,
            token_id=_token_for_side(current, side),
            price=ask,
            size=book.ask_size,
            reason=(
                f"{reason}; reverse {side} ask={ask:.2f} outside "
                f"{min_price:.2f}-{max_price:.2f}"
            ),
            entry_rule="strong_normal_reverse",
            risk_fraction=cfg.strong_normal_reverse_risk_fraction,
        )
    min_size = cfg.effective_min_order_notional_usd / max(ask, 1e-9)
    if book.ask_size < min_size:
        return Decision(
            action="SKIP_SCALE_REVERSE",
            side=side,
            token_id=_token_for_side(current, side),
            price=ask,
            size=book.ask_size,
            reason=(
                f"{reason}; reverse {side} ask_size={book.ask_size:.4f} "
                f"< min ${cfg.effective_min_order_notional_usd:.2f} ({min_size:.4f} sh)"
            ),
            entry_rule="strong_normal_reverse",
            risk_fraction=cfg.strong_normal_reverse_risk_fraction,
        )
    fee = taker_fee_per_share(cfg, ask)
    net_edge = 1.0 - ask - fee
    return Decision(
        action="BUY",
        side=side,
        token_id=_token_for_side(current, side),
        price=ask,
        size=cfg.effective_min_order_notional_usd / ask,
        fee=fee,
        net_edge=net_edge,
        entry_rule="strong_normal_reverse",
        risk_fraction=cfg.strong_normal_reverse_risk_fraction,
        reason=(
            f"{reason}; reverse {side} strong_normal_reverse ask={ask} "
            f"fee={fee:.4f} net_edge={net_edge:.4f} "
            f"book_size={book.ask_size} t_rem={t_rem:.1f}s "
            f"confirm={cfg.strong_normal_reverse_confirm_checks}x"
        ),
    )


def _apply_strong_normal_reverse(
    cfg: config.Config,
    current: LiveMarket,
    book_up: TopOfBook,
    book_down: TopOfBook,
    t_rem: float,
    dry_run: bool,
    scale_in_slot: Optional[str],
    decision: Decision,
) -> Decision:
    if (
        not cfg.strong_normal_reverse_enabled
        or scale_in_slot != "normal"
        or decision.action != "BUY"
        or decision.entry_rule not in _NORMAL_SCALE_ENTRY_RULES
        or decision.entry_rule == "strong_normal_reverse"
        or decision.side not in ("UP", "DOWN")
    ):
        return decision

    strong_order = _strong_buy_order_for_market(current, dry_run)
    if not strong_order:
        return decision
    strong_side = str(strong_order.get("side") or "")
    if decision.side != strong_side:
        return decision

    held_book = _book_for_side(strong_side, book_up, book_down)
    held_bid = held_book.best_bid
    if held_bid is None:
        return Decision(
            action="SKIP_SCALE_REVERSE",
            side=decision.side,
            token_id=decision.token_id,
            price=decision.price,
            reason=(
                f"strong->normal same-side add blocked; "
                f"{strong_side} held bid unavailable"
            ),
            entry_rule=decision.entry_rule,
            risk_fraction=decision.risk_fraction,
        )
    threshold = cfg.strong_normal_reverse_held_bid_threshold
    if held_bid > threshold:
        return decision

    reverse_side = _opposite_side(strong_side)
    return _strong_normal_reverse_decision_for_side(
        cfg,
        current,
        book_up,
        book_down,
        t_rem,
        reverse_side,
        (
            f"strong->normal same-side add replaced; strong {strong_side} "
            f"held_bid={held_bid:.2f} <= {threshold:.2f}"
        ),
    )


def _strong_normal_reverse_trigger(
    cfg: config.Config,
    current: LiveMarket,
    book_up: TopOfBook,
    book_down: TopOfBook,
    t_rem: float,
    dry_run: bool,
    scale_in_slot: Optional[str],
) -> Optional[Decision]:
    if not cfg.strong_normal_reverse_enabled or scale_in_slot != "normal":
        return None

    strong_order = _strong_buy_order_for_market(current, dry_run)
    if not strong_order:
        return None
    strong_side = str(strong_order.get("side") or "")
    if strong_side not in ("UP", "DOWN"):
        return None

    held_book = _book_for_side(strong_side, book_up, book_down)
    held_bid = held_book.best_bid
    if held_bid is None:
        return None
    threshold = cfg.strong_normal_reverse_held_bid_threshold
    if held_bid > threshold:
        return None

    reverse_side = _opposite_side(strong_side)
    return _strong_normal_reverse_decision_for_side(
        cfg,
        current,
        book_up,
        book_down,
        t_rem,
        reverse_side,
        (
            f"strong->normal reverse trigger; strong {strong_side} "
            f"held_bid={held_bid:.2f} <= {threshold:.2f}"
        ),
    )


def _effective_exit_status(status: str) -> str:
    return f"exit_{status}"


@dataclass(frozen=True)
class ExitAttemptPlan:
    order_type: str
    size: float
    price: float
    visible_size: float
    full_depth: bool


def _floor_size(value: float) -> float:
    return math.floor(max(float(value), 0.0) * 100) / 100


def _floor_price_to_tick(value: float, tick_size: float) -> float:
    tick = max(float(tick_size), 0.01)
    ticks = math.floor(max(float(value), tick) / tick + 1e-9)
    return round(max(ticks * tick, tick), 4)


def _sellable_bid_levels(
    cfg: config.Config,
    book: TopOfBook,
    tick_size: float,
    *,
    full_depth: bool = False,
) -> list[tuple[float, float]]:
    if book.best_bid is None:
        return []
    if full_depth:
        min_price = 0.0
    else:
        max_depth_ticks = max(
            int(getattr(cfg, "sell_exit_max_depth_ticks", 0)),
            int(getattr(cfg, "sell_fok_slippage_ticks", 0)),
            0,
        )
        min_price = _floor_price_to_tick(book.best_bid - max_depth_ticks * tick_size, tick_size)
    if book.bids:
        levels = [(float(level.price), float(level.size)) for level in book.bids]
    else:
        levels = [(float(book.best_bid), float(book.bid_size))]
    levels = [
        (_floor_price_to_tick(price, tick_size), max(float(size), 0.0))
        for price, size in levels
        if price >= min_price and size > 0
    ]
    levels.sort(key=lambda item: item[0], reverse=True)
    max_levels = max(int(getattr(cfg, "sell_exit_max_depth_levels", 0)), 0)
    if not full_depth and max_levels > 0:
        levels = levels[:max_levels]
    return levels


def _plan_exit_attempts(
    cfg: config.Config,
    *,
    book: TopOfBook,
    remaining_size: float,
    sell_fraction: float,
    tick_size: float,
) -> tuple[list[ExitAttemptPlan], float, float]:
    requested_size = _floor_size(remaining_size * min(max(float(sell_fraction), 0.0), 1.0))
    if requested_size <= 0:
        return [], requested_size, 0.0
    min_exit_size = _clob_min_exit_size(cfg)
    if requested_size + 1e-9 < min_exit_size:
        if remaining_size + 1e-9 < min_exit_size:
            return [], requested_size, 0.0
        requested_size = _floor_size(min_exit_size)
        if requested_size <= 0 or requested_size > remaining_size + 1e-9:
            return [], requested_size, 0.0
    residual = _floor_size(remaining_size - requested_size)
    if residual > 0 and residual + 1e-9 < min_exit_size:
        requested_size = _floor_size(remaining_size)
    levels = _sellable_bid_levels(cfg, book, tick_size, full_depth=True)
    visible_size = _floor_size(sum(size for _, size in levels))
    if not levels or visible_size <= 0:
        return [], requested_size, visible_size

    full_price = None
    cumulative = 0.0
    for price, size in levels:
        cumulative += size
        if cumulative + 1e-9 >= requested_size:
            full_price = price
            break

    base_price = full_price if full_price is not None else levels[-1][0]
    slippage_ticks = max(int(getattr(cfg, "sell_fok_slippage_ticks", 0)), 0)
    target_price = _floor_price_to_tick(base_price - slippage_ticks * tick_size, tick_size)
    attempts: list[ExitAttemptPlan] = []
    if full_price is not None:
        attempts.append(
            ExitAttemptPlan(
                order_type="FOK",
                size=requested_size,
                price=target_price,
                visible_size=visible_size,
                full_depth=True,
            )
        )
    if cfg.sell_exit_fak_fallback_enabled:
        attempts.append(
            ExitAttemptPlan(
                order_type="FAK",
                size=requested_size,
                price=target_price,
                visible_size=visible_size,
                full_depth=False,
            )
        )
    return attempts, requested_size, visible_size


def _filled_exit_values(
    result: OrderResult,
    *,
    requested_size: float,
    limit_price: float,
) -> tuple[float, float, float]:
    filled_size = _floor_size(min(float(result.filled_size or 0.0), requested_size))
    avg_price = float(result.avg_price or limit_price)
    filled_amount = (
        float(result.filled_amount)
        if result.filled_amount is not None
        else filled_size * avg_price
    )
    if filled_size <= 0:
        filled_amount = 0.0
    return filled_size, avg_price, filled_amount


def _combine_buy_results(
    maker: OrderResult,
    taker: OrderResult,
    *,
    target_size: float,
    maker_price: float,
    taker_price: float,
) -> OrderResult:
    """Merge a maker fill and its residual taker fallback.

    Position accounting must retain every real fill even if an execution
    fault exceeded the target. Two observations of the same order are
    cumulative evidence, however, and must never be summed twice.
    """
    target = max(float(target_size), 0.0)
    maker_size = max(float(maker.filled_size or 0.0), 0.0)
    taker_size = max(float(taker.filled_size or 0.0), 0.0)
    if maker.order_id and taker.order_id and str(maker.order_id).lower() == str(taker.order_id).lower():
        chosen = taker if taker_size >= maker_size else maker
        return replace(chosen, ambiguous=True, terminal=False, fallback_safe=False,
            remaining_size=None, error='Maker/fallback evidence references the same order; reconcile before another entry',
            raw={'maker': maker.raw, 'fallback': taker.raw,
                 'component_order_ids': [maker.order_id], 'duplicate_component_order': True})
    total_size = maker_size + taker_size
    maker_amount = (
        float(maker.filled_amount)
        if maker.filled_amount is not None
        else maker_size * float(maker.avg_price or maker_price)
    )
    taker_amount = (
        float(taker.filled_amount)
        if taker.filled_amount is not None
        else taker_size * float(taker.avg_price or taker_price)
    )
    total_amount = max(0.0, maker_amount + taker_amount)
    avg_price = total_amount / total_size if total_size > 0 else None
    status = "matched" if total_size >= target - 0.02 else str(taker.status or maker.status)
    order_id = taker.order_id or maker.order_id
    errors = [str(v) for v in (maker.error, taker.error) if v]
    return OrderResult(
        order_id=order_id,
        status=status,
        filled_size=total_size,
        error="; ".join(errors) or None,
        submitted=bool(maker.submitted or taker.submitted),
        ambiguous=bool(maker.ambiguous or taker.ambiguous or total_size > target + 1e-6),
        terminal=bool(maker.terminal and taker.terminal),
        fallback_safe=False,
        remaining_size=max(target - total_size, 0.0),
        raw={"maker": maker.raw, "fallback": taker.raw,
             "component_order_ids": [value for value in (maker.order_id, taker.order_id) if value]},
        avg_price=avg_price,
        filled_amount=total_amount,
    )


def _maker_fallback_size(result, *, target_size, total_budget, maker_price, taker_price, fee_per_share=0.):
    """Bound a fallback by proven cancelled shares AND its remaining budget."""
    if (result.ambiguous or not result.fallback_safe or not result.terminal
            or result.remaining_size is None):
        return 0.0
    filled = max(float(result.filled_size or 0.), 0.)
    shares = min(max(float(target_size) - filled, 0.), max(float(result.remaining_size), 0.))
    spent = (float(result.filled_amount) if result.filled_amount is not None
             else filled * float(result.avg_price or maker_price))
    unit_cost = max(float(taker_price), .01) + max(float(fee_per_share), 0.)
    return _floor_size(min(shares, max(float(total_budget) - spent, 0.) / unit_cost))


def _net_profit_exit_decision(cfg, market, book, position, executable_size, entry_price):
    """Allocate paid entry costs to executable shares, including partial exits."""
    schedule = FeeSchedule.from_market(getattr(market, 'fee_metadata', None) or {})
    total_size = max(float(getattr(position, 'remaining_size', executable_size)), float(executable_size))
    cost = getattr(position, 'entry_cost_remaining_usd', None)
    if cost is None:
        cost = total_size * entry_price
    paid = getattr(position, 'entry_fees_remaining_usd', None)
    if paid is None:
        paid = float(schedule.fee(total_size, entry_price, role='TAKER', conservative=True))
    estimate = estimate_execution(book, 'SELL', executable_size, max(market.tick_size, .01),
        schedule, now=time.time(), liquidity_role='TAKER', require_complete=True)
    return evaluate_net_exit(estimate, position_size=total_size, remaining_cost_usd=cost,
        entry_fees_usd=paid, target_fraction=_profit_target_fraction(cfg),
        profit_buffer_usd=max(getattr(cfg, 'profit_target_ticks', 2), 0) * max(market.tick_size, .01) * executable_size)


def _p2_entry_quote(cfg, market, book, size, price, rule, *, side=None, signal=None):
    """Final executable-depth/fee check; payout headroom is not a probability."""
    schedule = FeeSchedule.from_market(getattr(market, 'fee_metadata', None) or {})
    estimate = estimate_execution(book, 'BUY', size, price, schedule, now=time.time(),
        max_book_age_sec=getattr(cfg, 'ws_exit_max_book_age_sec', 1.5), require_complete=True)
    if not estimate.available:
        return estimate.reason, estimate
    minimum_fields = {'early_strong_delta': 'early_strong_delta_entry_min_t_remaining_sec',
        'strong_delta': 'strong_delta_entry_min_t_remaining_sec', 'late_edge': 'late_edge_entry_min_t_remaining_sec',
        'stable_delta': 'stable_delta_entry_min_t_remaining_sec', 'tail_price': 'tail_entry_min_t_remaining_sec',
        'mid_misprice': 'mid_entry_min_t_remaining_sec'}
    if market.t_remaining() < getattr(cfg, minimum_fields.get(rule, 'min_t_remaining_sec'), 0.):
        return 'entry_window_elapsed', estimate
    low, high = entry_price_bounds(cfg, rule, side)
    if not low - 1e-9 <= price <= high + 1e-9:
        return 'entry_price_outside_strategy', estimate
    if 1. - price - estimate.fee_usd / estimate.filled_size + 1e-9 < required_net_edge(cfg, price, rule):
        return 'fee_inclusive_payout_headroom_below_minimum', estimate
    if signal is not None and not btc_signal_allows_entry(cfg, signal, side, rule, price):
        return 'entry_signal_changed', estimate
    return None, estimate


class _IndependentExitInventory:
    """Apply asynchronous account reads without losing acknowledged exits.

    HTTP reconciliation runs against a detached copy. An exit changing the
    inventory while the request is in flight invalidates that older read.
    Quantity caps also protect the next read from lagging account indexes.
    """
    def __init__(self, cfg, client, provider, urgent):
        self.cfg, self.client, self.provider, self.urgent = cfg, client, provider, urgent
        self.lock = threading.RLock()
        self.states, self.revisions, self.busy, self.caps = {}, {}, set(), {}

    def _apply_caps(self, state):
        for position_key, position in list(state.local_positions.items()):
            cap = self.caps.get(position_key)
            if cap is None or position.entry_order_id != cap['entry_order_id']:
                continue
            if position.remaining_size > cap['remaining_size'] + 1e-8:
                ratio = cap['remaining_size'] / position.remaining_size
                position.remaining_size = cap['remaining_size']
                for field in ('entry_cost_remaining_usd', 'entry_fees_remaining_usd'):
                    value = getattr(position, field, None)
                    if value is not None:
                        setattr(position, field, value * ratio)
                if position.remaining_size <= .02:
                    state.local_positions.pop(position_key, None)

    def reconcile(self, market):
        key = market.condition_id
        with self.lock:
            if key in self.busy:
                return False
            state = self.states.get(key)
            revision = self.revisions.get(key, 0)
            candidate = StrategyState()
            candidate.reset_for_market(key)
            if state is not None:
                candidate.local_positions = {k: copy.copy(p) for k, p in state.local_positions.items()}
            guard = LiveExecutionGuard(self.cfg, self.client)
            candidate.live_execution_guard = guard
        guard.sync(market, candidate)
        with self.lock:
            if key in self.busy or self.revisions.get(key, 0) != revision:
                return False
            if state is None:
                state = candidate
                self.states[key] = state
            self._apply_caps(candidate)
            state.local_positions = candidate.local_positions
            state.live_execution_guard = guard
            state.live_authoritative = True
            state.urgent_exit_event = self.urgent
            state.execution_book_provider = self.provider
            self.revisions[key] = revision + 1
            return True

    def positions(self, market):
        with self.lock:
            state = self.states.get(market.condition_id)
            return [copy.copy(p) for p in state.local_positions.values()] if state else None

    def execute(self, market, callback):
        key = market.condition_id
        with self.lock:
            state = self.states.get(key)
            if state is None or key in self.busy:
                return False
            self.busy.add(key)
            self.revisions[key] = self.revisions.get(key, 0) + 1
            before = {k: copy.copy(p) for k, p in state.local_positions.items()}
        try:
            return callback(state)
        finally:
            with self.lock:
                for position_key, old in before.items():
                    current = state.local_positions.get(position_key)
                    remaining = current.remaining_size if current is not None else 0.
                    if remaining < old.remaining_size - 1e-8:
                        self.caps[position_key] = {'remaining_size': remaining,
                                                  'entry_order_id': old.entry_order_id}
                self._apply_caps(state)
                self.revisions[key] = self.revisions.get(key, 0) + 1
                self.busy.discard(key)


def _refresh_after_pending_exit(strategy_state, current, *, token_id, side, filled_size,
                                avg_price, order_id, previously_known=0.):
    """A wallet rebuild already includes old exits; do not subtract them twice."""
    if strategy_state is None or filled_size <= 0:
        return
    guard = getattr(strategy_state, 'live_execution_guard', None)
    if guard is not None:
        try:
            guard.sync(current, strategy_state)
        except Exception as exc:
            guard.snapshot['complete'] = False
            guard.last_error = type(exc).__name__
            log.warning('pending exit inventory refresh unavailable: %s', type(exc).__name__)
        return
    delta = max(float(filled_size) - float(previously_known or 0.), 0.)
    if delta > 0:
        strategy_state.note_exit_fill(current.condition_id, token_id, side, delta,
            avg_price, order_id=order_id, ts=time.time())


def _exit_intent_status(result, *, filled_size, requested_size):
    """Known fills never establish that an uncertain order has no remainder."""
    if result.ambiguous or result.status == "timeout_pending_reconcile":
        return "ambiguous"
    if filled_size >= requested_size - 0.02 and filled_size > 0:
        return "completed"
    return "partial" if filled_size > 0 else "failed"


def _exit_status_for_result(
    result: OrderResult,
    *,
    filled_size: float,
    requested_size: float,
) -> str:
    if filled_size > 0:
        if filled_size >= requested_size - 0.02:
            return "exit_matched"
        return "exit_partial"
    return _effective_exit_status(result.status)


def _reconcile_exit_result(
    cfg: config.Config,
    client,
    current: LiveMarket,
    token_id: str,
    result: OrderResult,
    *,
    requested_size: float,
) -> OrderResult:
    if not cfg.sell_exit_reconcile_trades or not result.submitted:
        return result
    submitted_at = float((result.raw or {}).get("submitted_at") or time.time())
    should_reconcile = bool(result.order_id) or result.ambiguous or result.status in ("matched", "filled")
    if not should_reconcile:
        return result
    for attempt in range(3):
        try:
            reconciled = reconcile_recent_trade(
                client,
                condition_id=current.condition_id,
                token_id=token_id,
                side="SELL",
                submitted_at=submitted_at,
                min_size=0.01,
                order_id=result.order_id,
            )
        except Exception as e:
            log.warning("sell trade reconcile failed: %s", e)
            return result
        if reconciled is not None and not reconciled.ambiguous:
            if reconciled.filled_size + 1e-6 < result.filled_size:
                # A lagging index cannot erase an execution acknowledgement.
                return result
            if result.ambiguous and reconciled.filled_size < requested_size - 1e-6:
                # Partial fills alone do not prove that an old resting order
                # has no remainder; keep the order pending until its terminal
                # state is positively known.
                return replace(reconciled, ambiguous=True, terminal=False, fallback_safe=False)
            return reconciled
        if attempt < 2:
            time.sleep(0.25)
    return result


_EARLY_SCALE_ENTRY_RULES = {"early_price", "early_strong_delta"}
_STRONG_SCALE_ENTRY_RULES = {"strong_delta"}
_NORMAL_SCALE_ENTRY_RULES = {"edge", "stable_delta", "strong_normal_reverse"}
_LATE_SCALE_ENTRY_RULES = {"late_edge"}
_TAIL_SCALE_ENTRY_RULES = {"tail_price"}
_TREND_OVERHEAT_ENTRY_RULES = {"edge", "late_edge", "stable_delta"}


def _previous_winner_streak(
    cfg: config.Config,
    current: LiveMarket,
    cache: dict[str, tuple[Optional[str], int]],
) -> tuple[Optional[str], int]:
    """Return the immediate previous closed-market winner streak for this asset."""
    cached = cache.get(current.condition_id)
    if cached is not None:
        return cached

    match = re.match(r"^(.*-)(\d{10})$", current.market_slug)
    if not match:
        result: tuple[Optional[str], int] = (None, 0)
        cache[current.condition_id] = result
        return result

    prefix = match.group(1)
    start_ts = int(match.group(2))
    streak_side: Optional[str] = None
    streak_count = 0
    for offset in range(1, max(cfg.trend_overheat_min_streak + 2, 5) + 1):
        slug = f"{prefix}{start_ts - (300 * offset)}"
        side = closed_market_winner_side(cfg, slug)
        if side not in ("UP", "DOWN"):
            break
        if streak_side is None:
            streak_side = side
            streak_count = 1
            continue
        if side != streak_side:
            break
        streak_count += 1

    result = (streak_side, streak_count)
    cache[current.condition_id] = result
    return result


def _trend_overheat_blocks_entry(
    cfg: config.Config,
    decision_side: Optional[str],
    entry_rule: str,
    price: Optional[float],
    streak_side: Optional[str],
    streak_count: int,
) -> bool:
    if not cfg.trend_overheat_filter_enabled:
        return False
    if entry_rule not in _TREND_OVERHEAT_ENTRY_RULES:
        return False
    if decision_side not in ("UP", "DOWN") or streak_side != decision_side:
        return False
    if streak_count < cfg.trend_overheat_min_streak:
        return False
    return price is not None and price >= cfg.trend_overheat_price_floor


def _order_t_remaining(current: LiveMarket, order: dict) -> Optional[float]:
    try:
        return current.end_ts - float(order["ts"])
    except (KeyError, TypeError, ValueError):
        return None


def _scale_slot_for_order(
    cfg: config.Config,
    current: LiveMarket,
    order: dict,
) -> Optional[str]:
    rule = str(order.get("entry_rule") or "")
    if rule in _EARLY_SCALE_ENTRY_RULES:
        return "early"
    if rule in _STRONG_SCALE_ENTRY_RULES:
        return "strong"
    if rule in _NORMAL_SCALE_ENTRY_RULES:
        return "normal"
    if rule in _LATE_SCALE_ENTRY_RULES:
        return "late"
    if rule in _TAIL_SCALE_ENTRY_RULES:
        return "tail"

    t_at_order = _order_t_remaining(current, order)
    if t_at_order is None:
        return None
    if t_at_order > cfg.strong_delta_entry_window_sec:
        return "early"
    if (
        cfg.strong_delta_entry_min_t_remaining_sec
        <= t_at_order
        <= cfg.strong_delta_entry_window_sec
    ):
        return "strong"
    if cfg.min_t_remaining_sec <= t_at_order <= cfg.seconds_before_close:
        return "normal"
    if (
        cfg.late_edge_entry_min_t_remaining_sec
        <= t_at_order
        <= cfg.late_edge_entry_window_sec
    ):
        return "late"
    if (
        cfg.tail_entry_min_t_remaining_sec
        <= t_at_order
        <= cfg.tail_entry_window_sec
    ):
        return "tail"
    return None


def _scale_slots_for_orders(
    cfg: config.Config,
    current: LiveMarket,
    orders: list[dict],
) -> set[str]:
    slots: set[str] = set()
    for order in orders:
        slot = _scale_slot_for_order(cfg, current, order)
        if slot is not None:
            slots.add(slot)
    return slots


def _early_scale_sides_for_market(
    cfg: config.Config,
    current: LiveMarket,
    dry_run: bool,
) -> set[str]:
    return {
        str(order.get("side") or "")
        for order in _early_scale_orders_for_market(cfg, current, dry_run)
        if str(order.get("side") or "") in ("UP", "DOWN")
    }


def _early_scale_orders_for_market(
    cfg: config.Config,
    current: LiveMarket,
    dry_run: bool,
) -> list[dict]:
    early_orders: list[dict] = []
    orders = store.effective_buy_orders_for_market(current.condition_id, dry_run)
    for order in orders:
        if _scale_slot_for_order(cfg, current, order) != "early":
            continue
        early_orders.append(order)
    return early_orders


def _early_order_allows_hedge(cfg: config.Config, order: dict) -> bool:
    return str(order.get("entry_rule") or "") == "early_strong_delta"


def _early_hedge_only_side(
    cfg: config.Config,
    current: LiveMarket,
    t_rem: float,
    dry_run: bool,
) -> Optional[str]:
    if not (
        cfg.scale_in_after_early_enabled
        and cfg.early_strong_delta_entry_enabled
        and cfg.early_strong_delta_entry_hedge_enabled
        and cfg.early_strong_delta_entry_min_t_remaining_sec < t_rem <= cfg.early_strong_delta_entry_window_sec
    ):
        return None
    early_orders = _early_scale_orders_for_market(cfg, current, dry_run)
    sides = {
        str(order.get("side") or "")
        for order in early_orders
        if str(order.get("side") or "") in ("UP", "DOWN")
    }
    if len(sides) != 1:
        return None
    if not any(_early_order_allows_hedge(cfg, order) for order in early_orders):
        return None
    return "DOWN" if "UP" in sides else "UP"


def _scale_in_slot(
    cfg: config.Config,
    current: LiveMarket,
    t_rem: float,
    dry_run: bool,
) -> Optional[str]:
    """Return the open scale-in slot; direction is chosen by the live strategy."""
    if not cfg.scale_in_after_early_enabled:
        return None

    orders = store.effective_buy_orders_for_market(current.condition_id, dry_run)
    if not orders:
        return None
    if cfg.max_buys_per_market > 0 and len(orders) >= cfg.max_buys_per_market:
        return None

    slots = _scale_slots_for_orders(cfg, current, orders)

    early_hedge_active = (
        cfg.early_strong_delta_entry_enabled
        and cfg.early_strong_delta_entry_hedge_enabled
        and cfg.early_strong_delta_entry_min_t_remaining_sec < t_rem <= cfg.early_strong_delta_entry_window_sec
    )
    if early_hedge_active:
        if _early_hedge_only_side(cfg, current, t_rem, dry_run) is not None:
            return "early_hedge"

    strong_active = (
        cfg.strong_delta_entry_enabled
        and cfg.strong_delta_entry_min_t_remaining_sec
        <= t_rem
        <= cfg.strong_delta_entry_window_sec
    )
    if strong_active and "strong" not in slots:
        return "strong"

    normal_active = (
        cfg.normal_scale_in_enabled
        and cfg.min_t_remaining_sec <= t_rem <= cfg.seconds_before_close
    )
    if normal_active and "normal" not in slots:
        return "normal"

    late_active = (
        cfg.late_edge_entry_enabled
        and cfg.late_edge_entry_min_t_remaining_sec
        <= t_rem
        <= cfg.late_edge_entry_window_sec
    )
    if late_active and "late" not in slots:
        return "late"

    tail_active = (
        cfg.tail_entry_enabled
        and cfg.tail_entry_min_t_remaining_sec <= t_rem <= cfg.tail_entry_window_sec
    )
    if tail_active and "tail" not in slots:
        return "tail"

    return None


def maybe_reversal_exit(
    cfg: config.Config,
    client,
    current: LiveMarket,
    book_up: TopOfBook,
    book_down: TopOfBook,
    t_rem: float,
    dry_run: bool,
    confirmations: dict[tuple[str, str, str], int],
    exit_attempts: dict[tuple[str, str, str], float],
    strategy_state: Optional[StrategyState] = None,
    btc_signal: Optional[BtcSignal] = None,
    btc_signal_error: Optional[str] = None,
) -> bool:
    """Use local tracked positions and full-size stop-loss exits."""
    # Once a market has expired, let the resolver settle the position.  A
    # stale order book at t<=0 must never be turned into a fabricated sell.
    if t_rem <= 0:
        return False
    if (
        not cfg.reversal_exit_enabled
        and not cfg.early_reversal_exit_enabled
        and not _profit_exit_enabled(cfg)
        and not getattr(cfg, "near_close_exit_enabled", False)
    ):
        return False

    exit_window = 0.0
    min_exit_t_remaining: Optional[float] = None
    if cfg.early_reversal_exit_enabled:
        exit_window = max(exit_window, cfg.early_reversal_exit_window_sec)
        min_exit_t_remaining = cfg.early_reversal_exit_min_t_remaining_sec
    if cfg.reversal_exit_enabled:
        exit_window = max(exit_window, cfg.reversal_exit_window_sec)
        min_exit_t_remaining = (
            cfg.reversal_exit_min_t_remaining_sec
            if min_exit_t_remaining is None
            else min(min_exit_t_remaining, cfg.reversal_exit_min_t_remaining_sec)
        )
    if cfg.reversal_exit_enabled and cfg.reversal_partial_exit_enabled:
        exit_window = max(exit_window, cfg.reversal_partial_exit_window_sec)
    if cfg.reversal_exit_enabled and cfg.reversal_late_exit_enabled:
        exit_window = max(exit_window, cfg.reversal_late_window_sec)
    if _profit_exit_enabled(cfg):
        # Profit exits are valid throughout the active market window.
        exit_window = max(exit_window, 10_000.0)
        min_exit_t_remaining = 0.0
    if getattr(cfg, "near_close_exit_enabled", False):
        exit_window = max(
            exit_window, getattr(cfg, "near_close_exit_window_sec", 15.0)
        )
        min_exit_t_remaining = 0.0
    if (
        min_exit_t_remaining is None
        or t_rem < min_exit_t_remaining
        or t_rem > exit_window
    ):
        return False

    open_orders = []
    if strategy_state is not None:
        open_orders = strategy_state.local_open_orders_for_market(current.condition_id)
        if not open_orders and not getattr(strategy_state, "live_authoritative", False):
            hydrated_orders = store.open_orders_for_market(current.condition_id, dry_run)
            for order in hydrated_orders:
                strategy_state.hydrate_open_order(current, order)
            open_orders = strategy_state.local_open_orders_for_market(current.condition_id)
    if not open_orders and not (strategy_state is not None and getattr(strategy_state, "live_authoritative", False)):
        open_orders = store.open_orders_for_market(current.condition_id, dry_run)
    if not open_orders:
        return False

    for order in open_orders:
        held_side = str(order["side"]).upper()
        if held_side not in ("UP", "DOWN"):
            continue

        position = (
            strategy_state.active_position(current.condition_id, str(order["token_id"]), held_side)
            if strategy_state is not None
            else None
        )
        if position is None and strategy_state is not None:
            position = strategy_state.hydrate_open_order(current, order)

        held_book = _book_for_side(held_side, book_up, book_down)
        book_timestamp = float(getattr(held_book, "fetched_at", 0.0) or 0.0)
        book_age = max(0.0, time.time() - book_timestamp) if book_timestamp else 0.0
        if (
            not dry_run
            and book_timestamp
            and book_age > max(float(getattr(cfg, "execution_book_max_age_sec", 3.0)), 0.1)
        ):
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=str(order["token_id"]),
                side=held_side,
                t_remaining=t_rem,
                ask_price=held_book.best_bid,
                ask_size=held_book.bid_size,
                action="SKIP_EXIT_STALE_BOOK",
                reason=f"exit book age={book_age:.2f}s exceeds execution limit",
                dry_run=dry_run,
            )
            continue
        sell_bid = held_book.best_bid
        buy_price = (
            position.entry_price
            if position is not None and position.entry_price > 0
            else float(order["price"])
        )
        remaining_size = _floor_size(
            position.remaining_size if position is not None else float(order["size"])
        )
        if not dry_run and strategy_state is not None:
            guard = getattr(strategy_state, "live_execution_guard", None)
            if guard is not None:
                try:
                    available = guard.available_to_sell(current, str(order["token_id"]))
                    remaining_size = _floor_size(min(remaining_size, available))
                except Exception as exc:
                    log.warning("exit balance reconciliation unavailable: %s", type(exc).__name__)
                    continue
                if remaining_size <= 0:
                    continue
        exit_pending = bool(position.stop_loss_pending) if position is not None else False
        early_exit = (
            cfg.early_reversal_exit_enabled
            and cfg.early_reversal_exit_min_t_remaining_sec
            <= t_rem
            <= cfg.early_reversal_exit_window_sec
            and _scale_slot_for_order(cfg, current, order) == "early"
        )
        partial_exit = (
            cfg.reversal_exit_enabled
            and cfg.reversal_partial_exit_enabled
            and cfg.reversal_exit_window_sec < t_rem <= cfg.reversal_partial_exit_window_sec
        )
        late_exit = (
            cfg.reversal_exit_enabled
            and cfg.reversal_late_exit_enabled
            and t_rem <= cfg.reversal_late_window_sec
        )
        normal_exit = (
            cfg.reversal_exit_enabled
            and not early_exit
            and not partial_exit
            and not late_exit
            and t_rem <= cfg.reversal_exit_window_sec
            and t_rem >= cfg.reversal_normal_min_t_remaining_sec
        )
        near_close_exit = (
            getattr(cfg, "near_close_exit_enabled", False)
            and t_rem <= getattr(cfg, "near_close_exit_window_sec", 15.0)
            and t_rem > 0
        )
        profit_target = buy_price * (1.0 + _profit_target_fraction(cfg))
        profit_target += max(getattr(cfg, "profit_target_ticks", 2), 0) * max(current.tick_size, 0.01)
        net_profit_ok = True
        if getattr(cfg, "profit_net_enabled", False):
            try:
                decision = _net_profit_exit_decision(cfg, current, held_book, position, remaining_size, buy_price)
                net_profit_ok = decision.available and decision.should_exit
            except (ValueError, TypeError, ArithmeticError):
                net_profit_ok = False
        profit_exit = (
            _profit_exit_enabled(cfg)
            and sell_bid is not None
            and net_profit_ok
            and (getattr(cfg,"profit_net_enabled",False) or sell_bid >= profit_target)
            and not near_close_exit
            and not exit_pending
        )
        if not early_exit and not partial_exit and not late_exit and not normal_exit and not near_close_exit and not profit_exit and not exit_pending:
            continue
        if profit_exit:
            held_bid_threshold = sell_bid or profit_target
            required_confirmations = max(getattr(cfg, "profit_exit_confirm_checks", 1), 1)
            sell_fraction = _profit_exit_fraction(cfg)
            exit_tier = "profit"
        elif near_close_exit:
            # Near-close is an emergency taker-only tier.  It deliberately
            # bypasses the normal drawdown threshold so profitable holdings
            # cannot remain stuck until resolution.
            held_bid_threshold = float("inf")
            required_confirmations = 1
            sell_fraction = 1.0
            exit_tier = "near_close"
        elif early_exit:
            held_bid_threshold = cfg.early_reversal_held_bid_threshold
            required_confirmations = cfg.early_reversal_confirm_checks
        elif partial_exit:
            held_bid_threshold = (
                cfg.reversal_partial_held_bid_threshold
                if cfg.reversal_partial_held_bid_threshold > 0
                else buy_price - cfg.reversal_partial_held_bid_drawdown
            )
            required_confirmations = cfg.reversal_partial_confirm_checks
        else:
            if late_exit:
                held_bid_threshold = cfg.reversal_late_held_bid_threshold
            elif cfg.reversal_held_bid_threshold > 0:
                held_bid_threshold = cfg.reversal_held_bid_threshold
            else:
                drawdown = min(max(cfg.reversal_held_bid_drawdown, 0.0), 1.0)
                held_bid_threshold = buy_price * (1.0 - drawdown)
            required_confirmations = (
                cfg.reversal_late_confirm_checks
                if late_exit
                else cfg.reversal_confirm_checks
            )
        if not profit_exit and not near_close_exit:
            sell_fraction = 1.0
            exit_tier = "stop_loss" if exit_pending else (
                "early"
                if early_exit
                else ("partial" if partial_exit else ("late" if late_exit else "normal"))
            )
        key = (current.condition_id, held_side, exit_tier)
        now = time.time()

        if sell_bid is None or sell_bid <= 0:
            # Avoid writing the same no-bid decision on every poll while still
            # allowing the next non-empty book to recover the position.
            if key in exit_attempts:
                return False
            exit_attempts[key] = now
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=str(order["token_id"]),
                side=held_side,
                t_remaining=t_rem,
                ask_price=None,
                ask_size=held_book.bid_size,
                action="SKIP_EXIT_BOOK",
                reason=f"no bid to sell held {held_side}",
                dry_run=dry_run,
            )
            return False

        if not exit_pending:
            if sell_bid > held_bid_threshold:
                confirmations[key] = 0
                continue

            if cfg.reversal_exit_require_btc_reversal:
                btc_reversed = (
                    (held_side == "UP" and btc_signal is not None and btc_signal.delta_usd < 0)
                    or (held_side == "DOWN" and btc_signal is not None and btc_signal.delta_usd > 0)
                )
                if not btc_reversed:
                    confirmations[key] = 0
                    store.log_decision(
                        market_slug=current.market_slug,
                        condition_id=current.condition_id,
                        token_id=str(order["token_id"]),
                        side=held_side,
                        t_remaining=t_rem,
                        ask_price=sell_bid,
                        ask_size=held_book.bid_size,
                        action="SKIP_EXIT_BTC_SIGNAL",
                        reason=(
                            f"held {held_side} bid={sell_bid} <= {held_bid_threshold} "
                            "but BTC delta has not reversed"
                            + (
                                f": {btc_signal.describe()}"
                                if btc_signal is not None
                                else f": unavailable{': ' + btc_signal_error if btc_signal_error else ''}"
                            )
                        ),
                        dry_run=dry_run,
                    )
                    continue

            confirmations[key] = confirmations.get(key, 0) + 1
            if confirmations[key] < required_confirmations:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=str(order["token_id"]),
                    side=held_side,
                    t_remaining=t_rem,
                    ask_price=sell_bid,
                    ask_size=held_book.bid_size,
                    action="SKIP_EXIT_CONFIRM",
                    reason=(
                        f"held {held_side} bid={sell_bid} <= "
                        f"{held_bid_threshold} "
                        f"confirmation {confirmations[key]}/{required_confirmations} "
                        f"tier={exit_tier}"
                    ),
                    dry_run=dry_run,
                )
                return False
            if strategy_state is not None:
                strategy_state.arm_stop_loss(current.condition_id, str(order["token_id"]), held_side)
        else:
            confirmations[key] = max(confirmations.get(key, 0), required_confirmations)

        # A partial fill changes the tier to ``stop_loss``.  Cooldown must
        # still span the previous ``normal``/``partial`` tier key, otherwise
        # the remainder can be re-submitted immediately.  The persisted
        # intent ledger also survives a worker restart.
        pending_intent = store.pending_exit_intent(
            current.condition_id, str(order["token_id"]), held_side, dry_run
        )
        if pending_intent is not None:
            age = max(0.0, now - float(pending_intent.get("updated_ts") or now))
            if not dry_run and client is not None and age >= 2.0:
                try:
                    reconciled = reconcile_recent_trade(
                        client, condition_id=current.condition_id,
                        token_id=str(order["token_id"]), side="SELL",
                        submitted_at=float(pending_intent.get("updated_ts") or now),
                        min_size=0.01, max_age_sec=max(age + 10.0, 45.0),
                        order_id=pending_intent.get("order_id"),
                    )
                except Exception as exc:
                    reconciled = None
                    log.warning("pending exit reconcile failed: %s", exc)
                if reconciled is not None and not reconciled.ambiguous:
                    requested_pending = float(pending_intent.get("requested_size") or remaining_size)
                    filled, avg, _amount = _filled_exit_values(
                        reconciled, requested_size=requested_pending, limit_price=float(sell_bid)
                    )
                    complete_fill = filled >= requested_pending - 1e-6
                    terminal_order = complete_fill
                    if not terminal_order and pending_intent.get('order_id'):
                        try:
                            from bot.order_evidence import order_snapshot
                            terminal_evidence = order_snapshot(
                                client.get_order(pending_intent['order_id']),
                                order_id=pending_intent['order_id'], token_id=str(order['token_id']),
                                side='SELL', requested_size=requested_pending)
                            terminal_order = bool(terminal_evidence and terminal_evidence['terminal'])
                        except Exception:
                            terminal_order = False
                    status = ('completed' if complete_fill else 'partial' if terminal_order else 'ambiguous')
                    store.upsert_exit_intent(
                        condition_id=current.condition_id, token_id=str(order["token_id"]),
                        side=held_side, tier=str(pending_intent.get("tier") or exit_tier),
                        dry_run=dry_run, requested_size=requested_pending, status=status,
                        order_id=reconciled.order_id, filled_size=filled,
                        error=reconciled.error, asset=getattr(current, "asset", None),
                    )
                    _refresh_after_pending_exit(strategy_state, current,
                        token_id=str(order['token_id']), side=held_side, filled_size=filled,
                        avg_price=avg, order_id=reconciled.order_id,
                        previously_known=float(pending_intent.get('filled_size') or 0.))
                    if filled > 0:
                        return True
            # Never follow an ambiguous request with a blind taker retry. If
            # the trade API cannot reconcile it, leave it in manual_review;
            # an operator can inspect the order before any further submission.
            store.log_decision(
                market_slug=current.market_slug, condition_id=current.condition_id,
                token_id=str(order["token_id"]), side=held_side, t_remaining=t_rem,
                ask_price=sell_bid, ask_size=held_book.bid_size,
                action="SKIP_EXIT_PENDING",
                reason=f"pending exit intent age={age:.1f}s; reconcile before retry",
                dry_run=dry_run,
            )
            return False

        memory_attempt_ts = max(
            (
                ts
                for (condition_id, side, _tier), ts in exit_attempts.items()
                if condition_id == current.condition_id and side == held_side
            ),
            default=0.0,
        )
        last_attempt_ts = max(
            memory_attempt_ts,
            store.latest_exit_attempt_ts(current.condition_id, str(order["token_id"]), dry_run),
        )
        if (
            cfg.order_retry_cooldown_sec > 0
            and now - last_attempt_ts < cfg.order_retry_cooldown_sec
        ):
            return False

        attempts, requested_size, visible_exit_size = _plan_exit_attempts(
            cfg,
            book=held_book,
            remaining_size=remaining_size,
            sell_fraction=sell_fraction,
            tick_size=current.tick_size,
        )
        if (
            profit_exit
            and str(getattr(cfg, "profit_exit_order_mode", "MAKER_FIRST")).upper()
            in {"MAKER_FIRST", "HYBRID"}
            and held_book.best_ask is not None
            and held_book.best_ask > float(sell_bid) + 1e-9
            and requested_size > 0
        ):
            # A passive sell is placed at the best ask.  It cannot cross the
            # current bid; otherwise post-only would be rejected and no
            # useful maker attempt would have been made.
            maker_price = _floor_price_to_tick(float(held_book.best_ask), current.tick_size)
            if maker_price > float(sell_bid) + 1e-9:
                attempts.insert(
                    0,
                    ExitAttemptPlan(
                        order_type="MAKER",
                        size=requested_size,
                        price=maker_price,
                        visible_size=visible_exit_size,
                        full_depth=True,
                    ),
                )
        if not attempts:
            min_exit_size = _clob_min_exit_size(cfg)
            min_exit_skip = (not dry_run and remaining_size + 1e-9 < min_exit_size)
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=str(order["token_id"]),
                side=held_side,
                t_remaining=t_rem,
                ask_price=sell_bid,
                ask_size=held_book.bid_size,
                action="SKIP_EXIT_MIN_ORDER_SIZE" if min_exit_skip else "SKIP_EXIT_SIZE",
                reason=(
                    f"held {held_side} remaining={remaining_size:.4f} is below live CLOB minimum "
                    f"{min_exit_size:.2f} shares; keep as settlement dust"
                    if min_exit_skip else
                    f"held {held_side} remaining={remaining_size} requested={requested_size:.4f} "
                    f"visible_exit_size={visible_exit_size} best_bid_size={held_book.bid_size}"
                ),
                dry_run=dry_run,
            )
            return False

        first_attempt = attempts[0]
        reason = (
            f"held-side exit: held={held_side} bid={sell_bid} <= "
            f"{held_bid_threshold} first_order={first_attempt.order_type} "
            f"sell_price={first_attempt.price} "
            f"buy_price={buy_price:.2f} remaining={remaining_size} "
            f"requested={requested_size:.2f} visible_exit_size={visible_exit_size:.2f} "
            f"fraction={sell_fraction:.2f} t_rem={t_rem:.1f}s tier={exit_tier}"
        )
        store.log_decision(
            market_slug=current.market_slug,
            condition_id=current.condition_id,
            token_id=str(order["token_id"]),
            side=held_side,
            t_remaining=t_rem,
            ask_price=first_attempt.price,
            ask_size=visible_exit_size,
            action="SELL_EXIT",
            reason=reason,
            dry_run=dry_run,
        )

        if dry_run:
            if first_attempt.order_type == "MAKER":
                # A passive order cannot be assumed filled from the current
                # bid in Paper mode.  Model the configured safe fallback
                # attempt instead; otherwise leave the position open for the
                # next poll.
                if getattr(cfg, "profit_maker_fallback_taker", True) and len(attempts) > 1:
                    first_attempt = attempts[1]
                else:
                    return False
            exit_attempts[key] = time.time()
            # Paper fills must follow visible depth just like a FAK fallback:
            # a thin book exits only the shares currently sellable.  Update
            # the in-memory tracker immediately so the same position cannot
            # be exited repeatedly during one worker run.
            paper_filled_size = min(first_attempt.size, visible_exit_size)
            if paper_filled_size <= 0:
                return False
            if not first_attempt.full_depth and not cfg.sell_exit_fak_fallback_enabled:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=str(order["token_id"]),
                    side=held_side,
                    t_remaining=t_rem,
                    ask_price=first_attempt.price,
                    ask_size=visible_exit_size,
                    action="SKIP_EXIT_SIZE",
                    reason=(
                        f"FOK depth insufficient: requested={requested_size:.4f} "
                        f"visible_exit_size={visible_exit_size:.4f}"
                    ),
                    dry_run=dry_run,
                )
                return False
            if not dry_run:
                intent_status = (
                    "completed" if effective and filled_size >= attempt.size - 0.02
                    else "partial" if effective
                    else "ambiguous" if result.ambiguous or result.status == "timeout_pending_reconcile"
                    else "failed"
                )
                store.upsert_exit_intent(
                    condition_id=current.condition_id, token_id=str(order["token_id"]),
                    side=held_side, tier=exit_tier, dry_run=False,
                    requested_size=attempt.size, status=intent_status,
                    order_id=result.order_id, filled_size=filled_size,
                    error=error_text, asset=getattr(current, "asset", None),
                )
            store.log_order(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=str(order["token_id"]),
                side=f"SELL_{held_side}",
                size=paper_filled_size,
                price=first_attempt.price,
                order_id=None,
                status="exit_dry_run",
                filled_size=paper_filled_size * first_attempt.price,
                error=reason,
                dry_run=True,
            )
            store.log_execution_audit(
                event="exit_attempt_result",
                asset=getattr(current, "asset", None),
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=str(order["token_id"]),
                lane="exit",
                dry_run=True,
                payload={
                    "target_size": float(requested_size),
                    "maker_fill_size": 0.0,
                    "fallback_requested_size": float(paper_filled_size),
                    "total_filled_size": float(paper_filled_size),
                    "remaining_position": max(0.0, float(remaining_size) - float(paper_filled_size)),
                    "attempt_count": 1,
                    "order_type": first_attempt.order_type,
                    "status": "exit_dry_run",
                    "failure_reason": None,
                    "intent_status": "completed" if paper_filled_size >= requested_size - 0.02 else "partial",
                    "t_remaining": float(t_rem),
                    "bid_depth": float(visible_exit_size),
                },
            )
            if strategy_state is not None:
                strategy_state.note_exit_fill(
                    current.condition_id,
                    str(order["token_id"]),
                    held_side,
                    paper_filled_size,
                    first_attempt.price,
                    ts=time.time(),
                )
            return True

        assert client is not None
        exit_attempts[key] = time.time()
        for attempt_index, attempt in enumerate(attempts):
            if current.t_remaining() <= 0:
                break
            provider = getattr(strategy_state, "execution_book_provider", None) if strategy_state is not None else None
            if provider is not None:
                refreshed = provider(str(order["token_id"]))
                if refreshed is None:
                    break
                held_book = refreshed
                if attempt_index > 0:
                    # Passive waiting can outlive the original signal. Never
                    # submit a stale planned Taker fallback after Maker TTL.
                    if exit_tier == "profit" and getattr(cfg,"profit_net_enabled",False):
                        if getattr(strategy_state,"urgent_exit_event",threading.Event()).is_set():
                            break
                        try:
                            net = _net_profit_exit_decision(cfg, current, refreshed, position, remaining_size, buy_price)
                            if not net.available or not net.should_exit:
                                break
                        except (ValueError,TypeError,ArithmeticError):
                            break
                    fresh_plans,_,_ = _plan_exit_attempts(cfg,book=refreshed,
                        remaining_size=remaining_size,sell_fraction=sell_fraction,tick_size=current.tick_size)
                    replacement = next((plan for plan in fresh_plans if plan.order_type==attempt.order_type),None)
                    if replacement is None:
                        continue
                    attempt = replacement
            guard = getattr(strategy_state, "live_execution_guard", None) if strategy_state is not None else None
            if guard is not None:
                try:
                    available = guard.available_to_sell(current, str(order["token_id"]))
                except Exception as exc:
                    log.warning("exit available shares unknown: %s", type(exc).__name__)
                    break
                clipped = _floor_size(min(attempt.size, available))
                if clipped + 1e-9 < _clob_min_exit_size(cfg):
                    break
                attempt = replace(attempt, size=clipped)
            log.info(
                "EXIT %s SELL_%s %s sz=%s/%s @ %s held_bid=%s threshold=%s "
                "visible=%s tier=%s t_rem=%.1fs",
                attempt.order_type,
                held_side,
                current.market_slug,
                attempt.size,
                remaining_size,
                attempt.price,
                sell_bid,
                held_bid_threshold,
                attempt.visible_size,
                exit_tier,
                t_rem,
            )
            if not dry_run:
                store.upsert_exit_intent(
                    condition_id=current.condition_id, token_id=str(order["token_id"]),
                    side=held_side, tier=exit_tier, dry_run=False,
                    requested_size=attempt.size, status="submitted",
                    asset=getattr(current, "asset", None),
                )
            if attempt.order_type == "MAKER":
                result = place_sell_maker(
                    client,
                    token_id=str(order["token_id"]),
                    price=attempt.price,
                    size=attempt.size,
                    tick_size=current.tick_size,
                    neg_risk=current.neg_risk,
                    order_type=getattr(cfg, "profit_maker_order_type", "GTC"),
                    ttl_sec=getattr(cfg, "profit_maker_ttl_sec", 2.0),
                    post_only=getattr(cfg, "profit_maker_post_only", True),
                    condition_id=current.condition_id,
                    best_bid=held_book.best_bid,
                    best_ask=held_book.best_ask,
                    cancel_event=getattr(strategy_state,"urgent_exit_event",None),
                )
                if (
                    result.status in {"maker_timeout_cancelled", "post_only_rejected"}
                    and not getattr(cfg, "profit_maker_fallback_taker", True)
                ):
                    # No taker fallback requested; leave this exit for a
                    # later poll after the maker was safely canceled.
                    store.upsert_exit_intent(
                        condition_id=current.condition_id, token_id=str(order["token_id"]),
                        side=held_side, tier=exit_tier, dry_run=False,
                        requested_size=attempt.size, status=("ambiguous" if result.ambiguous else "failed"),
                        order_id=result.order_id, filled_size=float(result.filled_size or 0.0),
                        error=result.error, asset=getattr(current, "asset", None),
                    )
                    store.log_execution_audit(
                        event="exit_attempt_result", asset=getattr(current, "asset", None),
                        market_slug=current.market_slug, condition_id=current.condition_id,
                        token_id=str(order["token_id"]), lane="exit", dry_run=False,
                        payload={
                            "target_size": float(attempt.size), "maker_fill_size": float(result.filled_size or 0.0),
                            "fallback_requested_size": 0.0, "total_filled_size": float(result.filled_size or 0.0),
                            "remaining_position": max(0.0, float(remaining_size) - float(result.filled_size or 0.0)),
                            "attempt_count": int(attempt_index + 1), "order_type": "MAKER",
                            "status": result.status, "failure_reason": result.error,
                            "intent_status": "ambiguous" if result.ambiguous else "failed",
                            "t_remaining": float(t_rem), "bid_depth": float(attempt.visible_size),
                        },
                    )
                    break
                if result.ambiguous:
                    # Never submit a taker while a maker cancel is uncertain.
                    store.upsert_exit_intent(
                        condition_id=current.condition_id, token_id=str(order["token_id"]),
                        side=held_side, tier=exit_tier, dry_run=False,
                        requested_size=attempt.size, status="ambiguous",
                        order_id=result.order_id, filled_size=float(result.filled_size or 0.0),
                        error=result.error, asset=getattr(current, "asset", None),
                    )
                    store.log_execution_audit(
                        event="exit_attempt_result", asset=getattr(current, "asset", None),
                        market_slug=current.market_slug, condition_id=current.condition_id,
                        token_id=str(order["token_id"]), lane="exit", dry_run=False,
                        payload={
                            "target_size": float(attempt.size), "maker_fill_size": float(result.filled_size or 0.0),
                            "fallback_requested_size": 0.0, "total_filled_size": float(result.filled_size or 0.0),
                            "remaining_position": max(0.0, float(remaining_size) - float(result.filled_size or 0.0)),
                            "attempt_count": int(attempt_index + 1), "order_type": "MAKER",
                            "status": result.status, "failure_reason": result.error,
                            "intent_status": "ambiguous", "t_remaining": float(t_rem),
                            "bid_depth": float(attempt.visible_size),
                        },
                    )
                    break
                # Safe maker cancellation may fall through to the existing
                # FOK/FAK attempts; a matched maker result is handled below.
                if (result.status in {"maker_timeout_cancelled", "post_only_rejected"}
                        and result.fallback_safe):
                    store.upsert_exit_intent(
                        condition_id=current.condition_id, token_id=str(order["token_id"]),
                        side=held_side, tier=exit_tier, dry_run=False,
                        requested_size=attempt.size, status="failed",
                        order_id=result.order_id, filled_size=float(result.filled_size or 0.0),
                        error=result.error, asset=getattr(current, "asset", None),
                    )
                    store.log_execution_audit(
                        event="exit_attempt_result", asset=getattr(current, "asset", None),
                        market_slug=current.market_slug, condition_id=current.condition_id,
                        token_id=str(order["token_id"]), lane="exit", dry_run=False,
                        payload={
                            "target_size": float(attempt.size), "maker_fill_size": float(result.filled_size or 0.0),
                            "fallback_requested_size": float(attempt.size), "total_filled_size": float(result.filled_size or 0.0),
                            "remaining_position": max(0.0, float(remaining_size) - float(result.filled_size or 0.0)),
                            "attempt_count": int(attempt_index + 1), "order_type": "MAKER",
                            "status": result.status, "failure_reason": result.error,
                            "intent_status": "failed", "t_remaining": float(t_rem),
                            "bid_depth": float(attempt.visible_size),
                        },
                    )
                    continue
            else:
                place_sell = place_sell_fok if attempt.order_type == "FOK" else place_sell_fak
                result = place_sell(
                    client,
                    token_id=str(order["token_id"]),
                    price=attempt.price,
                    size=attempt.size,
                    tick_size=current.tick_size,
                    neg_risk=current.neg_risk,
                )
            result = _reconcile_exit_result(
                cfg,
                client,
                current,
                str(order["token_id"]),
                result,
                requested_size=attempt.size,
            )
            filled_size, avg_price, filled_amount = _filled_exit_values(
                result,
                requested_size=attempt.size,
                limit_price=attempt.price,
            )
            status = _exit_status_for_result(
                result,
                filled_size=filled_size,
                requested_size=attempt.size,
            )
            effective = filled_size > 0
            error_text = result.error
            if not effective and result.error:
                error_text = (
                    f"{attempt.order_type} requested={attempt.size} "
                    f"limit={attempt.price}; {result.error}"
                )
            intent_status = _exit_intent_status(result,
                filled_size=filled_size, requested_size=attempt.size)
            # Every submitted attempt must leave a terminal status for
            # explicit FOK/FAK no-match failures.  Only ambiguous/network
            # results remain pending and block a blind retry.
            store.upsert_exit_intent(
                condition_id=current.condition_id, token_id=str(order["token_id"]),
                side=held_side, tier=exit_tier, dry_run=False,
                requested_size=attempt.size, status=intent_status,
                order_id=result.order_id, filled_size=filled_size,
                error=error_text, asset=getattr(current, "asset", None),
            )
            store.log_order(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=str(order["token_id"]),
                side=f"SELL_{held_side}",
                size=filled_size if effective else attempt.size,
                price=avg_price if effective else attempt.price,
                order_id=result.order_id,
                status=status,
                filled_size=filled_amount,
                error=error_text,
                dry_run=False,
            )
            store.log_execution_audit(
                event="exit_attempt_result",
                asset=getattr(current, "asset", None),
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=str(order["token_id"]),
                lane="exit",
                dry_run=False,
                payload={
                    "target_size": float(requested_size),
                    "maker_fill_size": float(filled_size if attempt.order_type == "MAKER" else 0.0),
                    "fallback_requested_size": float(attempt.size if attempt.order_type != "MAKER" else 0.0),
                    "total_filled_size": float(filled_size),
                    "remaining_position": max(0.0, float(remaining_size) - float(filled_size)),
                    "attempt_count": int(len(attempts)),
                    "order_type": attempt.order_type,
                    "status": status,
                    "failure_reason": error_text if not effective else None,
                    "intent_status": intent_status,
                    "t_remaining": float(t_rem),
                    "bid_depth": float(attempt.visible_size),
                },
            )
            log.info(
                "exit result: order_type=%s status=%s logged_status=%s "
                "filled=%s avg=%s amount=%s id=%s err=%s",
                attempt.order_type,
                result.status,
                status,
                filled_size,
                avg_price,
                filled_amount,
                result.order_id,
                result.error,
            )
            if strategy_state is not None and filled_size > 0:
                strategy_state.note_exit_fill(
                    current.condition_id,
                    str(order["token_id"]),
                    held_side,
                    filled_size,
                    avg_price if avg_price > 0 else attempt.price,
                    order_id=result.order_id,
                    ts=time.time(),
                )
            # Explicit FOK/FAK no-match responses are retryable.  Refresh the
            # book before the fallback attempt and slice it to currently
            # visible bid depth; this avoids holding a stale full-size request
            # after liquidity has disappeared.
            if (
                not effective
                and not result.ambiguous
                and attempt.order_type in {"FOK", "FAK"}
                and attempt_index + 1 < len(attempts)
            ):
                try:
                    refreshed_book = (provider(str(order["token_id"])) if provider is not None
                                      else fetch_book(cfg.clob_host, str(order["token_id"])))
                except Exception as exc:
                    refreshed_book = None
                    log.warning("exit retry book refresh failed: %s", exc)
                if refreshed_book is not None:
                    refreshed_attempts, _refreshed_requested, _refreshed_visible = _plan_exit_attempts(
                        cfg,
                        book=refreshed_book,
                        remaining_size=remaining_size,
                        sell_fraction=sell_fraction,
                        tick_size=current.tick_size,
                    )
                    refreshed_fak = next(
                        (candidate for candidate in refreshed_attempts if candidate.order_type == "FAK"),
                        None,
                    )
                    if refreshed_fak is not None:
                        attempts[attempt_index + 1] = refreshed_fak
                # Give the book a short interval to repopulate before using
                # the fallback.  The outer retry cooldown still governs the
                # next polling cycle.
                time.sleep(min(max(float(getattr(cfg, "order_retry_cooldown_sec", 1.0)), 1.0), 2.0))
            if effective or result.ambiguous:
                break
        return True

    return False


def loop(live: bool, asset: str = "BTC") -> None:
    base_cfg = config.load()
    asset = asset.upper()
    if live:
        # Keep per-asset gates in the worker so direct shell/systemd
        # invocations cannot bypass the dashboard controls.
        if asset == "BTC" and not base_cfg.btc_live_enabled:
            raise RuntimeError(
                "BTC_LIVE_ENABLED=false; enable the isolated BTC live switch before starting"
            )
    if asset == "ETH":
        if not base_cfg.eth_market_enabled:
            raise RuntimeError("ETH_MARKET_ENABLED=false; ETH market monitor is disabled")
        if live and not base_cfg.eth_trading_enabled:
            raise RuntimeError("ETH_TRADING_ENABLED=false; refusing ETH live orders")
    cfg = _runtime_config_for_asset(base_cfg, asset)
    if cfg.price_signal_source.strip().lower() in (
        "rtds",
        "polymarket-rtds",
        "chainlink-rtds",
        "polymarket",
    ):
        ensure_rtds_client(cfg)
    dry_run = not live
    client = build_client(cfg) if live else None

    # Materialize the DB schema up front.
    with store.db():
        pass

    early_label = (
        f"{cfg.seconds_before_close}-{cfg.early_entry_seconds_before_close}s@{cfg.early_entry_min_price}"
        if cfg.early_entry_enabled
        else "off"
    )
    strong_delta_label = (
        f"{cfg.strong_delta_entry_window_sec:.0f}-{cfg.strong_delta_entry_min_t_remaining_sec:.0f}s "
        f"@>{cfg.strong_delta_entry_min_price:.2f}/"
        f"UP>={cfg.strong_delta_entry_up_min_delta_usd:.1f}/"
        f"DOWN<={cfg.strong_delta_entry_down_max_delta_usd:.1f}/"
        f"{cfg.strong_delta_entry_confirm_checks}x"
        if cfg.strong_delta_entry_enabled
        else "off"
    )
    early_strong_label = (
        (
            f"{cfg.early_strong_delta_entry_window_sec:.0f}-{cfg.early_strong_delta_entry_min_t_remaining_sec:.0f}s "
            f">{cfg.early_strong_delta_entry_min_price:.2f}/"
            f"<{cfg.early_strong_delta_entry_max_price:.2f}/"
            + (
                "price-only always-hedge/"
                if cfg.early_strong_delta_entry_hedge_enabled
                else (
                    f"UP>={cfg.early_strong_delta_entry_up_min_delta_usd:.1f}/"
                    f"DOWN<={cfg.early_strong_delta_entry_down_max_delta_usd:.1f}/"
                )
            )
            + f"{cfg.early_strong_delta_entry_confirm_checks}x"
            + ("/hedge" if cfg.early_strong_delta_entry_hedge_enabled else "")
        )
        if cfg.early_strong_delta_entry_enabled
        else "off"
    )
    late_edge_filter_label = (
        f"UP>={cfg.late_edge_entry_up_min_delta_usd:.1f}/"
        f"DOWN<={cfg.late_edge_entry_down_max_delta_usd:.1f}/"
        if cfg.late_edge_entry_delta_filter_enabled
        else "price-only/"
    )
    late_edge_confirm_label = (
        (
            f"{cfg.late_edge_entry_window_sec:.0f}-30s:{cfg.late_edge_entry_mid_confirm_checks}x/"
            f"30-{cfg.late_edge_entry_min_t_remaining_sec:.0f}s:{cfg.late_edge_entry_late_confirm_checks}x"
        )
        if cfg.late_edge_entry_window_sec <= 60
        else (
            f"{cfg.late_edge_entry_window_sec:.0f}-60s:{cfg.late_edge_entry_confirm_checks}x/"
            f"60-30s:{cfg.late_edge_entry_mid_confirm_checks}x/"
            f"30-{cfg.late_edge_entry_min_t_remaining_sec:.0f}s:{cfg.late_edge_entry_late_confirm_checks}x"
        )
    )
    late_edge_label = (
        f"{cfg.late_edge_entry_window_sec:.0f}-{cfg.late_edge_entry_min_t_remaining_sec:.0f}s "
        f"@{cfg.late_edge_entry_min_price:.2f}-{cfg.late_edge_entry_max_price:.2f}/"
        f"{late_edge_filter_label}{late_edge_confirm_label}/"
        f"{cfg.late_edge_entry_risk_fraction * 100:.1f}%"
        if cfg.late_edge_entry_enabled
        else "off"
    )
    stable_delta_label = (
        f"{cfg.stable_delta_entry_window_sec:.0f}-{cfg.stable_delta_entry_min_t_remaining_sec:.0f}s "
        f"@{cfg.stable_delta_entry_min_price:.2f}-{cfg.stable_delta_entry_max_price:.2f}/"
        f"abs_delta={cfg.stable_delta_entry_min_abs_delta_usd:.1f}-"
        f"{cfg.stable_delta_entry_max_abs_delta_usd:.1f}/"
        f"move<{cfg.stable_delta_entry_max_delta_move_usd:.1f}/"
        f"{cfg.stable_delta_entry_confirm_checks}x/"
        f"{cfg.stable_delta_entry_risk_fraction * 100:.1f}%"
        if cfg.stable_delta_entry_enabled
        else "off"
    )
    tail_label = (
        f"{cfg.tail_entry_window_sec}-{cfg.tail_entry_min_t_remaining_sec}s@>{cfg.tail_entry_min_price}"
        if cfg.tail_entry_enabled
        else "off"
    )
    retry_label = (
        f"{cfg.max_buy_retries_per_market}x/{cfg.order_retry_cooldown_sec:.1f}s"
        if cfg.max_buy_retries_per_market > 0
        else f"until filled/{cfg.order_retry_cooldown_sec:.1f}s"
    )
    retry_drift_label = (
        "unlimited"
        if cfg.max_retry_price_drift_ticks < 0
        else f"{cfg.max_retry_price_drift_ticks}t"
    )
    reversal_late_label = (
        f"{cfg.reversal_late_window_sec:.0f}-{cfg.reversal_exit_min_t_remaining_sec:.0f}s "
        f"held<{cfg.reversal_late_held_bid_threshold:.2f}/{cfg.reversal_late_confirm_checks}x "
        if cfg.reversal_late_exit_enabled
        else "late=off "
    )
    early_reversal_label = (
        f"early={cfg.early_reversal_exit_window_sec:.0f}-"
        f"{cfg.early_reversal_exit_min_t_remaining_sec:.0f}s "
        f"held<{cfg.early_reversal_held_bid_threshold:.2f}/"
        f"{cfg.early_reversal_confirm_checks}x "
        f"sell={cfg.early_reversal_exit_fraction:.0%}; "
        if cfg.early_reversal_exit_enabled
        else ""
    )
    normal_exit_trigger_label = (
        f"held<{cfg.reversal_held_bid_threshold:.2f}"
        if cfg.reversal_held_bid_threshold > 0
        else f"dd>={cfg.reversal_held_bid_drawdown:.0%}"
    )
    if cfg.scale_in_after_early_enabled:
        scale_parts = [
            f"early{' + hedge' if cfg.early_strong_delta_entry_hedge_enabled else ''}"
        ]
        if cfg.strong_delta_entry_enabled:
            scale_parts.append("strong")
        if cfg.normal_scale_in_enabled:
            scale_parts.append(f"{cfg.seconds_before_close}-{cfg.min_t_remaining_sec}s")
        if cfg.late_edge_entry_enabled:
            scale_parts.append(
                f"{cfg.late_edge_entry_window_sec}-{cfg.late_edge_entry_min_t_remaining_sec}s"
            )
        if cfg.tail_entry_enabled:
            scale_parts.append("tail")
        scale_in_label = (
            f"{' + '.join(scale_parts)}; max {cfg.max_buys_per_market}; per-slot side"
        )
    else:
        scale_in_label = "off"
    log.info(
        "starting %s bot dry_run=%s window=%s-%ss early_strong=%s strong_delta=%s late_edge=%s stable_delta=%s mid=%s early=%s tail=%s scale_in=%s trend_overheat=%s min_edge=%.4f risk=%s hourly_cap=%s retry=%s retry_drift=%s signal=%s one_side=%s balance_reserve=$%.2f exit=%s",
        asset,
        dry_run,
        cfg.min_t_remaining_sec,
        cfg.seconds_before_close,
        early_strong_label,
        strong_delta_label,
        late_edge_label,
        stable_delta_label,
        (
            f"{cfg.mid_entry_window_sec:.0f}-{cfg.mid_entry_min_t_remaining_sec:.0f}s@"
            f"{cfg.mid_entry_min_price:.2f}-{cfg.mid_entry_max_price:.2f}/"
            f"{cfg.mid_entry_risk_fraction:.0%}/UP>{cfg.mid_btc_up_min_delta_usd:.1f}/"
            f"DOWN<{cfg.mid_btc_down_max_delta_usd:.1f}"
            if cfg.mid_entry_enabled
            else "off"
        ),
        early_label,
        tail_label,
        scale_in_label,
        (
            f"{cfg.trend_overheat_min_streak}x same-side price>={cfg.trend_overheat_price_floor:.2f}"
            if cfg.trend_overheat_filter_enabled
            else "off"
        ),
        cfg.min_net_edge,
        (
            f"${cfg.order_fixed_notional_usd:.2f}"
            if cfg.order_fixed_notional_usd > 0
            else f"{cfg.order_risk_fraction * 100:.1f}%"
        ),
        cfg.max_orders_per_hour if cfg.max_orders_per_hour > 0 else "off",
        retry_label,
        retry_drift_label,
        (
            f"UP>={cfg.btc_up_min_delta_usd:.2f} "
            + (
                f"DOWN={cfg.btc_down_min_delta_usd:.2f}..{cfg.btc_down_max_delta_usd:.2f}"
                if cfg.btc_down_min_delta_usd < 0
                else f"DOWN<={cfg.btc_down_max_delta_usd:.2f}"
            )
            if cfg.btc_delta_filter_enabled
            else "off"
        ),
        "on" if cfg.one_side_per_market else "off",
        cfg.order_balance_reserve_usd,
        (
            early_reversal_label
            +
            f"{cfg.reversal_exit_window_sec:.0f}-{cfg.reversal_normal_min_t_remaining_sec:.0f}s "
            f"{normal_exit_trigger_label}/{cfg.reversal_confirm_checks}x; "
            f"{reversal_late_label}"
            f"sell={cfg.reversal_exit_order_fraction:.0%} "
            f"depth=full slip={cfg.sell_fok_slippage_ticks}t "
            f"fak={'on' if cfg.sell_exit_fak_fallback_enabled else 'off'} "
            f"reconcile={'on' if cfg.sell_exit_reconcile_trades else 'off'}"
            if cfg.reversal_exit_enabled
            else "off"
        ),
    )
    log.info(
        "asset runtime asset=%s series=%s symbol=%s trading=%s",
        asset,
        cfg.series_slug,
        cfg.btc_price_symbol,
        "live" if live else "paper",
    )
    log.info(
        "Paper loss recovery enabled=%s threshold=%.2f%% confirm=%s/%ss "
        "mark_age=%ss size=%.0f%% max_risk=%.2f%% max_entries=%s",
        bool(dry_run and cfg.loss_cap_recovery_enabled),
        cfg.loss_cap_recovery_min_net_pnl_fraction * 100,
        cfg.loss_cap_recovery_confirm_samples,
        cfg.loss_cap_recovery_confirm_window_sec,
        cfg.loss_cap_recovery_mark_max_age_sec,
        cfg.loss_cap_recovery_size_multiplier * 100,
        cfg.loss_cap_recovery_max_risk_fraction * 100,
        cfg.loss_cap_recovery_max_entries_per_day,
    )
    if dry_run:
        log.info(
            "Paper profit policy asset=%s daily_target=%.1f%% capital=$%.2f "
            "limit=$%.2f action=block_new_entries resume=Beijing_midnight",
            asset, cfg.max_daily_realized_profit_fraction * 100,
            cfg.paper_equity_usd,
            cfg.paper_equity_usd * cfg.max_daily_realized_profit_fraction,
        )

    current: Optional[LiveMarket] = None
    last_market_refresh = 0.0
    last_resolve_check = 0.0
    bought_this_window: set[str] = set()
    # Live CLOB orders below five shares are rejected.  Remember markets that
    # cannot satisfy that floor under the configured risk budget so the worker
    # does not retry the same invalid order every poll.
    min_size_skipped_markets: set[str] = set()
    buy_attempts: dict[str, float] = {}
    buy_attempt_counts: dict[str, int] = {}
    buy_retry_sides: dict[tuple[str, str], str] = {}
    buy_retry_entry_rules: dict[tuple[str, str], str] = {}
    retry_cap_logged: set[str] = set()
    strategy_state = StrategyState()
    live_guard = LiveExecutionGuard(cfg, client) if live else None
    strategy_state.live_execution_guard = live_guard
    last_live_sync = 0.0
    order_gate = PriorityOrderGate()
    exit_supervisor = None
    if live and getattr(cfg, "ws_exit_enabled", False):
        from bot.clob_stream import ClobStreams
        from pathlib import Path
        from bot.live_risk import state_file as risk_state_file
        stream = ClobStreams.from_cfg(cfg, authenticated=True)
        exit_inventory = _IndependentExitInventory(cfg, client,
            lambda token: exit_supervisor.exit_book(token), order_gate.urgent)

        def urgent_exit_check(market, up, down):
            positions = exit_inventory.positions(market)
            if positions is None:
                return True
            for position in positions:
                if position.remaining_size <= 0:
                    continue
                book = up if position.side == "UP" else down
                if book is None or book.best_bid is None:
                    return True
                if market.t_remaining() <= cfg.near_close_exit_window_sec:
                    return True
                if book.best_bid <= position.entry_price*(1.-cfg.reversal_held_bid_drawdown):
                    return True
            return False

        independent_confirmations, independent_attempts = {}, {}
        def execute_independent_exit(market, up, down):
            empty = TopOfBook(None,0.,None,0.,fetched_at=time.time())
            return exit_inventory.execute(market, lambda state:
                maybe_reversal_exit(cfg,client,market,up or empty,down or empty,
                    market.t_remaining(),False,independent_confirmations,independent_attempts,state))

        exit_supervisor = IndependentExitSupervisor(stream, execute=execute_independent_exit,
            reconcile=exit_inventory.reconcile, urgent_check=urgent_exit_check, gate=order_gate,
            max_book_age_sec=cfg.ws_exit_max_book_age_sec,reconcile_sec=cfg.ws_exit_reconcile_sec,
            health_path=Path(risk_state_file()).with_name("ws-exit-runtime.json"))
        exit_supervisor.start()
    if live:
        from bot.live_accounting import refresh_live_risk
        def _risk_monitor():
            while True:
                try:
                    refresh_live_risk(cfg)
                except Exception as exc:
                    # A failed refresh leaves the prior snapshot to expire;
                    # risk gates then refuse entries while exits keep running.
                    log.warning("live risk refresh unavailable: %s", type(exc).__name__)
                time.sleep(5.0)
        threading.Thread(target=_risk_monitor, name="live-account-risk", daemon=True).start()
    exit_confirmations: dict[tuple[str, str, str], int] = {}
    exit_attempts: dict[tuple[str, str, str], float] = {}
    buy_retry_reference_prices: dict[tuple[str, str, str], float] = {}
    previous_winner_streak_cache: dict[str, tuple[Optional[str], int]] = {}
    last_profit_stop_reason: Optional[str] = None
    last_profit_stop_log = 0.0
    last_recovery_state: Optional[str] = None
    recovery_book_cache: dict[str, tuple[TopOfBook, float]] = {}
    entry_signal_history: dict[str, tuple[float, float]] = {}

    # Settle anything left unresolved from prior runs before we start.
    try:
        resolve_pending(cfg, dry_run)
        invalidate_paper_profit_cache()
    except Exception as e:
        log.warning("initial resolve_pending failed: %s", e)

    while True:
        now = time.time()

        # Periodically resolve filled positions whose markets have closed.
        if now - last_resolve_check > 30:
            try:
                resolve_pending(cfg, dry_run)
                invalidate_paper_profit_cache()
            except Exception as e:
                log.warning("resolve_pending failed: %s", e)
            last_resolve_check = now

        stop_reason = daily_realized_profit_stop_reason(
            cfg, dry_run, asset=asset, cache_ttl_sec=10.0,
        )
        if stop_reason != last_profit_stop_reason:
            log.info("%s daily entry gate: %s; exits and settlement remain enabled",
                     "Paper" if dry_run else "Live", stop_reason or "clear")
            last_profit_stop_reason = stop_reason

        # Refresh live market every 5s, or when the current one expires.
        if current is None or now > current.end_ts + 5 or (now - last_market_refresh) > 5:
            market_refresh_failed = False
            try:
                m = fetch_live_market(cfg.gamma_host, cfg.series_slug)
            except Exception as e:
                log.warning("market discovery failed: %s", e)
                m = None
                market_refresh_failed = True
            last_market_refresh = now
            if m and (current is None or m.condition_id != current.condition_id):
                current = m
                log.info("new live market: %s end_ts=%.0f", current.market_slug, current.end_ts)
            elif (
                m is None
                and current is not None
                and now > current.end_ts + cfg.market_stale_grace_sec
            ):
                current = None

        if current is None:
            time.sleep(1.0)
            continue

        if exit_supervisor is not None:
            exit_supervisor.update_market(current)
        strategy_state.reset_for_market(current.condition_id)
        strategy_state.live_execution_guard = live_guard
        if live_guard is not None and (now - last_live_sync >= 3.0 or
                live_guard.snapshot.get("condition_id") != current.condition_id):
            try:
                live_guard.sync(current, strategy_state)
            except Exception as exc:
                live_guard.snapshot["complete"] = False
                live_guard.last_error = type(exc).__name__
                log.warning("live position reconciliation unavailable: %s", type(exc).__name__)
            last_live_sync = now

        t_rem = current.t_remaining(now)
        if t_rem <= 0:
            time.sleep(0.5)
            continue

        effective_buy_orders = store.effective_buy_orders_for_market(
            current.condition_id,
            dry_run,
        )
        effective_buy_orders.extend(
            strategy_state.local_effective_buy_orders_for_market(current.condition_id)
        )
        effective_buy_sides = _effective_buy_sides(effective_buy_orders)
        locked_market_side = (
            _locked_market_side(effective_buy_orders)
            if cfg.one_side_per_market
            else None
        )
        side_conflict = cfg.one_side_per_market and len(effective_buy_sides) > 1
        already_bought = (
            current.condition_id in bought_this_window
            or bool(effective_buy_orders)
        )
        scale_in = _scale_in_slot(cfg, current, t_rem, dry_run) if already_bought else None
        scale_in_entry_slot = scale_in
        retry_slot = scale_in_entry_slot or "initial"
        reversal_enabled = (
            cfg.reversal_exit_enabled
            or cfg.early_reversal_exit_enabled
            or _profit_exit_enabled(cfg)
            or getattr(cfg, "near_close_exit_enabled", False)
        )
        reversal_window = 0.0
        reversal_min_t_remaining: Optional[float] = None
        if cfg.early_reversal_exit_enabled:
            reversal_window = max(reversal_window, cfg.early_reversal_exit_window_sec)
            reversal_min_t_remaining = cfg.early_reversal_exit_min_t_remaining_sec
        if cfg.reversal_exit_enabled:
            reversal_window = max(reversal_window, cfg.reversal_exit_window_sec)
            if cfg.reversal_partial_exit_enabled:
                reversal_window = max(reversal_window, cfg.reversal_partial_exit_window_sec)
            if cfg.reversal_late_exit_enabled:
                reversal_window = max(reversal_window, cfg.reversal_late_window_sec)
            reversal_min_t_remaining = (
                cfg.reversal_exit_min_t_remaining_sec
                if reversal_min_t_remaining is None
                else min(reversal_min_t_remaining, cfg.reversal_exit_min_t_remaining_sec)
            )
        if _profit_exit_enabled(cfg):
            reversal_window = max(reversal_window, 10_000.0)
            reversal_min_t_remaining = 0.0
        if getattr(cfg, "near_close_exit_enabled", False):
            reversal_window = max(
                reversal_window, getattr(cfg, "near_close_exit_window_sec", 15.0)
            )
            reversal_min_t_remaining = 0.0
        if (not dry_run) and current.condition_id in min_size_skipped_markets:
            time.sleep(cfg.poll_interval_sec)
            continue

        if already_bought and scale_in is None and (
            not reversal_enabled
            or t_rem > reversal_window
            or (
                reversal_min_t_remaining is not None
                and t_rem < reversal_min_t_remaining
            )
        ):
            time.sleep(cfg.poll_interval_sec)
            continue

        # Skip if already attempted this market in this process or a prior run.
        # Only fetch books when we're in (or near) the buy window — save bandwidth.
        buy_window_upper = buy_window_upper_sec(cfg)
        if t_rem > buy_window_upper + 10 and not (
            live_guard is not None and strategy_state.local_open_orders_for_market(current.condition_id)
        ):
            time.sleep(min(t_rem - buy_window_upper, 5.0))
            continue

        try:
            book_up = fetch_book(cfg.clob_host, current.up_token)
            book_down = fetch_book(cfg.clob_host, current.down_token)
        except Exception as e:
            log.warning("book fetch failed: %s", e)
            time.sleep(cfg.poll_interval_sec)
            continue
        book_fetched_at = time.time()
        recovery_book_cache[current.up_token] = (book_up, book_fetched_at)
        recovery_book_cache[current.down_token] = (book_down, book_fetched_at)

        btc_signal = None
        btc_signal_error = None
        if cfg.btc_delta_filter_enabled or cfg.reversal_exit_require_btc_reversal:
            try:
                btc_signal = fetch_btc_signal(cfg, current)
            except Exception as e:
                btc_signal_error = str(e)
        previous_entry_signal = entry_signal_history.get(current.condition_id)
        if btc_signal is not None:
            entry_signal_history[current.condition_id] = (
                now,
                float(btc_signal.delta_usd),
            )

        if exit_supervisor is None and maybe_reversal_exit(
            cfg,
            client,
            current,
            book_up,
            book_down,
            t_rem,
            dry_run,
            exit_confirmations,
            exit_attempts,
            strategy_state,
            btc_signal,
            btc_signal_error,
        ):
            invalidate_paper_profit_cache()
            time.sleep(cfg.poll_interval_sec)
            continue

        if exit_supervisor is not None and exit_supervisor.entry_block_reason():
            time.sleep(cfg.poll_interval_sec)
            continue

        if live_guard is not None:
            entry_block = live_guard.entry_reason(current)
            if entry_block:
                store.log_decision(market_slug=current.market_slug, condition_id=current.condition_id,
                    token_id=None, side=None, t_remaining=t_rem, ask_price=None, ask_size=None,
                    action="SKIP_LIVE_RECONCILIATION", reason=entry_block, dry_run=False)
                time.sleep(cfg.poll_interval_sec)
                continue

        def _recovery_fetch_book(token: str):
            cached = recovery_book_cache.get(token)
            max_age = max(0.1, float(cfg.loss_cap_recovery_mark_max_age_sec))
            if cached is not None and time.time() - cached[1] <= max_age:
                return cached
            fresh = fetch_book(cfg.clob_host, token)
            stamped = time.time()
            recovery_book_cache[token] = (fresh, stamped)
            return recovery_book_cache[token]

        recovery_decision = evaluate_loss_cap_recovery(
            cfg,
            asset,
            dry_run,
            books_by_token={
                current.up_token: (book_up, book_fetched_at),
                current.down_token: (book_down, book_fetched_at),
            },
            fetch_book=_recovery_fetch_book,
            now=now,
        )
        if recovery_decision.state != last_recovery_state:
            log.info(
                "Paper loss recovery asset=%s state=%s allow_entries=%s "
                "entries=%s net_pnl=%s reason=%s",
                asset,
                recovery_decision.state,
                recovery_decision.allow_entries,
                recovery_decision.entries_used,
                (
                    f"${recovery_decision.net_pnl_usd:.4f}"
                    if recovery_decision.net_pnl_usd is not None
                    else "n/a"
                ),
                recovery_decision.reason,
            )
            last_recovery_state = recovery_decision.state

        # Keep resolution and reversal exits above this gate. A Paper target
        # pauses BUYs until next Beijing day without terminating the worker.
        if dry_run and stop_reason is not None:
            if now - last_profit_stop_log >= 60:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=None, side=None, t_remaining=t_rem,
                    ask_price=None, ask_size=None,
                    action="SKIP_RISK", reason=stop_reason, dry_run=True,
                )
                log.info("Paper entry gate: %s", stop_reason)
                last_profit_stop_log = now
            time.sleep(cfg.poll_interval_sec)
            continue

        if side_conflict:
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=None,
                side=None,
                t_remaining=t_rem,
                ask_price=None,
                ask_size=None,
                action="SKIP_ONE_SIDE",
                reason=(
                    "market already contains effective buys on both sides; "
                    f"sides={sorted(effective_buy_sides)}"
                ),
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue

        # Skip new buys once a buy filled unless an explicit scale-in slot is open.
        if already_bought and scale_in is None:
            time.sleep(cfg.poll_interval_sec)
            continue

        last_buy_attempt_ts = buy_attempts.get(current.condition_id, 0.0)
        if (
            cfg.order_retry_cooldown_sec > 0
            and now - last_buy_attempt_ts < cfg.order_retry_cooldown_sec
        ):
            time.sleep(cfg.poll_interval_sec)
            continue

        buy_attempt_count = buy_attempt_counts.get(current.condition_id)
        if buy_attempt_count is None:
            buy_attempt_count = store.buy_attempt_count_for_market(
                current.condition_id,
                dry_run,
            )
            buy_attempt_counts[current.condition_id] = buy_attempt_count
        if (
            cfg.max_buy_retries_per_market > 0
            and buy_attempt_count >= cfg.max_buy_retries_per_market
        ):
            if current.condition_id not in retry_cap_logged:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=None,
                    side=None,
                    t_remaining=t_rem,
                    ask_price=None,
                    ask_size=None,
                    action="SKIP_RETRY_CAP",
                    reason=(
                        f"buy retry cap reached "
                        f"({buy_attempt_count}/{cfg.max_buy_retries_per_market})"
                    ),
                    dry_run=dry_run,
                )
                retry_cap_logged.add(current.condition_id)
            time.sleep(cfg.poll_interval_sec)
            continue

        retry_side = buy_retry_sides.get((current.condition_id, retry_slot))
        retry_entry_rule = buy_retry_entry_rules.get((current.condition_id, retry_slot))
        hedge_only_side = (
            locked_market_side
            if locked_market_side is not None
            else (
                _early_hedge_only_side(cfg, current, t_rem, dry_run)
                if retry_side is None
                else None
            )
        )
        if cfg.btc_delta_filter_enabled and btc_signal is None:
            try:
                btc_signal = fetch_btc_signal(cfg, current)
            except Exception as e:
                btc_signal_error = str(e)
        if retry_entry_rule == "strong_normal_reverse" and retry_side in ("UP", "DOWN"):
            d = _strong_normal_reverse_decision_for_side(
                cfg,
                current,
                book_up,
                book_down,
                t_rem,
                retry_side,
                f"retry strong_normal_reverse side={retry_side}",
            )
        else:
            d = (
                None
                if retry_side is not None
                else _strong_normal_reverse_trigger(
                    cfg,
                    current,
                    book_up,
                    book_down,
                    t_rem,
                    dry_run,
                    scale_in_entry_slot,
                )
            )
            if d is None:
                d = decide(
                    cfg,
                    current,
                    book_up,
                    book_down,
                    t_rem,
                    state=strategy_state,
                    now=now,
                    retry_side=retry_side,
                    only_side=hedge_only_side,
                    btc_signal=btc_signal,
                    btc_signal_error=btc_signal_error,
                )
                d = _apply_strong_normal_reverse(
                    cfg,
                    current,
                    book_up,
                    book_down,
                    t_rem,
                    dry_run,
                    scale_in_entry_slot,
                    d,
                )

        if d.action != "BUY":
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=d.price,
                ask_size=None,
                action=d.action,
                reason=d.reason,
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue

        if (
            cfg.one_side_per_market
            and locked_market_side is not None
            and d.side != locked_market_side
        ):
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=d.price,
                ask_size=None,
                action="SKIP_ONE_SIDE",
                reason=(
                    f"{d.side} blocked; market is locked to "
                    f"{locked_market_side} by an effective buy"
                ),
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue

        trend_side, trend_count = _previous_winner_streak(
            cfg,
            current,
            previous_winner_streak_cache,
        )
        if _trend_overheat_blocks_entry(
            cfg,
            d.side,
            d.entry_rule,
            d.price,
            trend_side,
            trend_count,
        ):
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=d.price,
                ask_size=None,
                action="SKIP_TREND_OVERHEAT",
                reason=(
                    f"{d.side} {d.entry_rule} blocked by trend overheat; "
                    f"previous {trend_count}x {trend_side}, "
                    f"price={d.price:.2f} >= {cfg.trend_overheat_price_floor:.2f}"
                ),
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue

        # P1: raise fresh-entry confirmation to at least three observations;
        # persisted CONFIRM_CHECKS=2 remains compatible because the execution
        # guard holds the order until the third candidate sample.
        if bool(getattr(cfg, "entry_guard_enabled", True)) and retry_side is None:
            if d.entry_rule == "stable_delta":
                observed_confirmations = int(
                    getattr(strategy_state, "stable_delta_count", 0) or 0
                )
            else:
                observed_confirmations = int(
                    getattr(strategy_state, "confirm_count", 0) or 0
                )
            required_guard_confirmations = max(
                int(getattr(cfg, "entry_guard_min_confirm_checks", 3) or 3),
                1,
            )
            if observed_confirmations > 0 and observed_confirmations < required_guard_confirmations:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=d.price,
                    ask_size=None,
                    action="SKIP_ENTRY_CONFIRM_GUARD",
                    reason=(
                        f"{d.side} {d.entry_rule} execution confirmation "
                        f"{observed_confirmations}/{required_guard_confirmations}"
                    ),
                    dry_run=dry_run,
                )
                time.sleep(cfg.poll_interval_sec)
                continue

        equity = account_equity_usd(cfg, dry_run)

        # Pocket-Kelly sizing switch (KELLY_SIZING_ENABLED, default off).
        # None -> legacy sizing untouched; 0.0 -> pocket unqualified, skip the
        # entry; >0 -> replace the flat risk fraction, which then flows through
        # both target_order_size calls via d.risk_fraction.
        kelly_fraction = KELLY_SIZING.fraction(asset, t_rem, float(d.price or 0.0))
        if kelly_fraction is not None:
            if kelly_fraction <= 0.0:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=d.price,
                    ask_size=None,
                    action="SKIP_KELLY_POCKET",
                    reason=(
                        f"{d.side} ask={d.price} t_rem={t_rem:.1f}s "
                        f"outside qualified Kelly pockets"
                    ),
                    dry_run=dry_run,
                )
                continue
            d = replace(d, risk_fraction=kelly_fraction)

        # Once the conservative recovery latch is active, cap this entry to
        # the recovery budget before either sizing pass.  The normal loss cap
        # remains enforced by allowed_to_trade unless this exact decision is
        # passed to both risk gates below.
        if (
            recovery_decision.allow_entries
            and recovery_decision.risk_fraction is not None
        ):
            normal_fraction = (
                cfg.order_risk_fraction
                if d.risk_fraction is None
                else float(d.risk_fraction)
            )
            d = replace(
                d,
                risk_fraction=min(
                    normal_fraction,
                    float(recovery_decision.risk_fraction),
                ),
            )

        side_book = book_up if d.side == "UP" else book_down
        order_size = target_order_size(
            cfg,
            ask_price=d.price or 0.0,
            ask_size=side_book.ask_size,
            equity_usd=equity,
            fee_per_share=d.fee or 0.0,
            risk_fraction=d.risk_fraction,
        )
        fee = d.fee or 0.0
        initial_amount_usd, initial_order_size = market_buy_amount_and_shares(
            d.price or 0.0,
            order_size,
            tick_size=current.tick_size,
            min_notional_usd=cfg.effective_min_order_notional_usd,
        )
        if initial_amount_usd > 0:
            order_cost = initial_amount_usd
            order_size = initial_order_size
        else:
            order_cost = order_size * (d.price or 0.0)

        ok, why = allowed_to_trade(
            cfg,
            dry_run,
            equity_usd=equity,
            order_cost_usd=order_cost,
            risk_fraction=d.risk_fraction,
            asset=asset,
            recovery=recovery_decision,
        )
        if not ok:
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=d.price,
                ask_size=side_book.ask_size,
                action="SKIP_RISK",
                reason=why,
                dry_run=dry_run,
            )
            log.info("risk gate: %s", why)
            time.sleep(cfg.poll_interval_sec)
            continue

        exec_btc_signal = btc_signal
        if (cfg.btc_delta_filter_enabled or d.entry_rule == "stable_delta") and d.entry_rule != "tail_price":
            try:
                exec_btc_signal = fetch_btc_signal(cfg, current)
            except Exception as e:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=d.price,
                    ask_size=side_book.ask_size,
                    action="SKIP_EXEC_BTC_SIGNAL",
                    reason=f"execution BTC delta signal unavailable: {e}",
                    dry_run=dry_run,
                )
                time.sleep(cfg.poll_interval_sec)
                continue
            guard_reason = price_source_guard_reason(cfg, current, exec_btc_signal)
            if guard_reason:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=d.price,
                    ask_size=side_book.ask_size,
                    action="SKIP_EXEC_PRICE_SOURCE",
                    reason=f"{d.side} {d.entry_rule} blocked before FOK: {guard_reason}",
                    dry_run=dry_run,
                )
                time.sleep(cfg.poll_interval_sec)
                continue
            if (
                d.entry_rule == "stable_delta"
                and btc_signal is not None
                and abs(abs(exec_btc_signal.delta_usd) - abs(btc_signal.delta_usd))
                >= cfg.stable_delta_entry_max_delta_move_usd
            ):
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=d.price,
                    ask_size=side_book.ask_size,
                    action="SKIP_EXEC_DELTA_JUMP",
                    reason=(
                        f"{d.side} stable_delta blocked before FOK; "
                        f"abs_delta moved "
                        f"{abs(abs(exec_btc_signal.delta_usd) - abs(btc_signal.delta_usd)):.2f} >= "
                        f"{cfg.stable_delta_entry_max_delta_move_usd:.2f}; "
                        f"confirm_delta={btc_signal.delta_usd:+.2f} "
                        f"exec_delta={exec_btc_signal.delta_usd:+.2f}"
                    ),
                    dry_run=dry_run,
                )
                time.sleep(cfg.poll_interval_sec)
                continue
            if not btc_signal_allows_entry(
                cfg, exec_btc_signal, d.side, d.entry_rule, d.price
            ):
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=d.price,
                    ask_size=side_book.ask_size,
                    action="SKIP_EXEC_BTC_SIGNAL",
                    reason=(
                        f"{d.side} blocked before FOK by price signal filter; "
                        f"{exec_btc_signal.describe()} "
                        f"{btc_signal_entry_description(cfg, d.entry_rule)}"
                    ),
                    dry_run=dry_run,
                )
                time.sleep(cfg.poll_interval_sec)
                continue
            reversal_reason = entry_guard_reversal_reason(
                cfg,
                previous=previous_entry_signal,
                current_ts=time.time(),
                current_delta=float(exec_btc_signal.delta_usd),
                side=d.side,
            )
            if reversal_reason:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=d.price,
                    ask_size=side_book.ask_size,
                    action="SKIP_ENTRY_REVERSAL",
                    reason=reversal_reason,
                    dry_run=dry_run,
                )
                time.sleep(cfg.poll_interval_sec)
                continue

        # Re-read the selected side immediately before FOK. On these markets the
        # top ask can disappear between the strategy check and order submission.
        try:
            fresh_book = fetch_book(cfg.clob_host, d.token_id)
        except Exception as e:
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=d.price,
                ask_size=side_book.ask_size,
                action="SKIP_EXEC_BOOK",
                reason=f"execution book refresh failed: {e}",
                dry_run=dry_run,
            )
            log.warning("execution book refresh failed: %s", e)
            time.sleep(cfg.poll_interval_sec)
            continue

        fresh_ask = fresh_book.best_ask
        fresh_book_timestamp = float(getattr(fresh_book, "fetched_at", 0.0) or 0.0)
        fresh_book_age = (
            max(0.0, time.time() - fresh_book_timestamp)
            if fresh_book_timestamp
            else 0.0
        )
        if (
            not dry_run
            and fresh_book_timestamp
            and fresh_book_age > max(float(getattr(cfg, "execution_book_max_age_sec", 3.0)), 0.1)
        ):
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=fresh_ask,
                ask_size=fresh_book.ask_size,
                action="SKIP_EXEC_STALE_BOOK",
                reason=f"entry book age={fresh_book_age:.2f}s exceeds execution limit",
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue
        if fresh_ask is None:
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=None,
                ask_size=fresh_book.ask_size,
                action="SKIP_EXEC_PRICE",
                reason="execution book has no ask",
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue

        configured_price_floor, configured_price_cap = entry_price_bounds(
            cfg, d.entry_rule, d.side
        )
        price_floor = max(configured_price_floor, CLOB_BUY_MIN_PRICE)
        price_cap = min(configured_price_cap, CLOB_BUY_MAX_PRICE)
        price_buffer = max(cfg.fok_price_buffer_ticks, 0) * current.tick_size
        order_limit_price = buy_limit_price(
            fresh_ask=fresh_ask,
            price_buffer=price_buffer,
            price_cap=price_cap,
        )
        if _trend_overheat_blocks_entry(
            cfg,
            d.side,
            d.entry_rule,
            order_limit_price,
            trend_side,
            trend_count,
        ):
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=fresh_ask,
                ask_size=fresh_book.ask_size,
                action="SKIP_EXEC_TREND_OVERHEAT",
                reason=(
                    f"{d.side} {d.entry_rule} blocked before FOK by trend overheat; "
                    f"previous {trend_count}x {trend_side}, "
                    f"limit={order_limit_price:.2f} >= {cfg.trend_overheat_price_floor:.2f}, "
                    f"fresh_ask={fresh_ask:.2f}"
                ),
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue
        exec_fee = taker_fee_per_share(cfg, order_limit_price)
        if not dry_run and getattr(cfg, 'profit_net_enabled', False):
            try:
                exec_fee = float(FeeSchedule.from_market(current.fee_metadata or {}).fee(
                    1, order_limit_price, role='TAKER', conservative=True))
            except (ValueError, TypeError, ArithmeticError):
                store.log_decision(market_slug=current.market_slug, condition_id=current.condition_id,
                    token_id=d.token_id, side=d.side, t_remaining=t_rem, ask_price=order_limit_price,
                    ask_size=fresh_book.ask_size, action='SKIP_ENTRY_FEES',
                    reason='current market fee schedule unavailable', dry_run=False)
                time.sleep(cfg.poll_interval_sec)
                continue
        exec_edge = 1.0 - order_limit_price - exec_fee
        fresh_order_size = target_order_size(
            cfg,
            ask_price=order_limit_price,
            ask_size=fresh_book.ask_size,
            equity_usd=equity,
            fee_per_share=exec_fee,
            risk_fraction=d.risk_fraction,
        )
        min_order_notional = cfg.effective_min_order_notional_usd
        fresh_amount_usd, fresh_order_size = market_buy_amount_and_shares(
            order_limit_price,
            fresh_order_size,
            tick_size=current.tick_size,
            min_notional_usd=min_order_notional,
        )
        fresh_cost = fresh_amount_usd
        depth_reason = entry_guard_depth_reason(
            cfg,
            visible_ask_size=getattr(fresh_book, "ask_size", None),
            requested_size=fresh_order_size,
        )
        if depth_reason:
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=fresh_ask,
                ask_size=getattr(fresh_book, "ask_size", None),
                action="SKIP_ENTRY_DEPTH",
                reason=depth_reason,
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue
        min_order_size_shares = cfg.effective_min_order_size_shares
        if (not dry_run) and fresh_order_size + 1e-9 < min_order_size_shares:
            # Polymarket requires at least five outcome shares. With a small
            # account, a strict 2% budget can calculate 4.x shares at a 0.84-
            # 0.90 quote and silently block every otherwise valid entry. Allow
            # the exchange floor when it fits the available balance and stays
            # within a small, explicit risk buffer; otherwise keep the safe
            # skip. This preserves the configured risk target for normal-sized
            # accounts and makes the unavoidable minimum-order exception audit.
            configured_risk = entry_risk_fraction(cfg, d.entry_rule)
            floor_risk_ceiling = configured_risk + max(
                0.0, float(getattr(cfg, "min_order_risk_buffer_fraction", 0.0025) or 0.0)
            )
            floor_amount_usd, floor_size = market_buy_amount_and_shares(
                order_limit_price,
                min_order_size_shares,
                tick_size=current.tick_size,
                min_notional_usd=min_order_notional,
            )
            available_after_reserve = max(
                0.0, float(equity or 0.0) - float(cfg.order_balance_reserve_usd)
            )
            floor_allowed = (
                floor_size + 1e-9 >= min_order_size_shares
                and floor_amount_usd > 0
                and floor_amount_usd <= available_after_reserve + 1e-9
                and (not equity or floor_amount_usd <= float(equity) * floor_risk_ceiling + 1e-9)
            )
            if floor_allowed:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=fresh_ask,
                    ask_size=fresh_book.ask_size,
                    action="MIN_ORDER_SIZE_FLOOR",
                    reason=(
                        f"raised {fresh_order_size:.4f} to CLOB minimum {floor_size:.4f} shares; "
                        f"amount=${floor_amount_usd:.2f}; configured risk={configured_risk:.2%}; "
                        f"risk ceiling={floor_risk_ceiling:.2%}"
                    ),
                    dry_run=False,
                )
                fresh_amount_usd, fresh_order_size = floor_amount_usd, floor_size
                fresh_cost = fresh_amount_usd
            else:
                min_size_skipped_markets.add(current.condition_id)
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=fresh_ask,
                    ask_size=fresh_book.ask_size,
                    action="SKIP_MIN_ORDER_SIZE",
                    reason=(
                        f"calculated order size={fresh_order_size:.4f} shares "
                        f"below CLOB minimum={min_order_size_shares:.4f} shares; "
                        f"amount=${fresh_amount_usd:.2f}; risk={configured_risk:.2%}; "
                        f"minimum floor exceeds balance/risk ceiling"
                    ),
                    dry_run=False,
                )
                log.warning(
                    "skip live BUY %s: %.4f shares below CLOB minimum %.4f "
                    "(amount=$%.2f, risk=%.2f%%); no retry for this market",
                    current.market_slug, fresh_order_size, min_order_size_shares,
                    fresh_amount_usd, configured_risk * 100,
                )
                time.sleep(cfg.poll_interval_sec)
                continue
        min_exec_size = min_order_notional / max(order_limit_price, 1e-9)
        min_exec_edge = required_net_edge(cfg, order_limit_price, d.entry_rule)
        edge_ok = (
            True
            if d.entry_rule not in ("edge", "late_edge", "stable_delta", "strong_delta", "early_strong_delta")
            else exec_edge > min_exec_edge
        )
        retry_key = (current.condition_id, retry_slot, str(d.side))
        retry_reference_price = buy_retry_reference_prices.get(retry_key)
        retry_chase_reason = retry_chase_block_reason(
            retry_side=retry_side,
            retry_reference_price=retry_reference_price,
            order_limit_price=order_limit_price,
            fresh_ask=fresh_ask,
            tick_size=current.tick_size,
            max_retry_price_drift_ticks=cfg.max_retry_price_drift_ticks,
        )
        if retry_chase_reason is not None:
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=fresh_ask,
                ask_size=fresh_book.ask_size,
                action="SKIP_RETRY_CHASE",
                reason=retry_chase_reason,
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue
        if (
            fresh_ask > price_cap
            or order_limit_price < price_floor
            or not edge_ok
            or fresh_book.ask_size < min_exec_size
            or fresh_amount_usd < min_order_notional
        ):
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=fresh_ask,
                ask_size=fresh_book.ask_size,
                action="SKIP_EXEC_REPRICE",
                reason=(
                    f"exec ask={fresh_ask} limit={order_limit_price} floor={price_floor} "
                    f"cap={price_cap} cfg_cap={configured_price_cap} size={fresh_book.ask_size} "
                    f"edge={exec_edge:.4f} min_edge={min_exec_edge:.4f} "
                    f"rule={d.entry_rule} amount={fresh_amount_usd:.2f}; "
                    f"original ask={d.price}"
                ),
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue

        ok, why = allowed_to_trade(
            cfg,
            dry_run,
            equity_usd=equity,
            order_cost_usd=fresh_cost,
            risk_fraction=d.risk_fraction,
            asset=asset,
            recovery=recovery_decision,
        )
        if not ok:
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=fresh_ask,
                ask_size=fresh_book.ask_size,
                action="SKIP_EXEC_RISK",
                reason=why,
                dry_run=dry_run,
            )
            log.info("execution risk gate: %s", why)
            time.sleep(cfg.poll_interval_sec)
            continue

        clob_collateral: Optional[CollateralBalance] = None
        order_balance_for_sdk: Optional[float] = None
        if not dry_run:
            assert client is not None
            try:
                clob_collateral = get_collateral_balance_allowance(
                    client,
                    chain_id=cfg.chain_id,
                    neg_risk=current.neg_risk,
                )
            except Exception as e:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=fresh_ask,
                    ask_size=fresh_book.ask_size,
                    action="SKIP_BALANCE",
                    reason=f"CLOB balance/allowance check failed before BUY: {e}",
                    dry_run=dry_run,
                )
                log.warning("CLOB balance/allowance check failed: %s", e)
                time.sleep(cfg.poll_interval_sec)
                continue

            order_balance_for_sdk = clob_collateral.spendable_usd(
                cfg.order_balance_reserve_usd
            )
            min_order_notional = cfg.effective_min_order_notional_usd
            if order_balance_for_sdk < min_order_notional:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=fresh_ask,
                    ask_size=fresh_book.ask_size,
                    action="SKIP_BALANCE",
                    reason=(
                        f"CLOB spendable=${order_balance_for_sdk:.6f} below "
                        f"minimum=${min_order_notional:.2f}; "
                        f"balance=${clob_collateral.balance_usd:.6f} "
                        f"allowance=${clob_collateral.allowance_usd:.6f} "
                        f"reserve=${cfg.order_balance_reserve_usd:.2f}"
                    ),
                    dry_run=dry_run,
                )
                time.sleep(cfg.poll_interval_sec)
                continue

            max_order_amount = math.floor(
                (order_balance_for_sdk + 1e-9) * 100
            ) / 100
            if fresh_amount_usd > max_order_amount + 1e-9:
                capped_amount, capped_size = market_buy_amount_and_shares(
                    order_limit_price,
                    order_balance_for_sdk / max(order_limit_price, 1e-9),
                    tick_size=current.tick_size,
                    min_notional_usd=min_order_notional,
                )
                if capped_amount < min_order_notional or capped_size <= 0:
                    store.log_decision(
                        market_slug=current.market_slug,
                        condition_id=current.condition_id,
                        token_id=d.token_id,
                        side=d.side,
                        t_remaining=t_rem,
                        ask_price=fresh_ask,
                        ask_size=fresh_book.ask_size,
                        action="SKIP_BALANCE",
                        reason=(
                            f"CLOB spendable=${order_balance_for_sdk:.6f} cannot "
                            f"support minimum order after rounding; "
                            f"balance=${clob_collateral.balance_usd:.6f} "
                            f"allowance=${clob_collateral.allowance_usd:.6f}"
                        ),
                        dry_run=dry_run,
                    )
                    time.sleep(cfg.poll_interval_sec)
                    continue
                log.info(
                    "cap BUY amount by CLOB collateral requested=%.2f capped=%.2f "
                    "balance=%.6f allowance=%.6f reserve=%.2f",
                    fresh_amount_usd,
                    capped_amount,
                    clob_collateral.balance_usd,
                    clob_collateral.allowance_usd,
                    cfg.order_balance_reserve_usd,
                )
                fresh_amount_usd = capped_amount
                fresh_order_size = capped_size
                fresh_cost = capped_amount

            if clob_collateral.allowance_usd + 1e-9 < fresh_amount_usd:
                store.log_decision(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    t_remaining=t_rem,
                    ask_price=fresh_ask,
                    ask_size=fresh_book.ask_size,
                    action="SKIP_BALANCE",
                    reason=(
                        f"CLOB allowance=${clob_collateral.allowance_usd:.6f} "
                        f"below order amount=${fresh_amount_usd:.2f}; "
                        f"contract={clob_collateral.allowance_contract}"
                    ),
                    dry_run=dry_run,
                )
                time.sleep(cfg.poll_interval_sec)
                continue

        d = type(d)(
            action=d.action,
            side=d.side,
            token_id=d.token_id,
            price=order_limit_price,
            size=fresh_order_size,
            fee=exec_fee,
            net_edge=exec_edge,
            entry_rule=d.entry_rule,
            risk_fraction=d.risk_fraction,
            reason=(
                f"{d.side} {d.entry_rule} exec_ask={fresh_ask} limit={order_limit_price} "
                f"fee={exec_fee:.4f} net_edge={exec_edge:.4f} book_size={fresh_book.ask_size} "
                f"amount=${fresh_amount_usd:.2f} order_size={fresh_order_size} "
                f"risk={entry_risk_fraction(cfg, d.entry_rule):.0%} t_rem={t_rem:.1f}s"
                + (
                    f" clob_balance={clob_collateral.balance_usd:.6f}"
                    f" clob_allowance={clob_collateral.allowance_usd:.6f}"
                    f" reserve={cfg.order_balance_reserve_usd:.2f}"
                    if clob_collateral is not None
                    else ""
                )
                + (f" scale_in={scale_in_entry_slot}" if scale_in_entry_slot else "")
                + (f" {exec_btc_signal.describe()}" if exec_btc_signal is not None else "")
            ),
        )
        side_book = fresh_book
        order_size = fresh_order_size
        fee = exec_fee
        order_cost = fresh_cost

        log.info(
            "BUY %s %s sz=%s @ %s edge=%.4f cost=%.2f equity=%s t_rem=%.1fs dry=%s",
            d.side,
            current.market_slug,
            order_size,
            d.price,
            d.net_edge or 0.0,
            order_cost,
            f"{equity:.2f}" if equity is not None else "unknown",
            t_rem,
            dry_run,
        )
        store.log_decision(
            market_slug=current.market_slug,
            condition_id=current.condition_id,
            token_id=d.token_id,
            side=d.side,
            t_remaining=t_rem,
            ask_price=d.price,
            ask_size=side_book.ask_size,
            action="BUY",
            reason=f"{d.reason} cost={order_cost:.2f} equity={equity if equity is not None else 'unknown'}",
            dry_run=dry_run,
        )
        # Log-only Kelly pocket shadow: records what pocket sizing would do
        # next to the actual order; never alters behavior (see kelly_shadow.py).
        KELLY_SHADOW.observe(
            asset=asset,
            market_slug=current.market_slug,
            side=d.side,
            entry_rule=d.entry_rule,
            ask=float(d.price),
            t_remaining=t_rem,
            equity=equity,
            actual_size=order_size,
            actual_cost=order_cost,
            dry_run=dry_run,
        )

        if dry_run:
            store.log_order(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                size=order_size,
                price=d.price,
                order_id=None,
                status="dry_run",
                filled_size=0.0,
                entry_rule=d.entry_rule,
                dry_run=True,
            )
            if recovery_decision.allow_entries:
                record_loss_recovery_entry(asset)
            bought_this_window.add(current.condition_id)
        else:
            with order_gate.entry() as entry_allowed:
                if not entry_allowed:
                    time.sleep(cfg.poll_interval_sec)
                    continue
                assert client is not None and live_guard is not None
                if getattr(cfg, 'profit_net_enabled', False):
                    try:
                        p2_reason, _ = _p2_entry_quote(cfg, current, fresh_book, order_size, d.price,
                            d.entry_rule, side=d.side, signal=exec_btc_signal)
                    except (ValueError, TypeError, ArithmeticError):
                        p2_reason = 'market_fee_or_execution_metadata_unavailable'
                    if p2_reason:
                        store.log_decision(market_slug=current.market_slug, condition_id=current.condition_id,
                            token_id=d.token_id, side=d.side, t_remaining=current.t_remaining(), ask_price=d.price,
                            ask_size=fresh_book.ask_size, action='SKIP_P2_ENTRY', reason=p2_reason, dry_run=False)
                        continue
                claimed, claim_reason = live_guard.claim_entry(current, d.token_id, d.side, order_size, d.price)
                if not claimed:
                    store.log_decision(market_slug=current.market_slug, condition_id=current.condition_id,
                        token_id=d.token_id, side=d.side, t_remaining=t_rem, ask_price=d.price,
                        ask_size=fresh_book.ask_size, action="SKIP_ENTRY_INTENT", reason=claim_reason, dry_run=False)
                    time.sleep(cfg.poll_interval_sec)
                    continue
                maker_mode = str(getattr(cfg, "entry_order_mode", "TAKER")).upper() in {"MAKER_FIRST", "HYBRID"}
                maker_price = None
                maker_size = order_size
                if maker_mode and fresh_book.best_bid is not None:
                    candidate = _floor_price_to_tick(float(fresh_book.best_bid), current.tick_size)
                    configured_min, configured_max = entry_price_bounds(cfg, d.entry_rule, d.side)
                    # A passive buy must be below the ask and remain in the
                    # configured strategy zone.  Otherwise use the existing
                    # taker path (unless the maker result is ambiguous).
                    if (
                        candidate >= configured_min - 1e-9
                        and candidate <= configured_max + 1e-9
                        and fresh_book.best_ask is not None
                        and candidate < float(fresh_book.best_ask) - 1e-9
                    ):
                        maker_price = candidate
                        # Keep the maker request bounded by the strategy target.
                        # A lower bid needs more shares for the same notional; if
                        # we submit that larger size, a full maker fill can exceed
                        # the risk-sized target before the residual fallback runs.
                        maker_size = min(
                            order_size,
                            _floor_size(fresh_amount_usd / max(candidate, 1e-9)),
                        )
                log.info(
                    "SUBMIT %s amount=%.2f price=%s shares_est=%s tick=%s neg_risk=%s",
                    "maker" if maker_price is not None else "market_fok",
                    fresh_amount_usd,
                    d.price,
                    order_size,
                    current.tick_size,
                    current.neg_risk,
                )
                buy_attempts[current.condition_id] = time.time()
                buy_attempt_counts[current.condition_id] = buy_attempt_count + 1
                buy_retry_reference_prices.setdefault(retry_key, order_limit_price)
                submitted_buy_price = maker_price if maker_price is not None else d.price
                maker_result: Optional[OrderResult] = None
                maker_fill_size = 0.0
                fallback_requested_size = 0.0
                if maker_price is not None:
                    maker_result = place_buy_maker(
                        client,
                        token_id=d.token_id,
                        price=maker_price,
                        size=maker_size,
                        tick_size=current.tick_size,
                        neg_risk=current.neg_risk,
                        order_type=getattr(cfg, "entry_maker_order_type", "GTC"),
                        ttl_sec=getattr(cfg, "entry_maker_ttl_sec", 3.0),
                        post_only=getattr(cfg, "entry_maker_post_only", True),
                        condition_id=current.condition_id,
                        best_bid=fresh_book.best_bid,
                        best_ask=fresh_book.best_ask,
                        cancel_event=order_gate.urgent,
                    )
                    # A canceled maker order may safely fall back to the old
                    # taker path.  An ambiguous cancel must stop here: submitting
                    # another order could duplicate exposure.
                    result = maker_result
                    maker_filled = max(float(maker_result.filled_size or 0.0), 0.0)
                    maker_fill_size = maker_filled
                    maker_needs_fallback = (
                        getattr(cfg, "entry_maker_fallback_taker", True)
                        and not order_gate.urgent.is_set()
                        and not maker_result.ambiguous
                        and maker_result.fallback_safe
                        and float(maker_result.remaining_size or 0.0) > 0.02
                        and maker_filled < order_size - 0.02
                    )
                    if maker_needs_fallback:
                        # Convert only the residual shares to USD.  The previous
                        # implementation submitted the full amount again after a
                        # partial maker fill, which could double the position.
                        residual_size = _maker_fallback_size(maker_result,
                            target_size=order_size, total_budget=fresh_amount_usd,
                            maker_price=maker_price, taker_price=d.price,
                            fee_per_share=exec_fee)
                        if getattr(cfg, 'profit_net_enabled', False) and residual_size > 0:
                            try:
                                fallback_book = (stream.latest_book(d.token_id,
                                    max_age_sec=cfg.ws_exit_max_book_age_sec) if exit_supervisor is not None
                                    else fetch_book(cfg.clob_host, d.token_id))
                                fallback_signal = (fetch_btc_signal(cfg, current)
                                    if (cfg.btc_delta_filter_enabled or d.entry_rule == 'stable_delta')
                                    and d.entry_rule != 'tail_price' else None)
                                p2_reason, _ = _p2_entry_quote(cfg, current, fallback_book, residual_size,
                                    d.price, d.entry_rule, side=d.side, signal=fallback_signal)
                                if fallback_signal is not None:
                                    p2_reason = p2_reason or price_source_guard_reason(cfg, current, fallback_signal)
                                if order_gate.urgent.is_set():
                                    p2_reason = 'urgent_exit_preempted_entry'
                            except (ValueError, TypeError, ArithmeticError, AttributeError):
                                p2_reason = 'fallback_fresh_data_unavailable'
                            except Exception as exc:
                                p2_reason = 'fallback_refresh_' + type(exc).__name__
                            if p2_reason:
                                residual_size = 0.
                                store.log_decision(market_slug=current.market_slug, condition_id=current.condition_id,
                                    token_id=d.token_id, side=d.side, t_remaining=current.t_remaining(), ask_price=d.price,
                                    ask_size=None, action='SKIP_P2_FALLBACK', reason=p2_reason, dry_run=False)
                        if residual_size + 1e-9 >= cfg.effective_min_order_size_shares:
                            fallback_requested_size = residual_size
                            log.info(
                                "maker entry residual fallback: target=%.4f maker=%.4f residual=%.4f",
                                order_size, maker_filled, residual_size,
                            )
                            # Use a share-bounded FOK. A fixed dollar fallback can
                            # buy more than the verified residual if its execution
                            # price improves while the request is in flight.
                            fallback = place_buy_fok(
                                client,
                                token_id=d.token_id,
                                price=d.price,
                                size=residual_size,
                                tick_size=current.tick_size,
                                neg_risk=current.neg_risk,
                            )
                            result = _combine_buy_results(
                                maker_result,
                                fallback,
                                target_size=order_size,
                                maker_price=float(maker_result.avg_price or maker_price),
                                taker_price=float(d.price),
                            )
                    elif (
                        maker_result.status in {"maker_timeout_cancelled", "post_only_rejected"}
                        and getattr(cfg, "entry_maker_fallback_taker", True)
                        and not order_gate.urgent.is_set()
                        and maker_result.ambiguous
                    ):
                        # An uncertain maker cancellation must never be followed
                        # by a blind taker order that could duplicate exposure.
                        result = maker_result
                else:
                    result = place_buy_market_fok(
                        client,
                        token_id=d.token_id,
                        price=d.price,
                        amount_usd=fresh_amount_usd,
                        tick_size=current.tick_size,
                        neg_risk=current.neg_risk,
                        user_usdc_balance=order_balance_for_sdk,
                    )
                if result.ambiguous and not (maker_result is not None and maker_result.ambiguous):
                    combined = bool((result.raw or {}).get('component_order_ids'))
                    pending_component = fallback if combined else result
                    submitted_at = float((pending_component.raw or {}).get("submitted_at") or time.time())
                    try:
                        reconciled = reconcile_recent_trade(
                            client,
                            condition_id=current.condition_id,
                            token_id=d.token_id,
                            side="BUY",
                            submitted_at=submitted_at,
                            min_size=0.01,
                            order_id=pending_component.order_id,
                        )
                    except Exception as e:
                        reconciled = None
                        log.warning("buy timeout reconcile failed: %s", e)
                    if reconciled is not None and not reconciled.ambiguous:
                        log.info(
                            "buy timeout reconciled: status=%s filled=%s id=%s",
                            reconciled.status,
                            reconciled.filled_size,
                            reconciled.order_id,
                            )
                        if combined:
                            if reconciled.order_id != maker_result.order_id:
                                result = _combine_buy_results(maker_result, reconciled,
                                    target_size=order_size,
                                    maker_price=float(maker_result.avg_price or maker_price),
                                    taker_price=float(d.price))
                        elif reconciled.filled_size + 1e-6 >= result.filled_size:
                            result = reconciled
                elif (result.order_id and not (result.raw or {}).get("component_order_ids")
                      and str(result.status).lower() in {"matched", "filled", "partially_filled"}):
                    try:
                        reconciled = reconcile_recent_trade(
                            client,
                            condition_id=current.condition_id,
                            token_id=d.token_id,
                            side="BUY",
                            submitted_at=float((result.raw or {}).get("submitted_at") or time.time()),
                            min_size=0.01,
                            order_id=result.order_id,
                        )
                    except Exception as e:
                        reconciled = None
                        log.warning("buy fill reconcile failed: %s", e)
                    if (reconciled is not None and not reconciled.ambiguous
                            and reconciled.filled_size + 1e-6 >= result.filled_size):
                        # Preserve the verified terminal/cancel information and
                        # all prior evidence while enriching the actual fill.
                        result = replace(result, filled_size=reconciled.filled_size,
                            avg_price=reconciled.avg_price, filled_amount=reconciled.filled_amount,
                            raw={**(result.raw or {}), 'fill_reconciliation': reconciled.raw})
                live_guard.record_result(current, result, order_ids=tuple(
                    value for value in ((maker_result.order_id if maker_result else None),
                                        *((result.raw or {}).get("component_order_ids") or [])) if value))
                if result.filled_size and result.filled_size > 0:
                    buy_fill_price = (
                        result.avg_price
                        if result.avg_price is not None and result.avg_price > 0
                        else (
                            result.filled_amount / result.filled_size
                            if result.filled_amount is not None and result.filled_size > 0
                            else d.price
                        )
                    )
                    strategy_state.note_buy_fill(
                        current,
                        token_id=d.token_id,
                        side=d.side,
                        size=result.filled_size,
                        avg_price=buy_fill_price,
                        order_id=result.order_id,
                        ts=time.time(),
                    )
                store.log_order(
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    side=d.side,
                    size=order_size,
                    price=(
                        buy_fill_price
                        if result.filled_size and result.filled_size > 0
                        else submitted_buy_price
                    ),
                    order_id=result.order_id,
                    status="filled" if result.filled_size and result.filled_size > 0 else result.status,
                    filled_size=result.filled_size,
                    error=result.error,
                    entry_rule=d.entry_rule,
                    dry_run=False,
                )
                store.log_execution_audit(
                    event="entry_order_result",
                    asset=asset,
                    market_slug=current.market_slug,
                    condition_id=current.condition_id,
                    token_id=d.token_id,
                    lane="entry",
                    dry_run=False,
                    payload={
                        "target_size": float(order_size),
                        "maker_requested_size": float(maker_size if maker_price is not None else 0.0),
                        "maker_fill_size": float(maker_fill_size),
                        "fallback_requested_size": float(fallback_requested_size),
                        "total_filled_size": float(result.filled_size or 0.0),
                        "remaining_position": float(result.filled_size or 0.0),
                        "attempt_count": 2 if fallback_requested_size > 0 else 1,
                        "order_type": "MAKER_FIRST" if maker_price is not None else "FOK",
                        "status": result.status,
                        "failure_reason": result.error if not (result.filled_size and result.filled_size > 0) else None,
                        "intent_status": "completed" if result.filled_size and result.filled_size > 0 else ("ambiguous" if result.ambiguous else "failed"),
                        "t_remaining": float(t_rem),
                        "ask_depth": float(fresh_book.ask_size or 0.0),
                    },
                )
                log.info("order result: status=%s filled=%s id=%s err=%s",
                         result.status, result.filled_size, result.order_id, result.error)

                buy_filled = _update_buy_retry_state(
                    condition_id=current.condition_id,
                    retry_slot=retry_slot,
                    retry_key=retry_key,
                    side=d.side,
                    entry_rule=d.entry_rule,
                    filled_size=result.filled_size,
                    bought_this_window=bought_this_window,
                    buy_retry_sides=buy_retry_sides,
                    buy_retry_entry_rules=buy_retry_entry_rules,
                    buy_retry_reference_prices=buy_retry_reference_prices,
                )
                if not buy_filled:
                    time.sleep(cfg.poll_interval_sec)
                    continue

        time.sleep(cfg.poll_interval_sec)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="actually place orders (default: dry-run)")
    p.add_argument("--asset", choices=("BTC", "ETH", "btc", "eth"), default="BTC")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        loop(live=args.live, asset=args.asset.upper())
    except KeyboardInterrupt:
        pass
    finally:
        log.info("shutdown")


if __name__ == "__main__":
    main()
