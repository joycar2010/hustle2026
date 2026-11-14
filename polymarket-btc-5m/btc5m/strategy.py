"""Late-window + opening-gap fee-aware edge strategy for BTC 5m Up/Down."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from btc5m.book import TopOfBook
from btc5m.calibration import bucket_ban_reason
from btc5m.config import Config
from btc5m.lead_table import edge_after_fee, hold_win_rate, is_cheap_vs_hold
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
    phase: str = ""  # late | opening_gap


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


def _phase(cfg: Config, market: LiveMarket) -> Optional[str]:
    t_left = market.t_remaining()
    elapsed = market.t_elapsed()
    if cfg.opening_gap_enabled and elapsed <= cfg.opening_gap_window_sec:
        return "opening_gap"
    if t_left <= cfg.entry_window_sec and t_left >= cfg.min_t_remaining_sec:
        return "late"
    return None


def decide(
    cfg: Config,
    market: LiveMarket,
    up_book: TopOfBook,
    down_book: TopOfBook,
    signal: Optional[BtcSignal],
    state: StrategyState,
    *,
    already_in_market: bool,
    db_path: Optional[Path] = None,
) -> Decision:
    state.reset_for_market(market.condition_id)
    t_left = market.t_remaining()
    elapsed = market.t_elapsed()

    if already_in_market or market.condition_id in (state.entered_markets or set()):
        return Decision(action="HOLD", reason="already entered this window")

    phase = _phase(cfg, market)
    if phase is None:
        if t_left > cfg.entry_window_sec and not (
            cfg.opening_gap_enabled and elapsed <= cfg.opening_gap_window_sec
        ):
            return Decision(
                action="SKIP",
                reason=(
                    f"waiting for entry window t_left={t_left:.1f}s "
                    f"elapsed={elapsed:.1f}s"
                ),
            )
        return Decision(
            action="SKIP",
            reason=f"outside trade phases t_left={t_left:.1f}s elapsed={elapsed:.1f}s",
        )

    if signal is None and (cfg.delta_filter_enabled or cfg.lead_table_enabled):
        return Decision(action="SKIP", reason="btc signal unavailable", phase=phase)

    # Opening-gap: require minimum gap in bp
    if phase == "opening_gap":
        if signal is None or abs(signal.opening_gap_bp) < cfg.opening_gap_min_bp:
            gap = signal.opening_gap_bp if signal else 0.0
            return Decision(
                action="SKIP",
                phase=phase,
                reason=(
                    f"opening gap {gap:+.1f}bp < min {cfg.opening_gap_min_bp:.1f}bp"
                ),
            )

    preferred = None
    if signal:
        preferred = signal.decision_side if signal.decision_side in {"UP", "DOWN"} else signal.signal_side

    candidates: list[tuple[str, str, float, float, float, float]] = []
    banned_high = 0
    banned_cal = 0
    rejected_hold = 0
    for side, token, book in (
        ("UP", market.up_token, up_book),
        ("DOWN", market.down_token, down_book),
    ):
        ask = book.best_ask
        if ask is None or book.ask_size < cfg.order_shares:
            continue
        if ask < cfg.min_entry_price or ask > cfg.max_entry_price:
            continue
        if ask >= cfg.late_edge_hard_ban_price - 1e-12:
            banned_high += 1
            continue
        if cfg.bucket_calibration_enabled and db_path is not None:
            ban = bucket_ban_reason(
                ask,
                db_path,
                lookback_sec=cfg.bucket_lookback_sec,
                min_samples=cfg.bucket_min_samples,
                fee_rate=cfg.taker_fee_rate,
                wr_buffer=cfg.bucket_wr_buffer,
            )
            if ban:
                banned_cal += 1
                continue
        fee = taker_fee_per_share(cfg.taker_fee_rate, ask)
        edge = 1.0 - ask - fee
        residual = max(1.0 - ask, 0.0)
        if edge < cfg.min_net_edge:
            continue
        if residual > 0 and (ask + fee) > 1.0 - residual / max(cfg.late_edge_edge_safety, 1.0):
            continue

        # P3: lead-hold table — ask must be cheap vs empirical WR
        hold = signal.hold_wr if signal else 0.5
        if cfg.lead_table_enabled and signal is not None:
            # Recompute for this side's signed lead
            signed = signal.projected_lead_bp if signal.in_final_minute else signal.lead_bp
            if side == "DOWN":
                signed = -signed
            hold = hold_win_rate(elapsed_sec=elapsed, lead_bp=signed).hold_wr
            if not is_cheap_vs_hold(
                ask,
                hold,
                fee_rate=cfg.taker_fee_rate,
                margin=cfg.lead_edge_margin,
            ):
                rejected_hold += 1
                continue
            # Score by probabilistic edge rather than residual-only
            edge = edge_after_fee(
                ask, hold, fee_rate=cfg.taker_fee_rate, margin=cfg.lead_edge_margin
            )

        candidates.append((side, token, ask, fee, edge, hold))

    if not candidates:
        extras = []
        if banned_high:
            extras.append(f"banned_high>={cfg.late_edge_hard_ban_price:.2f}x{banned_high}")
        if banned_cal:
            extras.append(f"bucket_cal_ban x{banned_cal}")
        if rejected_hold:
            extras.append(f"hold_table_reject x{rejected_hold}")
        extra = (" " + " ".join(extras)) if extras else ""
        return Decision(
            action="SKIP",
            phase=phase,
            reason=(
                f"no edge candidate phase={phase} up_ask={up_book.best_ask} "
                f"dn_ask={down_book.best_ask} t_left={t_left:.1f}s{extra}"
            ),
        )

    candidates.sort(key=lambda c: c[4], reverse=True)
    if preferred in {"UP", "DOWN"}:
        aligned = [c for c in candidates if c[0] == preferred]
        if aligned:
            candidates = aligned + [c for c in candidates if c[0] != preferred]

    side, token, ask, fee, edge, hold = candidates[0]

    if cfg.delta_filter_enabled:
        assert signal is not None
        if signal.venue_count < cfg.signal_min_venues:
            return Decision(
                action="SKIP",
                side=side,
                phase=phase,
                reason=(
                    f"signal venues {signal.venue_count} < min {cfg.signal_min_venues}: "
                    f"{signal.describe()}"
                ),
            )
        if not signal.consensus:
            return Decision(
                action="SKIP",
                side=side,
                phase=phase,
                reason=f"signal consensus failed: {signal.describe()}",
            )
        # Align with decision_side (projected in final minute)
        want = signal.decision_side if signal.decision_side in {"UP", "DOWN"} else side
        if want != side:
            return Decision(
                action="SKIP",
                side=side,
                phase=phase,
                reason=f"side {side} != decision_side {want}: {signal.describe()}",
            )
        if not signal.allows(
            side,
            up_min=cfg.up_min_delta_usd,
            down_max=cfg.down_max_delta_usd,
        ):
            # Opening gap may use bp gate instead of USD delta
            if phase == "opening_gap" and abs(signal.opening_gap_bp) >= cfg.opening_gap_min_bp:
                pass
            else:
                return Decision(
                    action="SKIP",
                    side=side,
                    phase=phase,
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
            phase=phase,
            reason=(
                f"confirm {confirms}/{cfg.confirm_checks} {side}@{ask:.2f} "
                f"edge={edge:.4f} hold={hold:.1%} phase={phase}"
            ),
        )

    size = float(cfg.order_shares)
    notional = size * ask
    if notional > cfg.max_order_usd:
        size = max(cfg.max_order_usd / ask, market.min_size)
        size = float(int(size))
        if size < market.min_size:
            return Decision(
                action="SKIP",
                phase=phase,
                reason="size below exchange minimum after USD cap",
            )

    return Decision(
        action="BUY",
        side=side,
        token_id=token,
        price=ask,
        size=size,
        fee=fee,
        net_edge=edge,
        phase=phase,
        reason=(
            f"BUY {side}@{ask:.2f} size={size:.0f} edge={edge:.4f} "
            f"fee={fee:.4f} hold={hold:.1%} phase={phase} t_left={t_left:.1f}s"
            + (f" | {signal.describe()}" if signal else "")
        ),
    )
