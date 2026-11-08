"""Main event loop. Dry-run by default; --live to actually trade."""
from __future__ import annotations

import argparse
import logging
import math
import re
import time
from dataclasses import dataclass, replace
from typing import Optional

from bot import config, store
from bot.book import TopOfBook, fetch_book
from bot.btc_signal import BtcSignal, fetch_btc_signal
from bot.markets import LiveMarket, fetch_live_market
from bot.orders import (
    CollateralBalance,
    OrderResult,
    build_client,
    get_collateral_balance_allowance,
    place_buy_market_fok,
    place_sell_fak,
    place_sell_fok,
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
    attempts: list[ExitAttemptPlan] = [
        ExitAttemptPlan(
            order_type="FOK",
            size=requested_size,
            price=target_price,
            visible_size=visible_size,
            full_depth=full_price is not None,
        )
    ]
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
        if reconciled is not None:
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
    if not cfg.reversal_exit_enabled and not cfg.early_reversal_exit_enabled:
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
    if (
        min_exit_t_remaining is None
        or t_rem < min_exit_t_remaining
        or t_rem > exit_window
    ):
        return False

    open_orders = []
    if strategy_state is not None:
        open_orders = strategy_state.local_open_orders_for_market(current.condition_id)
        if not open_orders:
            hydrated_orders = store.open_orders_for_market(current.condition_id, dry_run)
            for order in hydrated_orders:
                strategy_state.hydrate_open_order(current, order)
            open_orders = strategy_state.local_open_orders_for_market(current.condition_id)
    if not open_orders:
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
        sell_bid = held_book.best_bid
        buy_price = (
            position.entry_price
            if position is not None and position.entry_price > 0
            else float(order["price"])
        )
        remaining_size = _floor_size(
            position.remaining_size if position is not None else float(order["size"])
        )
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
        if not early_exit and not partial_exit and not late_exit and not normal_exit:
            continue
        if early_exit:
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
        sell_fraction = 1.0
        exit_tier = "stop_loss" if exit_pending else (
            "early"
            if early_exit
            else ("partial" if partial_exit else ("late" if late_exit else "normal"))
        )
        key = (current.condition_id, held_side, exit_tier)
        now = time.time()

        if sell_bid is None or sell_bid <= 0:
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

        last_attempt_ts = exit_attempts.get(key, 0.0)
        if (
            not exit_pending
            and cfg.order_retry_cooldown_sec > 0
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
        if not attempts:
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=str(order["token_id"]),
                side=held_side,
                t_remaining=t_rem,
                ask_price=sell_bid,
                ask_size=held_book.bid_size,
                action="SKIP_EXIT_SIZE",
                reason=(
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
            exit_attempts[key] = time.time()
            store.log_order(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=str(order["token_id"]),
                side=f"SELL_{held_side}",
                size=first_attempt.size,
                price=first_attempt.price,
                order_id=None,
                status="exit_dry_run",
                filled_size=first_attempt.size * first_attempt.price,
                error=reason,
                dry_run=True,
            )
            return True

        assert client is not None
        exit_attempts[key] = time.time()
        for attempt in attempts:
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
            if effective or result.ambiguous:
                break
        return True

    return False


def loop(live: bool, asset: str = "BTC") -> None:
    base_cfg = config.load()
    asset = asset.upper()
    if live and base_cfg.instance_name == "polyauto":
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

    current: Optional[LiveMarket] = None
    last_market_refresh = 0.0
    last_resolve_check = 0.0
    bought_this_window: set[str] = set()
    buy_attempts: dict[str, float] = {}
    buy_attempt_counts: dict[str, int] = {}
    buy_retry_sides: dict[tuple[str, str], str] = {}
    buy_retry_entry_rules: dict[tuple[str, str], str] = {}
    retry_cap_logged: set[str] = set()
    strategy_state = StrategyState()
    exit_confirmations: dict[tuple[str, str, str], int] = {}
    exit_attempts: dict[tuple[str, str, str], float] = {}
    buy_retry_reference_prices: dict[tuple[str, str, str], float] = {}
    previous_winner_streak_cache: dict[str, tuple[Optional[str], int]] = {}

    # Settle anything left unresolved from prior runs before we start.
    try:
        resolve_pending(cfg, dry_run)
    except Exception as e:
        log.warning("initial resolve_pending failed: %s", e)

    while True:
        now = time.time()

        # Periodically resolve filled positions whose markets have closed.
        if now - last_resolve_check > 30:
            try:
                resolve_pending(cfg, dry_run)
            except Exception as e:
                log.warning("resolve_pending failed: %s", e)
            last_resolve_check = now

        stop_reason = daily_realized_profit_stop_reason(cfg, dry_run)
        if stop_reason is not None:
            log.warning("daily realized profit target reached: %s", stop_reason)
            break

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

        strategy_state.reset_for_market(current.condition_id)

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
        reversal_enabled = cfg.reversal_exit_enabled or cfg.early_reversal_exit_enabled
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
        if t_rem > buy_window_upper + 10:
            time.sleep(min(t_rem - buy_window_upper, 5.0))
            continue

        try:
            book_up = fetch_book(cfg.clob_host, current.up_token)
            book_down = fetch_book(cfg.clob_host, current.down_token)
        except Exception as e:
            log.warning("book fetch failed: %s", e)
            time.sleep(cfg.poll_interval_sec)
            continue

        btc_signal = None
        btc_signal_error = None
        if cfg.btc_delta_filter_enabled or cfg.reversal_exit_require_btc_reversal:
            try:
                btc_signal = fetch_btc_signal(cfg, current)
            except Exception as e:
                btc_signal_error = str(e)

        if maybe_reversal_exit(
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

        equity = account_equity_usd(cfg, dry_run)
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
            bought_this_window.add(current.condition_id)
        else:
            assert client is not None
            log.info(
                "SUBMIT market_fok amount=%.2f price=%s shares_est=%s tick=%s neg_risk=%s",
                fresh_amount_usd,
                d.price,
                order_size,
                current.tick_size,
                current.neg_risk,
            )
            buy_attempts[current.condition_id] = time.time()
            buy_attempt_counts[current.condition_id] = buy_attempt_count + 1
            buy_retry_reference_prices.setdefault(retry_key, order_limit_price)
            result = place_buy_market_fok(
                client,
                token_id=d.token_id,
                price=d.price,
                amount_usd=fresh_amount_usd,
                tick_size=current.tick_size,
                neg_risk=current.neg_risk,
                user_usdc_balance=order_balance_for_sdk,
            )
            if result.ambiguous:
                submitted_at = float((result.raw or {}).get("submitted_at") or time.time())
                try:
                    reconciled = reconcile_recent_trade(
                        client,
                        condition_id=current.condition_id,
                        token_id=d.token_id,
                        side="BUY",
                        submitted_at=submitted_at,
                        min_size=order_size,
                    )
                except Exception as e:
                    reconciled = None
                    log.warning("buy timeout reconcile failed: %s", e)
                if reconciled is not None:
                    log.info(
                        "buy timeout reconciled: status=%s filled=%s id=%s",
                        reconciled.status,
                        reconciled.filled_size,
                        reconciled.order_id,
                        )
                    result = reconciled
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
                price=d.price,
                order_id=result.order_id,
                status="filled" if result.filled_size and result.filled_size > 0 else result.status,
                filled_size=result.filled_size,
                error=result.error,
                entry_rule=d.entry_rule,
                dry_run=False,
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
