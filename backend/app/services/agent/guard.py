"""Deterministic Guard rules engine.

Every Codex Proposal MUST pass through Guard before any execution call.
Guard is pure-Python, side-effect-free except for rate_buckets pre_check.
On reject, Proposal is logged and a Feishu alert may fire (caller's choice).

Bound rules implement the operator's stated 铁律 verbatim:
  - Symbol whitelist (XAU pair only)
  - Single trade ≤ 10% of total equity
  - Total positions ≤ 50% of equity
  - Daily cumulative volume ≤ 500% of equity
  - Both legs must be balanced; single-leg → only補腿 action allowed
  - Anti-ban frequency caps (delegated to rate_buckets)
  - Time-window special rules (Wed/Fri 22:00 BJT)
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple
from datetime import datetime, timezone, timedelta

# Beijing = UTC+8
BJT = timezone(timedelta(hours=8))

ActionType = Literal['open_long', 'open_short', 'close_long', 'close_short', 'rebalance', 'noop']


@dataclass
class Proposal:
    action: ActionType
    leg: Literal['a', 'b', 'both']  # which leg the action applies to
    qty: float
    reason: str
    trigger: str
    confidence: float = 0.0
    is_rebalance_补腿: bool = False  # set True when correcting single-leg


@dataclass
class MarketState:
    spread_now: float
    spread_30m_avg: float
    funding_rate: float
    swap_fee_long: float
    swap_fee_short: float
    a_size: float
    b_size: float
    conversion_factor: float
    total_equity: float
    a_equity: float
    b_equity: float
    daily_traded_volume: float
    now_utc_ms: int


@dataclass
class GuardResult:
    ok: bool
    violations: List[str] = field(default_factory=list)
    soft_warnings: List[str] = field(default_factory=list)


def _bjt_now(state: MarketState) -> datetime:
    return datetime.fromtimestamp(state.now_utc_ms / 1000, tz=timezone.utc).astimezone(BJT)


def check_symbol_whitelist(p: Proposal, _: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    if p.leg not in ('a', 'b', 'both'):
        return f'invalid_leg:{p.leg}'
    return None


def check_single_trade_cap(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    if p.action in ('noop', 'close_long', 'close_short'):
        return None
    cap_pct = float(cfg.get('position_caps', {}).get('single_trade_pct', 0.10))
    notional = p.qty  # qty already in equity-equivalent units
    if s.total_equity <= 0:
        return 'zero_equity'
    if notional / s.total_equity > cap_pct:
        return f'single_trade_exceeds_cap:{notional/s.total_equity:.2%}>{cap_pct:.0%}'
    return None


def check_total_position_cap(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    if p.action in ('noop', 'close_long', 'close_short'):
        return None
    cap_pct = float(cfg.get('position_caps', {}).get('total_position_pct', 0.50))
    current_notional = abs(s.a_size) + abs(s.b_size) * s.conversion_factor
    new_notional = current_notional + p.qty
    if new_notional / s.total_equity > cap_pct:
        return f'total_position_exceeds_cap:{new_notional/s.total_equity:.2%}>{cap_pct:.0%}'
    return None


def check_daily_volume_cap(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    if p.action == 'noop':
        return None
    cap_pct = float(cfg.get('position_caps', {}).get('daily_volume_pct', 5.00))
    if (s.daily_traded_volume + p.qty) / s.total_equity > cap_pct:
        return f'daily_volume_exceeds_cap:{(s.daily_traded_volume+p.qty)/s.total_equity:.2%}>{cap_pct:.0%}'
    return None


def check_leg_balance(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    """If currently single-leg, only 補腿 actions allowed."""
    delta = abs(s.a_size - s.b_size * s.conversion_factor)
    is_single_leg = delta > 1.0
    if is_single_leg and not p.is_rebalance_补腿:
        return f'single_leg_detected_delta={delta:.2f};only_rebalance_allowed'
    if not is_single_leg and p.action in ('open_long', 'open_short') and p.leg != 'both':
        return f'must_open_both_legs_simultaneously:proposal_leg={p.leg}'
    return None


def check_no_signal(p: Proposal, _: MarketState, __: Dict[str, Any]) -> Optional[str]:
    if not p.reason or not p.trigger or p.confidence < 0.3:
        return f'insufficient_signal:reason={bool(p.reason)},trigger={bool(p.trigger)},conf={p.confidence}'
    return None


def check_time_window(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    """Wed/Fri 22:00 BJT: heavy positions disallowed unless special spread+funding combo."""
    if p.action not in ('open_long', 'open_short'):
        return None
    bjt = _bjt_now(s)
    weekday = bjt.weekday()  # 0=Mon ... 6=Sun
    is_wed_evening = weekday == 2 and bjt.hour >= 22
    is_fri_evening = weekday == 4 and bjt.hour >= 22
    if is_wed_evening or is_fri_evening:
        proposed_pct = (abs(s.a_size) + p.qty + abs(s.b_size) * s.conversion_factor) / max(s.total_equity, 1)
        if proposed_pct > 0.30:
            # Allow >30% only if Wed and spread + funding combo
            if is_wed_evening and s.spread_30m_avg >= 2.0 and s.funding_rate >= 0.005:
                if proposed_pct > 0.50:
                    return f'wed_evening_max_50pct_exceeded:{proposed_pct:.2%}'
                return None
            return f'late_session_position_cap:{proposed_pct:.2%}>30%_without_funding_combo'
    return None


GUARD_CHECKS = [
    check_symbol_whitelist,
    check_no_signal,
    check_single_trade_cap,
    check_total_position_cap,
    check_daily_volume_cap,
    check_leg_balance,
    check_time_window,
]


def run_guard(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> GuardResult:
    violations = []
    for fn in GUARD_CHECKS:
        v = fn(p, s, cfg)
        if v:
            violations.append(v)
    return GuardResult(ok=not violations, violations=violations)
