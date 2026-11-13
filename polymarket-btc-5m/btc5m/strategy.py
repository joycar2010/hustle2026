"""Late-window fee-aware edge strategy for BTC 5m Up/Down."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from btc5m.book import TopOfBook
from btc5m.config import Config
from btc5m.markets import LiveMarket
from btc5m.signal import BtcSignal


@dataclass(frozen=True)
class Decision:
    action: str  # BUY | SKIP | HOLD
    side: Optional[str] = None
    token_id: Optional[str] = None
    price: Optional[float] = None
    size: Optional[float] = None
    fee: Optional[float] = None
    net_edge: Optional[float] = None
    reason: str = ""


@dataclass
class StrategyState:
    market_id: Optional[str] = None
    confirm_key: Optional[tuple[str, str]] = None
    confirm_count: int = 0
    entered_markets: set[str] | None = None

    def __post_init__(self) -> None:
        if self.entered_markets is None:
            self.entered_markets = set()

    def reset_for_market(self, condition_id: str) -> None:
        if self.market_id == condition_id:
            return
        self.market_id = condition_id
        self.confirm_key = None
        self.confirm_count = 0

    def note(self, side: str, price: float) -> int:
        key = (side, f"{price:.2f}")
        if key == self.confirm_key:
            self.confirm_count += 1
        else:
            self.confirm_key = key
            self.confirm_count = 1
        return self.confirm_count


def taker_fee_per_share(fee_rate: float, ask: float) -> float:
    """Polymarket crypto_fees_v2: fee = rate * price * (1 - price)."""
    return fee_rate * ask * (1.0 - ask)


def net_edge(ask: float, fee_rate: float) -> float:
    return 1.0 - ask - taker_fee_per_share(fee_rate, ask)


def decide(
    cfg: Config,
    market: LiveMarket,
    up_book: TopOfBook,
    down_book: TopOfBook,
    signal: Optional[BtcSignal],
    state: StrategyState,
    *,
    already_in_market: bool,
) -> Decision:
    state.reset_for_market(market.condition_id)
    t_left = market.t_remaining()

    if already_in_market or market.condition_id in (state.entered_markets or set()):
        return Decision(action="HOLD", reason="already entered this window")

    if t_left > cfg.entry_window_sec:
        return Decision(
            action="SKIP",
            reason=f"waiting for entry window t_left={t_left:.1f}s > {cfg.entry_window_sec:.0f}s",
        )
    if t_left < cfg.min_t_remaining_sec:
        return Decision(
            action="SKIP",
            reason=f"too close to close t_left={t_left:.1f}s < {cfg.min_t_remaining_sec:.0f}s",
        )

    candidates: list[tuple[str, str, float, float, float]] = []
    for side, token, book in (
        ("UP", market.up_token, up_book),
        ("DOWN", market.down_token, down_book),
    ):
        ask = book.best_ask
        if ask is None or book.ask_size < cfg.order_shares:
            continue
        if ask < cfg.min_entry_price or ask > cfg.max_entry_price:
            continue
        fee = taker_fee_per_share(cfg.taker_fee_rate, ask)
        edge = 1.0 - ask - fee
        if edge < cfg.min_net_edge:
            continue
        candidates.append((side, token, ask, fee, edge))

    if not candidates:
        return Decision(
            action="SKIP",
            reason=(
                f"no edge candidate up_ask={up_book.best_ask} "
                f"dn_ask={down_book.best_ask} t_left={t_left:.1f}s"
            ),
        )

    # Prefer higher net edge; ties break toward BTC signal side.
    candidates.sort(key=lambda c: c[4], reverse=True)
    if signal and signal.signal_side in {"UP", "DOWN"}:
        aligned = [c for c in candidates if c[0] == signal.signal_side]
        if aligned:
            candidates = aligned + [c for c in candidates if c[0] != signal.signal_side]

    side, token, ask, fee, edge = candidates[0]

    if cfg.delta_filter_enabled:
        if signal is None:
            return Decision(action="SKIP", reason="btc signal unavailable")
        if not signal.allows(
            side,
            up_min=cfg.up_min_delta_usd,
            down_max=cfg.down_max_delta_usd,
        ):
            return Decision(
                action="SKIP",
                side=side,
                reason=f"delta filter blocked {side}: {signal.describe()}",
            )

    confirms = state.note(side, ask)
    if confirms < cfg.confirm_checks:
        return Decision(
            action="SKIP",
            side=side,
            price=ask,
            fee=fee,
            net_edge=edge,
            reason=f"confirm {confirms}/{cfg.confirm_checks} {side}@{ask:.2f} edge={edge:.4f}",
        )

    size = float(cfg.order_shares)
    notional = size * ask
    if notional > cfg.max_order_usd:
        size = max(cfg.max_order_usd / ask, market.min_size)
        size = float(int(size))  # whole shares
        if size < market.min_size:
            return Decision(action="SKIP", reason="size below exchange minimum after USD cap")

    return Decision(
        action="BUY",
        side=side,
        token_id=token,
        price=ask,
        size=size,
        fee=fee,
        net_edge=edge,
        reason=(
            f"BUY {side}@{ask:.2f} size={size:.0f} edge={edge:.4f} "
            f"fee={fee:.4f} t_left={t_left:.1f}s"
            + (f" | {signal.describe()}" if signal else "")
        ),
    )
