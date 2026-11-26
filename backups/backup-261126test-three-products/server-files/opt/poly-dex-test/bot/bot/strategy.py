"""Fee-aware late-window value buy.

The bot buys one likely-winning side when the residual payout edge survives
taker fees:

    net_edge = 1.00 - ask - taker_fee_per_share

The chosen side must pass twice in a row for the same market before an order is
allowed. Protective last-window exits are handled by the main loop.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional

from bot.book import TopOfBook
from bot.btc_signal import BtcSignal
from bot.config import Config
from bot.markets import LiveMarket


@dataclass(frozen=True)
class Decision:
    action: str
    side: Optional[str] = None
    token_id: Optional[str] = None
    price: Optional[float] = None
    size: Optional[float] = None
    fee: Optional[float] = None
    net_edge: Optional[float] = None
    reason: str = ""
    entry_rule: str = "edge"
    risk_fraction: Optional[float] = None


@dataclass(frozen=True)
class _Candidate:
    side: str
    token_id: str
    ask: float
    ask_size: float
    fee: float
    net_edge: float
    entry_rule: str


@dataclass(frozen=True)
class _Snapshot:
    ts: float
    up_bid: Optional[float]
    up_ask: Optional[float]
    down_bid: Optional[float]
    down_ask: Optional[float]


@dataclass
class TrackedPosition:
    market_slug: str
    condition_id: str
    token_id: str
    side: str
    entry_size: float
    remaining_size: float
    entry_price: float
    entry_notional: float
    entry_order_id: Optional[str] = None
    entry_ts: float = 0.0
    stop_loss_pending: bool = False
    last_exit_attempt_ts: float = 0.0
    last_exit_order_id: Optional[str] = None

    def effective_order(self) -> dict:
        return {
            "id": None,
            "ts": self.entry_ts,
            "asset": None,
            "market_slug": self.market_slug,
            "condition_id": self.condition_id,
            "token_id": self.token_id,
            "side": self.side,
            "size": self.remaining_size,
            "price": self.entry_price,
            "order_id": self.entry_order_id,
            "status": "filled",
            "filled_size": self.entry_size,
            "error": None,
            "entry_rule": "local_tracker",
            "dry_run": 0,
        }

    def open_order(self) -> dict:
        return {
            "id": None,
            "ts": self.entry_ts,
            "market_slug": self.market_slug,
            "condition_id": self.condition_id,
            "token_id": self.token_id,
            "side": self.side,
            "entry_rule": "local_tracker",
            "size": self.remaining_size,
            "original_size": self.entry_size,
            "exited_size": max(self.entry_size - self.remaining_size, 0.0),
            "price": self.entry_price,
            "order_id": self.entry_order_id,
            "status": "filled",
            "filled_size": self.entry_size,
            "dry_run": 0,
        }


class StrategyState:
    """Short-lived per-process state for confirmations and book protections."""

    def __init__(self) -> None:
        self.market_id: Optional[str] = None
        self.snapshots: list[_Snapshot] = []
        self.confirm_key: Optional[tuple[str, str, str]] = None
        self.confirm_count = 0
        self.entry_momentum_key: Optional[tuple[str, str, str]] = None
        self.entry_momentum_first_ask: Optional[float] = None
        self.entry_momentum_previous_ask: Optional[float] = None
        self.entry_momentum_last_ask: Optional[float] = None
        self.stable_delta_key: Optional[tuple[str, str, str]] = None
        self.stable_delta_count = 0
        self.stable_delta_last_abs: Optional[float] = None
        self.local_positions: dict[tuple[str, str, str], TrackedPosition] = {}

    def reset_for_market(self, condition_id: str) -> None:
        if self.market_id == condition_id:
            return
        self.market_id = condition_id
        self.snapshots = []
        self.confirm_key = None
        self.confirm_count = 0
        self.entry_momentum_key = None
        self.entry_momentum_first_ask = None
        self.entry_momentum_previous_ask = None
        self.entry_momentum_last_ask = None
        self.stable_delta_key = None
        self.stable_delta_count = 0
        self.stable_delta_last_abs = None
        self.local_positions = {}

    def _position_key(self, condition_id: str, token_id: str, side: str) -> tuple[str, str, str]:
        return condition_id, token_id, side

    def note_buy_fill(
        self,
        market: LiveMarket,
        *,
        token_id: str,
        side: str,
        size: float,
        avg_price: float,
        order_id: Optional[str],
        ts: Optional[float] = None,
    ) -> Optional[TrackedPosition]:
        filled_size = max(float(size), 0.0)
        filled_price = max(float(avg_price), 0.0)
        if filled_size <= 0 or filled_price <= 0:
            return None
        key = self._position_key(market.condition_id, token_id, side)
        position = TrackedPosition(
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            token_id=token_id,
            side=side,
            entry_size=filled_size,
            remaining_size=filled_size,
            entry_price=filled_price,
            entry_notional=filled_size * filled_price,
            entry_order_id=order_id,
            entry_ts=float(ts if ts is not None else time.time()),
        )
        self.local_positions[key] = position
        return position

    def hydrate_open_order(self, market: LiveMarket, order: dict) -> Optional[TrackedPosition]:
        side = str(order.get("side") or "").upper()
        token_id = str(order.get("token_id") or "")
        if side not in ("UP", "DOWN") or not token_id:
            return None
        key = self._position_key(market.condition_id, token_id, side)
        position = self.local_positions.get(key)
        if position is not None:
            remaining_size = max(float(order.get("size") or position.remaining_size), 0.0)
            position.remaining_size = min(position.remaining_size, remaining_size)
            original_size = max(float(order.get("original_size") or position.entry_size), 0.0)
            position.entry_size = max(position.entry_size, original_size)
            if position.entry_size > 0 and position.remaining_size > position.entry_size:
                position.remaining_size = position.entry_size
            if position.entry_price <= 0:
                position.entry_price = max(float(order.get("price") or 0.0), 0.0)
            position.stop_loss_pending = position.stop_loss_pending or bool(order.get("stop_loss_pending"))
            return position

        remaining_size = max(float(order.get("size") or 0.0), 0.0)
        original_size = max(float(order.get("original_size") or remaining_size), 0.0)
        entry_price = max(float(order.get("price") or 0.0), 0.0)
        if remaining_size <= 0 or entry_price <= 0:
            return None
        position = TrackedPosition(
            market_slug=str(order.get("market_slug") or market.market_slug),
            condition_id=market.condition_id,
            token_id=token_id,
            side=side,
            entry_size=original_size,
            remaining_size=remaining_size,
            entry_price=entry_price,
            entry_notional=original_size * entry_price,
            entry_order_id=str(order.get("order_id")) if order.get("order_id") else None,
            entry_ts=float(order.get("ts") or time.time()),
        )
        self.local_positions[key] = position
        return position

    def local_effective_buy_orders_for_market(self, condition_id: str) -> list[dict]:
        return [
            position.effective_order()
            for key, position in self.local_positions.items()
            if key[0] == condition_id and position.remaining_size > 0.02
        ]

    def local_open_orders_for_market(self, condition_id: str) -> list[dict]:
        return [
            position.open_order()
            for key, position in self.local_positions.items()
            if key[0] == condition_id and position.remaining_size > 0.02
        ]

    def active_position(self, condition_id: str, token_id: str, side: str) -> Optional[TrackedPosition]:
        return self.local_positions.get(self._position_key(condition_id, token_id, side))

    def arm_stop_loss(self, condition_id: str, token_id: str, side: str) -> Optional[TrackedPosition]:
        position = self.active_position(condition_id, token_id, side)
        if position is None:
            return None
        position.stop_loss_pending = True
        return position

    def note_exit_fill(
        self,
        condition_id: str,
        token_id: str,
        side: str,
        filled_size: float,
        avg_price: float,
        *,
        order_id: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> Optional[TrackedPosition]:
        position = self.active_position(condition_id, token_id, side)
        if position is None:
            return None
        position.last_exit_attempt_ts = float(ts if ts is not None else time.time())
        position.last_exit_order_id = order_id or position.last_exit_order_id
        fill = max(float(filled_size), 0.0)
        if fill > 0:
            position.remaining_size = max(position.remaining_size - fill, 0.0)
        if position.remaining_size <= 0.02:
            self.local_positions.pop(self._position_key(condition_id, token_id, side), None)
            return None
        position.stop_loss_pending = True
        return position

    def add_snapshot(
        self,
        ts: float,
        book_up: TopOfBook,
        book_down: TopOfBook,
        keep_sec: float,
    ) -> None:
        cutoff = ts - max(keep_sec, 1.0)
        self.snapshots.append(
            _Snapshot(
                ts=ts,
                up_bid=book_up.best_bid,
                up_ask=book_up.best_ask,
                down_bid=book_down.best_bid,
                down_ask=book_down.best_ask,
            )
        )
        self.snapshots = [s for s in self.snapshots if s.ts >= cutoff]

    def note_candidate(self, market: LiveMarket, c: _Candidate) -> int:
        key = (market.condition_id, c.side, c.entry_rule)
        if key == self.confirm_key:
            self.confirm_count += 1
        else:
            self.confirm_key = key
            self.confirm_count = 1
        return self.confirm_count

    def entry_momentum_reset_reason(
        self,
        cfg: Config,
        market: LiveMarket,
        c: _Candidate,
    ) -> Optional[str]:
        if not cfg.entry_momentum_filter_enabled:
            return None
        if c.entry_rule == "tail_price":
            return None
        no_retreat_only = cfg.entry_momentum_max_ask_move <= 0
        if (
            not no_retreat_only
            and not (cfg.entry_momentum_min_price <= c.ask <= cfg.entry_momentum_max_price)
        ):
            return None

        key = (market.condition_id, c.side, c.entry_rule)
        if key != self.entry_momentum_key or self.entry_momentum_first_ask is None:
            self.entry_momentum_key = key
            self.entry_momentum_first_ask = c.ask
            self.entry_momentum_previous_ask = None
            self.entry_momentum_last_ask = c.ask
            return None

        self.entry_momentum_previous_ask = self.entry_momentum_last_ask
        self.entry_momentum_last_ask = c.ask
        return None

    def entry_momentum_confirmation_reason(
        self,
        cfg: Config,
        market: LiveMarket,
        c: _Candidate,
        confirmations: int,
        required_confirmations: int,
    ) -> Optional[str]:
        if not cfg.entry_momentum_filter_enabled:
            return None
        if c.entry_rule == "tail_price":
            return None
        if confirmations < required_confirmations:
            return None

        key = (market.condition_id, c.side, c.entry_rule)
        if key != self.entry_momentum_key or self.entry_momentum_first_ask is None:
            self.entry_momentum_key = key
            self.entry_momentum_first_ask = c.ask
            self.entry_momentum_previous_ask = None
            self.entry_momentum_last_ask = c.ask
            return None

        previous = self.entry_momentum_previous_ask
        self.entry_momentum_last_ask = c.ask
        if previous is None:
            return None
        tick_size = max(float(getattr(market, "tick_size", 0.01) or 0.01), 0.01)
        min_allowed = previous - tick_size
        move = abs(c.ask - previous)
        max_move = cfg.entry_momentum_max_ask_move
        if c.ask >= min_allowed - 1e-9 and (max_move <= 0 or move <= max_move + 1e-9):
            return None
        if c.ask >= min_allowed - 1e-9:
            return (
                f"{c.side} {c.entry_rule} final ask moved too fast "
                f"{previous:.3f}->{c.ask:.3f} "
                f"move={move:.3f} > {max_move:.3f}; waiting"
            )
        return (
            f"{c.side} {c.entry_rule} final ask {c.ask:.3f} "
            f"< previous ask {previous:.3f} - 1 tick ({tick_size:.3f}); waiting"
        )

    def note_stable_delta_candidate(
        self,
        market: LiveMarket,
        c: _Candidate,
        abs_delta: float,
        max_move: float,
    ) -> tuple[int, Optional[float]]:
        key = (market.condition_id, c.side, c.entry_rule)
        if key != self.stable_delta_key or self.stable_delta_last_abs is None:
            self.stable_delta_key = key
            self.stable_delta_count = 1
            self.stable_delta_last_abs = abs_delta
            return self.stable_delta_count, None

        move = abs(abs_delta - self.stable_delta_last_abs)
        self.stable_delta_last_abs = abs_delta
        if move >= max_move:
            self.stable_delta_count = 1
            return self.stable_delta_count, move

        self.stable_delta_count += 1
        return self.stable_delta_count, None


def taker_fee_per_share(cfg: Config, ask: float) -> float:
    return cfg.taker_fee_rate * ask * (1.0 - ask)


def buy_window_upper_sec(cfg: Config) -> float:
    upper = float(cfg.seconds_before_close)
    if cfg.early_strong_delta_entry_enabled:
        upper = max(upper, cfg.early_strong_delta_entry_window_sec)
    if cfg.strong_delta_entry_enabled:
        upper = max(upper, cfg.strong_delta_entry_window_sec)
    if cfg.late_edge_entry_enabled:
        upper = max(upper, cfg.late_edge_entry_window_sec)
    if cfg.stable_delta_entry_enabled:
        upper = max(upper, cfg.stable_delta_entry_window_sec)
    if cfg.mid_entry_enabled:
        upper = max(upper, cfg.mid_entry_window_sec)
    if not cfg.early_entry_enabled:
        return upper
    return max(upper, cfg.early_entry_seconds_before_close)


def mid_entry_active(cfg: Config, t_remaining: float) -> bool:
    return (
        cfg.mid_entry_enabled
        and t_remaining >= cfg.mid_entry_min_t_remaining_sec
        and t_remaining <= cfg.mid_entry_window_sec
    )


def strong_delta_entry_active(cfg: Config, t_remaining: float) -> bool:
    return (
        cfg.strong_delta_entry_enabled
        and t_remaining >= cfg.strong_delta_entry_min_t_remaining_sec
        and t_remaining <= cfg.strong_delta_entry_window_sec
    )


def early_strong_delta_entry_active(cfg: Config, t_remaining: float) -> bool:
    return (
        cfg.early_strong_delta_entry_enabled
        and t_remaining >= cfg.early_strong_delta_entry_min_t_remaining_sec
        and t_remaining <= cfg.early_strong_delta_entry_window_sec
    )


def early_strong_delta_hedge_active(cfg: Config, t_remaining: float) -> bool:
    return cfg.early_strong_delta_entry_hedge_enabled and early_strong_delta_entry_active(
        cfg, t_remaining
    )


def early_entry_active(cfg: Config, t_remaining: float) -> bool:
    return (
        cfg.early_entry_enabled
        and t_remaining > cfg.seconds_before_close
        and t_remaining <= cfg.early_entry_seconds_before_close
    )


def late_edge_entry_active(cfg: Config, t_remaining: float) -> bool:
    return (
        cfg.late_edge_entry_enabled
        and t_remaining >= cfg.late_edge_entry_min_t_remaining_sec
        and t_remaining <= cfg.late_edge_entry_window_sec
    )


def stable_delta_entry_active(cfg: Config, t_remaining: float) -> bool:
    return (
        cfg.stable_delta_entry_enabled
        and t_remaining >= cfg.stable_delta_entry_min_t_remaining_sec
        and t_remaining <= cfg.stable_delta_entry_window_sec
    )


def tail_entry_active(cfg: Config, t_remaining: float) -> bool:
    return (
        cfg.tail_entry_enabled
        and t_remaining >= cfg.tail_entry_min_t_remaining_sec
        and t_remaining <= cfg.tail_entry_window_sec
    )


def entry_price_bounds(
    cfg: Config,
    entry_rule: str,
    side: Optional[str] = None,
) -> tuple[float, float]:
    if entry_rule == "early_price":
        min_price, max_price = cfg.early_entry_min_price, cfg.early_entry_max_price
    elif entry_rule == "tail_price":
        return cfg.tail_entry_min_price, cfg.tail_entry_max_price
    elif entry_rule == "strong_normal_reverse":
        return cfg.strong_normal_reverse_min_price, cfg.strong_normal_reverse_max_price
    elif entry_rule == "mid_misprice":
        min_price, max_price = cfg.mid_entry_min_price, cfg.mid_entry_max_price
    elif entry_rule == "strong_delta":
        min_price = cfg.strong_delta_entry_min_price
        max_price = cfg.strong_delta_entry_max_price
        return min_price, max_price
    elif entry_rule == "late_edge":
        return cfg.late_edge_entry_min_price, cfg.late_edge_entry_max_price
    elif entry_rule == "stable_delta":
        return cfg.stable_delta_entry_min_price, cfg.stable_delta_entry_max_price
    elif entry_rule == "early_strong_delta":
        min_price = cfg.early_strong_delta_entry_min_price
        max_price = cfg.early_strong_delta_entry_max_price
        return min_price, max_price
    else:
        min_price, max_price = cfg.min_entry_price, cfg.max_entry_price
        if side == "UP":
            if cfg.up_min_entry_price > 0:
                min_price = cfg.up_min_entry_price
            if cfg.up_max_entry_price > 0:
                max_price = cfg.up_max_entry_price
            return min_price, max_price
    if side == "UP" and cfg.up_min_entry_price > 0:
        min_price = max(min_price, cfg.up_min_entry_price)
    if side == "UP" and cfg.up_max_entry_price > 0:
        max_price = min(max_price, cfg.up_max_entry_price)
    return min_price, max_price


def required_net_edge(cfg: Config, ask: float, entry_rule: str) -> float:
    if (
        entry_rule == "edge"
        and cfg.high_price_edge_threshold > 0
        and ask >= cfg.high_price_edge_threshold
    ):
        return cfg.high_price_min_net_edge
    return cfg.min_net_edge


def late_edge_confirm_checks(cfg: Config, t_remaining: Optional[float]) -> int:
    if t_remaining is None:
        return cfg.late_edge_entry_confirm_checks
    if t_remaining <= 30.0:
        return cfg.late_edge_entry_late_confirm_checks
    if t_remaining <= 60.0:
        return cfg.late_edge_entry_mid_confirm_checks
    return cfg.late_edge_entry_confirm_checks


def entry_confirm_checks(
    cfg: Config,
    entry_rule: str,
    t_remaining: Optional[float] = None,
) -> int:
    if entry_rule == "early_strong_delta":
        return cfg.early_strong_delta_entry_confirm_checks
    if entry_rule == "strong_delta":
        return cfg.strong_delta_entry_confirm_checks
    if entry_rule == "late_edge":
        return late_edge_confirm_checks(cfg, t_remaining)
    if entry_rule == "stable_delta":
        return cfg.stable_delta_entry_confirm_checks
    if entry_rule == "mid_misprice":
        return cfg.mid_entry_confirm_checks
    if entry_rule == "tail_price":
        return cfg.tail_entry_confirm_checks
    if entry_rule == "strong_normal_reverse":
        return cfg.strong_normal_reverse_confirm_checks
    return cfg.confirm_checks


def entry_risk_fraction(cfg: Config, entry_rule: str) -> float:
    if entry_rule == "early_strong_delta":
        return cfg.early_strong_delta_entry_risk_fraction
    if entry_rule == "strong_delta":
        return cfg.strong_delta_entry_risk_fraction
    if entry_rule == "late_edge":
        return cfg.late_edge_entry_risk_fraction
    if entry_rule == "stable_delta":
        return cfg.stable_delta_entry_risk_fraction
    if entry_rule == "mid_misprice":
        return cfg.mid_entry_risk_fraction
    if entry_rule == "tail_price":
        return cfg.tail_entry_risk_fraction
    if entry_rule == "strong_normal_reverse":
        return cfg.strong_normal_reverse_risk_fraction
    return cfg.order_risk_fraction


def btc_signal_allows_entry(
    cfg: Config,
    btc_signal: BtcSignal,
    side: Optional[str],
    entry_rule: str,
    ask: Optional[float] = None,
) -> bool:
    if entry_rule == "tail_price":
        return True
    if entry_rule == "strong_normal_reverse":
        return True
    if entry_rule == "mid_misprice":
        if side == "UP":
            return btc_signal.delta_usd > cfg.mid_btc_up_min_delta_usd
        if side == "DOWN":
            return btc_signal.delta_usd < cfg.mid_btc_down_max_delta_usd
        return False
    if entry_rule == "strong_delta":
        if side == "UP":
            return btc_signal.delta_usd >= cfg.strong_delta_entry_up_min_delta_usd
        if side == "DOWN":
            return btc_signal.delta_usd <= cfg.strong_delta_entry_down_max_delta_usd
        return False
    if entry_rule == "early_strong_delta" and cfg.early_strong_delta_entry_hedge_enabled:
        return True
    if entry_rule == "stable_delta":
        abs_delta = abs(btc_signal.delta_usd)
        if not (
            cfg.stable_delta_entry_min_abs_delta_usd
            <= abs_delta
            <= cfg.stable_delta_entry_max_abs_delta_usd
        ):
            return False
        if side == "UP":
            return btc_signal.delta_usd > 0
        if side == "DOWN":
            return btc_signal.delta_usd < 0
        return False
    if entry_rule in ("edge", "late_edge"):
        if entry_rule == "late_edge":
            if not cfg.late_edge_entry_delta_filter_enabled:
                return True
            up_min = cfg.late_edge_entry_up_min_delta_usd
            down_max = cfg.late_edge_entry_down_max_delta_usd
        else:
            up_min = cfg.btc_up_min_delta_usd
            down_max = cfg.btc_down_max_delta_usd
        if (
            entry_rule == "edge"
            and
            ask is not None
            and cfg.high_price_edge_threshold > 0
            and ask >= cfg.high_price_edge_threshold
            and cfg.high_price_btc_delta_usd > 0
        ):
            up_min = cfg.high_price_btc_delta_usd
            down_max = -cfg.high_price_btc_delta_usd
        if side == "UP":
            return btc_signal.delta_usd >= up_min
        if side == "DOWN":
            return btc_signal.delta_usd <= down_max
        return False
    if entry_rule == "early_strong_delta":
        if side == "UP":
            return btc_signal.delta_usd >= cfg.early_strong_delta_entry_up_min_delta_usd
        if side == "DOWN":
            return btc_signal.delta_usd <= cfg.early_strong_delta_entry_down_max_delta_usd
        return False
    return btc_signal.allows(side)


def btc_signal_entry_description(cfg: Config, entry_rule: str) -> str:
    if entry_rule == "tail_price":
        return "tail BTC filter off"
    if entry_rule == "strong_normal_reverse":
        return "strong->normal reverse uses price guard only"
    if entry_rule == "mid_misprice":
        return (
            f"mid BTC filter UP>{cfg.mid_btc_up_min_delta_usd:.2f} "
            f"DOWN<{cfg.mid_btc_down_max_delta_usd:.2f}"
        )
    if entry_rule == "strong_delta":
        return (
            f"strong BTC filter UP>={cfg.strong_delta_entry_up_min_delta_usd:.2f} "
            f"DOWN<={cfg.strong_delta_entry_down_max_delta_usd:.2f}"
        )
    if entry_rule == "late_edge":
        confirm_label = (
            (
                f"{cfg.late_edge_entry_window_sec:.0f}-30s:"
                f"{cfg.late_edge_entry_mid_confirm_checks}x "
                f"30-{cfg.late_edge_entry_min_t_remaining_sec:.0f}s:"
                f"{cfg.late_edge_entry_late_confirm_checks}x"
            )
            if cfg.late_edge_entry_window_sec <= 60
            else (
                f"{cfg.late_edge_entry_window_sec:.0f}-60s:"
                f"{cfg.late_edge_entry_confirm_checks}x "
                f"60-30s:{cfg.late_edge_entry_mid_confirm_checks}x "
                f"30-{cfg.late_edge_entry_min_t_remaining_sec:.0f}s:"
                f"{cfg.late_edge_entry_late_confirm_checks}x"
            )
        )
        if not cfg.late_edge_entry_delta_filter_enabled:
            return (
                f"late edge price-only {cfg.late_edge_entry_min_price:.2f}-"
                f"{cfg.late_edge_entry_max_price:.2f} "
                f"{confirm_label} "
                f"{cfg.late_edge_entry_risk_fraction * 100:.1f}%"
            )
        return (
            f"late edge BTC filter UP>={cfg.late_edge_entry_up_min_delta_usd:.2f} "
            f"DOWN<={cfg.late_edge_entry_down_max_delta_usd:.2f} "
            f"{confirm_label}"
        )
    if entry_rule == "stable_delta":
        return (
            f"stable delta abs={cfg.stable_delta_entry_min_abs_delta_usd:.2f}-"
            f"{cfg.stable_delta_entry_max_abs_delta_usd:.2f} "
            f"move<{cfg.stable_delta_entry_max_delta_move_usd:.2f}/"
            f"{cfg.stable_delta_entry_confirm_checks}x"
        )
    if entry_rule == "early_strong_delta":
        if cfg.early_strong_delta_entry_hedge_enabled:
            return (
                f"early price-only >{cfg.early_strong_delta_entry_min_price:.2f}-"
                f"<{cfg.early_strong_delta_entry_max_price:.2f} "
                "always-hedge"
            )
        return (
            f"early strong BTC filter UP>={cfg.early_strong_delta_entry_up_min_delta_usd:.2f} "
            f"DOWN<={cfg.early_strong_delta_entry_down_max_delta_usd:.2f}"
        )
    return (
        "normal BTC filter"
        + (
            f"; high_price>={cfg.high_price_edge_threshold:.2f} "
            f"requires abs_delta>{cfg.high_price_btc_delta_usd:.2f}"
            if cfg.high_price_edge_threshold > 0 and cfg.high_price_btc_delta_usd > 0
            else ""
        )
    )


def btc_signal_context_description(btc_signal: BtcSignal, entry_rule: str) -> str:
    if entry_rule == "edge":
        return btc_signal.describe()
    return (
        f"btc_delta={btc_signal.delta_usd:+.2f} "
        f"price={btc_signal.current_price:.2f} beat={btc_signal.price_to_beat:.2f} "
        f"signal={btc_signal.signal_side} source={btc_signal.source}"
    )


def _is_chainlink_twap_market(market: LiveMarket) -> bool:
    source = (market.resolution_source or "").lower()
    return "data.chain.link" in source and "twap" in source


def _is_trusted_twap_signal(btc_signal: BtcSignal) -> bool:
    source = (btc_signal.source or "").lower()
    return "chainlink" in source or "polymarket-rtds" in source or "rtds" in source


def price_source_guard_reason(
    cfg: Config,
    market: LiveMarket,
    btc_signal: Optional[BtcSignal],
) -> Optional[str]:
    if not cfg.price_source_guard_enabled:
        return None
    if cfg.allow_binance_proxy_chainlink_entries:
        return None
    if not _is_chainlink_twap_market(market):
        return None
    if btc_signal is None:
        return (
            "Chainlink TWAP market guarded: official TWAP signal unavailable; "
            f"resolution={market.resolution_source}"
        )
    if _is_trusted_twap_signal(btc_signal):
        return None
    return (
        f"{btc_signal.symbol} Chainlink TWAP market guarded: "
        "Binance proxy PX/BEAT is display-only and not allowed for LIVE delta entry; "
        f"signal_source={btc_signal.source} resolution={market.resolution_source}"
    )


def _candidate_for(
    cfg: Config,
    side: str,
    token_id: str,
    book: TopOfBook,
    *,
    entry_rule: str = "edge",
) -> Optional[_Candidate]:
    ask = book.best_ask
    if ask is None:
        return None
    min_price, max_price = entry_price_bounds(cfg, entry_rule, side)
    if entry_rule == "early_strong_delta":
        if not (ask > min_price and ask < max_price):
            return None
    elif entry_rule in ("strong_delta", "tail_price"):
        if not (ask > min_price and ask <= max_price):
            return None
    elif not (min_price <= ask <= max_price):
        return None
    min_notional = cfg.effective_min_order_notional_usd
    min_size = min_notional / ask
    if book.ask_size < min_size:
        return None

    fee = taker_fee_per_share(cfg, ask)
    net_edge = 1.0 - ask - fee
    min_edge = required_net_edge(cfg, ask, entry_rule)
    if entry_rule in ("edge", "late_edge", "stable_delta", "strong_delta", "early_strong_delta") and net_edge <= min_edge:
        return None
    return _Candidate(
        side=side,
        token_id=token_id,
        ask=ask,
        ask_size=book.ask_size,
        fee=fee,
        net_edge=net_edge,
        entry_rule=entry_rule,
    )


def _stagnation_reason(cfg: Config, state: StrategyState) -> Optional[str]:
    if cfg.stagnation_window_sec <= 0 or len(state.snapshots) < 2:
        return None
    first = state.snapshots[0]
    last = state.snapshots[-1]
    if last.ts - first.ts < cfg.stagnation_window_sec:
        return None
    first_levels = (first.up_bid, first.up_ask, first.down_bid, first.down_ask)
    if all((s.up_bid, s.up_ask, s.down_bid, s.down_ask) == first_levels for s in state.snapshots):
        return f"book top unchanged for {last.ts - first.ts:.1f}s"
    return None


def _volatility_reason(cfg: Config, state: StrategyState, tick_size: float) -> Optional[str]:
    if cfg.volatility_window_sec <= 0 or cfg.max_top_move_ticks <= 0 or len(state.snapshots) < 2:
        return None
    cutoff = state.snapshots[-1].ts - cfg.volatility_window_sec
    recent = [s for s in state.snapshots if s.ts >= cutoff]
    if len(recent) < 2:
        return None

    max_move = 0.0
    for attr in ("up_ask", "down_ask"):
        vals = [getattr(s, attr) for s in recent if getattr(s, attr) is not None]
        if len(vals) >= 2:
            max_move = max(max_move, max(vals) - min(vals))

    max_allowed = cfg.max_top_move_ticks * tick_size
    if max_move > max_allowed:
        return f"top ask moved {max_move:.4f} > volatility cap {max_allowed:.4f}"
    return None


def decide(
    cfg: Config,
    market: LiveMarket,
    book_up: TopOfBook,
    book_down: TopOfBook,
    t_remaining: float,
    state: Optional[StrategyState] = None,
    now: Optional[float] = None,
    order_size: Optional[float] = None,
    retry_side: Optional[str] = None,
    only_side: Optional[str] = None,
    btc_signal: Optional[BtcSignal] = None,
    btc_signal_error: Optional[str] = None,
) -> Decision:
    upper_sec = buy_window_upper_sec(cfg)
    if t_remaining > upper_sec:
        return Decision(action="SKIP_TIME", reason=f"t_remaining={t_remaining:.1f}s > {upper_sec:.0f}s buy window")
    if t_remaining <= 0:
        return Decision(action="SKIP_TIME", reason="window closed")

    tail_entry = tail_entry_active(cfg, t_remaining)
    normal_min_t_remaining = (
        cfg.retry_min_t_remaining_sec if retry_side else cfg.min_t_remaining_sec
    )

    early_entry = early_entry_active(cfg, t_remaining)
    entry_rules: list[str] = []
    if tail_entry:
        entry_rules = ["tail_price"]
    elif early_entry:
        entry_rules = ["early_price"]
    else:
        if early_strong_delta_entry_active(cfg, t_remaining):
            entry_rules.append("early_strong_delta")
        if strong_delta_entry_active(cfg, t_remaining):
            entry_rules.append("strong_delta")
        if late_edge_entry_active(cfg, t_remaining):
            entry_rules.append("late_edge")
        if stable_delta_entry_active(cfg, t_remaining):
            entry_rules.append("stable_delta")
        if (
            t_remaining <= cfg.seconds_before_close
            and t_remaining >= normal_min_t_remaining
        ):
            entry_rules.append("edge")
        if mid_entry_active(cfg, t_remaining):
            entry_rules.append("mid_misprice")
    if not entry_rules:
        return Decision(
            action="SKIP_TIME",
            reason=(
                f"t_remaining={t_remaining:.1f}s outside active buy rules "
                f"(normal <= {cfg.seconds_before_close}s"
                + (
                    f", strong {cfg.strong_delta_entry_window_sec:.0f}-"
                    f"{cfg.strong_delta_entry_min_t_remaining_sec:.0f}s"
                    if cfg.strong_delta_entry_enabled
                    else ""
                )
                + (
                    f", late {cfg.late_edge_entry_window_sec:.0f}-"
                    f"{cfg.late_edge_entry_min_t_remaining_sec:.0f}s"
                    if cfg.late_edge_entry_enabled
                    else ""
                )
                + (
                    f", stable delta {cfg.stable_delta_entry_window_sec:.0f}-"
                    f"{cfg.stable_delta_entry_min_t_remaining_sec:.0f}s"
                    if cfg.stable_delta_entry_enabled
                    else ""
                )
                + (
                    f", early strong {cfg.early_strong_delta_entry_window_sec:.0f}-"
                    f"{cfg.early_strong_delta_entry_min_t_remaining_sec:.0f}s"
                    if cfg.early_strong_delta_entry_enabled
                    else ""
                )
                + ")"
            ),
        )
    base_entry_rule = entry_rules[0]

    if state is not None and base_entry_rule != "tail_price" and retry_side is None:
        state.reset_for_market(market.condition_id)
        keep_sec = max(cfg.stagnation_window_sec, cfg.volatility_window_sec, 1.0)
        state.add_snapshot(now or 0.0, book_up, book_down, keep_sec)
        reason = _stagnation_reason(cfg, state)
        if reason:
            return Decision(action="SKIP_STAGNANT", reason=reason)
        reason = _volatility_reason(cfg, state, market.tick_size)
        if reason:
            return Decision(action="SKIP_VOLATILE", reason=reason)

    candidates = []
    for entry_rule in entry_rules:
        candidates.extend(
            c
            for c in (
                _candidate_for(cfg, "UP", market.up_token, book_up, entry_rule=entry_rule),
                _candidate_for(cfg, "DOWN", market.down_token, book_down, entry_rule=entry_rule),
            )
            if c is not None
            and (retry_side is None or c.side == retry_side)
            and (only_side is None or c.side == only_side)
        )
    guarded_candidates = [c for c in candidates if c.entry_rule != "tail_price"]
    if guarded_candidates and (
        cfg.btc_delta_filter_enabled
        or any(c.entry_rule == "stable_delta" for c in guarded_candidates)
    ):
        guard_reason = price_source_guard_reason(cfg, market, btc_signal)
        if guard_reason:
            c = guarded_candidates[0]
            return Decision(
                action="SKIP_PRICE_SOURCE",
                side=c.side,
                token_id=c.token_id,
                price=c.ask,
                size=order_size,
                fee=c.fee,
                net_edge=c.net_edge,
                reason=f"{c.side} {c.entry_rule} blocked: {guard_reason}",
                entry_rule=c.entry_rule,
                risk_fraction=entry_risk_fraction(cfg, c.entry_rule),
            )
    btc_blocked_candidates: list[_Candidate] = []
    needs_signal_filter = cfg.btc_delta_filter_enabled or any(
        c.entry_rule == "stable_delta" for c in candidates
    )
    if needs_signal_filter and btc_signal is not None:
        btc_allowed_candidates = []
        for c in candidates:
            if c.entry_rule == "tail_price" or btc_signal_allows_entry(
                cfg, btc_signal, c.side, c.entry_rule, c.ask
            ):
                btc_allowed_candidates.append(c)
            else:
                btc_blocked_candidates.append(c)
        candidates = btc_allowed_candidates
    if candidates:
        preferred_by_side: dict[str, _Candidate] = {}
        for c in candidates:
            preferred_by_side.setdefault(c.side, c)
        candidates = list(preferred_by_side.values())

    if not candidates:
        sides = (("UP", book_up), ("DOWN", book_down))
        if retry_side == "UP":
            sides = (("UP", book_up),)
        elif retry_side == "DOWN":
            sides = (("DOWN", book_down),)
        elif only_side == "UP":
            sides = (("UP", book_up),)
        elif only_side == "DOWN":
            sides = (("DOWN", book_down),)
        for side, book in sides:
            if book.best_ask is None:
                continue
            reasons = []
            for entry_rule in entry_rules:
                min_price, max_price = entry_price_bounds(cfg, entry_rule, side)
                if entry_rule == "early_strong_delta":
                    in_zone = min_price < book.best_ask < max_price
                elif entry_rule in ("strong_delta", "tail_price"):
                    in_zone = min_price < book.best_ask <= max_price
                else:
                    in_zone = min_price <= book.best_ask <= max_price
                if in_zone:
                    break
                reasons.append(f"{entry_rule}={min_price}-{max_price}")
            else:
                entry_rule = base_entry_rule
                min_price, max_price = entry_price_bounds(cfg, entry_rule, side)
            if book.best_ask > max_price:
                return Decision(
                    action="SKIP_PRICE",
                    side=side,
                    price=book.best_ask,
                    reason=f"{side} ask={book.best_ask} outside buy zones ({'; '.join(reasons)})",
                    entry_rule=entry_rule,
                )
            if entry_rule in ("early_price", "tail_price", "mid_misprice"):
                if entry_rule == "tail_price" and book.best_ask <= min_price:
                    continue
                if entry_rule != "tail_price" and book.best_ask < min_price:
                    continue
                min_notional = cfg.effective_min_order_notional_usd
                min_size = min_notional / book.best_ask
                if book.ask_size < min_size:
                    return Decision(
                        action="SKIP_SIZE",
                        side=side,
                        price=book.best_ask,
                        size=book.ask_size,
                        reason=f"{side} ask_size={book.ask_size} < min ${min_notional:.2f} ({min_size:.4f} sh)",
                    )
                continue
            if book.best_ask < min_price:
                continue
            min_notional = cfg.effective_min_order_notional_usd
            min_size = min_notional / book.best_ask
            if book.ask_size < min_size:
                return Decision(
                    action="SKIP_SIZE",
                    side=side,
                    price=book.best_ask,
                    size=book.ask_size,
                    reason=f"{side} ask_size={book.ask_size} < min ${min_notional:.2f} ({min_size:.4f} sh)",
                )
            fee = taker_fee_per_share(cfg, book.best_ask)
            net_edge = 1.0 - book.best_ask - fee
            min_edge = required_net_edge(cfg, book.best_ask, entry_rule)
            if net_edge <= min_edge:
                return Decision(
                    action="SKIP_EDGE",
                    side=side,
                    price=book.best_ask,
                    fee=fee,
                    net_edge=net_edge,
                    reason=f"{side} net_edge={net_edge:.4f} <= {min_edge:.4f}",
                )
        if btc_blocked_candidates:
            c = btc_blocked_candidates[0]
            return Decision(
                action="SKIP_BTC_SIGNAL",
                side=c.side,
                token_id=c.token_id,
                price=c.ask,
                size=order_size,
                fee=c.fee,
                net_edge=c.net_edge,
                reason=(
                    f"{c.side} blocked by price signal filter; "
                    f"{btc_signal_context_description(btc_signal, c.entry_rule)} "
                    f"{btc_signal_entry_description(cfg, c.entry_rule)}"
                ),
                entry_rule=c.entry_rule,
                risk_fraction=entry_risk_fraction(cfg, c.entry_rule),
            )
        if entry_rule in ("early_price", "tail_price"):
            return Decision(
                action="SKIP_PRICE",
                reason=f"no {base_entry_rule} side ask > {entry_price_bounds(cfg, base_entry_rule)[0]}",
                entry_rule=base_entry_rule,
            )
        return Decision(action="SKIP_PRICE", reason="no qualifying side")

    if len(candidates) == 2:
        if early_strong_delta_hedge_active(cfg, t_remaining):
            candidates = [
                min(candidates, key=lambda item: (item.ask, 0 if item.side == "UP" else 1))
            ]
        else:
            return Decision(
                action="SKIP_AMBIGUOUS",
                reason=f"both sides in buy zone: UP={book_up.best_ask}, DOWN={book_down.best_ask}",
            )

    c = candidates[0]
    if (cfg.btc_delta_filter_enabled or c.entry_rule == "stable_delta") and c.entry_rule != "tail_price":
        if btc_signal is None:
            return Decision(
                action="SKIP_BTC_SIGNAL",
                side=c.side,
                token_id=c.token_id,
                price=c.ask,
                size=order_size,
                fee=c.fee,
                net_edge=c.net_edge,
                reason=(
                    "BTC delta signal unavailable"
                    + (f": {btc_signal_error}" if btc_signal_error else "")
                ),
                entry_rule=c.entry_rule,
            )
        if not btc_signal_allows_entry(cfg, btc_signal, c.side, c.entry_rule, c.ask):
            return Decision(
                action="SKIP_BTC_SIGNAL",
                side=c.side,
                token_id=c.token_id,
                price=c.ask,
                size=order_size,
                fee=c.fee,
                net_edge=c.net_edge,
                reason=(
                    f"{c.side} blocked by price signal filter; "
                    f"{btc_signal.describe()} {btc_signal_entry_description(cfg, c.entry_rule)}"
                ),
                entry_rule=c.entry_rule,
                risk_fraction=entry_risk_fraction(cfg, c.entry_rule),
            )
    if state is not None and retry_side is None:
        momentum_reason = state.entry_momentum_reset_reason(cfg, market, c)
        if momentum_reason:
            required_confirmations = entry_confirm_checks(cfg, c.entry_rule, t_remaining)
            momentum_limit = "no-retreat"
            if cfg.entry_momentum_max_ask_move > 0:
                momentum_limit = (
                    f"no-retreat max_move<{cfg.entry_momentum_max_ask_move:.3f}"
                )
            return Decision(
                action="SKIP_PRICE_MOMENTUM",
                side=c.side,
                token_id=c.token_id,
                price=c.ask,
                size=order_size,
                fee=c.fee,
                net_edge=c.net_edge,
                reason=(
                    f"{momentum_reason}; "
                    f"requires {required_confirmations}x "
                    f"within {cfg.entry_momentum_min_price:.3f}-"
                    f"{cfg.entry_momentum_max_price:.3f} "
                    f"{momentum_limit}"
                ),
                entry_rule=c.entry_rule,
                risk_fraction=entry_risk_fraction(cfg, c.entry_rule),
            )
        if c.entry_rule == "stable_delta" and btc_signal is not None:
            confirmations, delta_move = state.note_stable_delta_candidate(
                market,
                c,
                abs(btc_signal.delta_usd),
                cfg.stable_delta_entry_max_delta_move_usd,
            )
            required_confirmations = entry_confirm_checks(cfg, c.entry_rule, t_remaining)
            if delta_move is not None:
                return Decision(
                    action="SKIP_DELTA_JUMP",
                    side=c.side,
                    token_id=c.token_id,
                    price=c.ask,
                    size=order_size,
                    fee=c.fee,
                    net_edge=c.net_edge,
                    reason=(
                        f"{c.side} stable_delta reset; "
                        f"abs_delta moved {delta_move:.2f} >= "
                        f"{cfg.stable_delta_entry_max_delta_move_usd:.2f}; "
                        f"btc_delta={btc_signal.delta_usd:+.2f} "
                        f"confirmation {confirmations}/{required_confirmations}"
                    ),
                    entry_rule=c.entry_rule,
                    risk_fraction=entry_risk_fraction(cfg, c.entry_rule),
                )
            if confirmations < required_confirmations:
                return Decision(
                    action="SKIP_CONFIRM",
                    side=c.side,
                    token_id=c.token_id,
                    price=c.ask,
                    size=order_size,
                    fee=c.fee,
                    net_edge=c.net_edge,
                    reason=(
                        f"{c.side} stable_delta confirmation {confirmations}/{required_confirmations} "
                        f"ask={c.ask} net_edge={c.net_edge:.4f} "
                        f"btc_delta={btc_signal.delta_usd:+.2f} "
                        f"abs_range={cfg.stable_delta_entry_min_abs_delta_usd:.2f}-"
                        f"{cfg.stable_delta_entry_max_abs_delta_usd:.2f} "
                        f"move<{cfg.stable_delta_entry_max_delta_move_usd:.2f}"
                    ),
                    entry_rule=c.entry_rule,
                    risk_fraction=entry_risk_fraction(cfg, c.entry_rule),
                )
        else:
            confirmations = state.note_candidate(market, c)
            required_confirmations = entry_confirm_checks(cfg, c.entry_rule, t_remaining)
            if confirmations < required_confirmations:
                return Decision(
                    action="SKIP_CONFIRM",
                    side=c.side,
                    token_id=c.token_id,
                    price=c.ask,
                    size=order_size,
                    fee=c.fee,
                    net_edge=c.net_edge,
                    reason=(
                        f"{c.side} {c.entry_rule} confirmation {confirmations}/{required_confirmations} "
                        f"ask={c.ask} net_edge={c.net_edge:.4f}"
                    ),
                    entry_rule=c.entry_rule,
                    risk_fraction=entry_risk_fraction(cfg, c.entry_rule),
                )
            momentum_reason = state.entry_momentum_confirmation_reason(
                cfg,
                market,
                c,
                confirmations,
                required_confirmations,
            )
            if momentum_reason:
                return Decision(
                    action="SKIP_PRICE_MOMENTUM",
                    side=c.side,
                    token_id=c.token_id,
                    price=c.ask,
                    size=order_size,
                    fee=c.fee,
                    net_edge=c.net_edge,
                    reason=(
                        f"{momentum_reason}; "
                        f"confirmation {confirmations}/{required_confirmations}"
                    ),
                    entry_rule=c.entry_rule,
                    risk_fraction=entry_risk_fraction(cfg, c.entry_rule),
                )

    size = order_size or (cfg.effective_min_order_notional_usd / c.ask)
    return Decision(
        action="BUY",
        side=c.side,
        token_id=c.token_id,
        price=c.ask,
        size=size,
        fee=c.fee,
        net_edge=c.net_edge,
        entry_rule=c.entry_rule,
        risk_fraction=entry_risk_fraction(cfg, c.entry_rule),
        reason=(
            f"{c.side} {c.entry_rule} ask={c.ask} fee={c.fee:.4f} net_edge={c.net_edge:.4f} "
            f"book_size={c.ask_size} order_size={size} t_rem={t_remaining:.1f}s"
        ),
    )
