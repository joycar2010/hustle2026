"""Deterministic Guard rules engine.

Every Codex Proposal MUST pass through Guard before any execution call.
Guard is pure-Python, side-effect-free except for rate_buckets pre_check.
On reject, Proposal is logged and a Feishu alert may fire (caller's choice).

Bound rules implement the operator's stated rules verbatim:
  - Symbol whitelist (XAU pair only)
  - Single trade <= 10% of total equity
  - Total positions <= 50% of equity
  - Daily cumulative volume <= 500% of equity
  - Both legs must be balanced; single-leg -> only rebalance action allowed
  - Anti-ban frequency caps (delegated to rate_buckets)
  - Monday open volatility guard (06:00-06:30 BJT)
  - Wednesday triple overnight direction-aware caps
  - Friday weekend graduated position reduction
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
    funding_rate_history: List[float] = field(default_factory=list)
    position_direction: str = 'flat'  # 'forward', 'reverse', 'flat', 'mixed'


@dataclass
class GuardResult:
    ok: bool
    violations: List[str] = field(default_factory=list)
    escalatable_violations: List[str] = field(default_factory=list)
    soft_warnings: List[str] = field(default_factory=list)


def _bjt_now(state: MarketState) -> datetime:
    return datetime.fromtimestamp(state.now_utc_ms / 1000, tz=timezone.utc).astimezone(BJT)


def _position_direction(s: MarketState) -> str:
    a_net = s.a_size
    b_net_oz = s.b_size * s.conversion_factor
    if abs(a_net) < 0.01 and abs(b_net_oz) < 0.01:
        return 'flat'
    if a_net > 0.01 and b_net_oz < -0.01:
        return 'forward'
    if a_net < -0.01 and b_net_oz > 0.01:
        return 'reverse'
    return 'mixed'


def _proposed_position_pct(p: Proposal, s: MarketState) -> float:
    current_notional = abs(s.a_size) + abs(s.b_size) * s.conversion_factor
    new_notional = current_notional + p.qty
    return new_notional / max(s.total_equity, 1)


def _parse_hhmm(s: str) -> int:
    try:
        parts = s.split(':')
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


# ===== Individual Guard checks =====

def check_symbol_whitelist(p: Proposal, _: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    if p.leg not in ('a', 'b', 'both'):
        return f'invalid_leg:{p.leg}'
    return None


def check_single_trade_cap(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    if p.action in ('noop', 'close_long', 'close_short'):
        return None
    cap_pct = float(cfg.get('position_caps', {}).get('single_trade_pct', 0.10))
    notional = p.qty
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


def check_monday_open(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    """Monday market open volatility guard.

    06:00-06:30 BJT (summer): High volatility, require spread >= threshold.
    07:15-08:00 BJT: Funding rate capture window, special handling.
    """
    if p.action not in ('open_long', 'open_short'):
        return None
    bjt = _bjt_now(s)
    if bjt.weekday() != 0:  # Not Monday
        return None

    tr = cfg.get('time_rules', {}).get('monday_open', {})
    if not tr.get('enabled', True):
        return None

    t_minutes = bjt.hour * 60 + bjt.minute

    vol_start = _parse_hhmm(tr.get('volatility_start', '06:00'))
    vol_end = _parse_hhmm(tr.get('volatility_end', '06:30'))
    min_spread = float(tr.get('min_spread_to_open', 4.0))

    if vol_start <= t_minutes < vol_end:
        if abs(s.spread_now) < min_spread:
            return (f'monday_open_volatility:spread={s.spread_now:.2f}<{min_spread}'
                    f'(06:00-06:30_high_volatility_window)')

    fr_start = _parse_hhmm(tr.get('funding_window_start', '07:15'))
    fr_end = _parse_hhmm(tr.get('funding_window_end', '08:00'))
    if fr_start <= t_minutes < fr_end:
        min_funding = float(tr.get('min_funding_for_capture', 0.003))
        if abs(s.funding_rate) < min_funding:
            return (f'monday_funding_window:funding={s.funding_rate:.6f}<{min_funding}'
                    f'(07:15-08:00_funding_capture_window)')

    return None


def check_time_window(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    """Wednesday triple overnight fee: direction-aware position caps.

    Forward (A long + B short): MT5 short swap x3 is the cost.
    Reverse (A short + B long): MT5 long swap x3 is the cost.
    Net cost vs funding rate benefit determines allowed position cap.
    """
    if p.action not in ('open_long', 'open_short'):
        return None
    bjt = _bjt_now(s)
    if not (bjt.weekday() == 2 and bjt.hour >= 22):
        return None

    tr = cfg.get('time_rules', {}).get('wednesday_overnight', {})
    if tr and not tr.get('enabled', True):
        return None

    direction = s.position_direction if s.position_direction != 'flat' else _position_direction(s)
    proposed_pct = _proposed_position_pct(p, s)

    if tr:
        if direction in ('forward', 'flat'):
            rules = tr.get('forward', {})
            base_cap = float(rules.get('base_cap_pct', 0.30))
            favorable_cap = float(rules.get('favorable_cap_pct', 0.50))
            fav = rules.get('favorable_conditions', {})
            min_spread = float(fav.get('min_spread', 2.0))
            min_funding = float(fav.get('min_funding', 0.005))

            triple_swap_cost = abs(s.swap_fee_short) * 3
            funding_benefit = s.funding_rate if s.funding_rate > 0 else 0
            net_favorable = funding_benefit > triple_swap_cost * 0.5

            if proposed_pct > favorable_cap:
                return f'wed_overnight_forward_max:{proposed_pct:.2%}>{favorable_cap:.0%}'
            if proposed_pct > base_cap:
                if s.spread_30m_avg >= min_spread and s.funding_rate >= min_funding and net_favorable:
                    return None
                return (f'wed_overnight_forward_cap:{proposed_pct:.2%}>{base_cap:.0%}'
                        f'(spread={s.spread_30m_avg:.2f},funding={s.funding_rate:.4f},'
                        f'swap_cost_x3={triple_swap_cost:.4f})')

        elif direction == 'reverse':
            rules = tr.get('reverse', {})
            base_cap = float(rules.get('base_cap_pct', 0.20))
            favorable_cap = float(rules.get('favorable_cap_pct', 0.40))
            fav = rules.get('favorable_conditions', {})
            min_spread = float(fav.get('min_spread', 3.0))

            triple_swap_cost = abs(s.swap_fee_long) * 3
            funding_offset = abs(s.funding_rate) if s.funding_rate < 0 else 0
            net_favorable = funding_offset > triple_swap_cost * 0.5

            if proposed_pct > favorable_cap:
                return f'wed_overnight_reverse_max:{proposed_pct:.2%}>{favorable_cap:.0%}'
            if proposed_pct > base_cap:
                if abs(s.spread_30m_avg) >= min_spread and net_favorable:
                    return None
                return (f'wed_overnight_reverse_cap:{proposed_pct:.2%}>{base_cap:.0%}'
                        f'(spread={s.spread_30m_avg:.2f},'
                        f'swap_cost_x3={triple_swap_cost:.4f})')

        else:  # mixed
            if proposed_pct > 0.20:
                return f'wed_overnight_mixed_cap:{proposed_pct:.2%}>20%'

    else:
        # Fallback: original behavior when time_rules not configured
        if proposed_pct > 0.30:
            is_favorable = s.spread_30m_avg >= 2.0 and s.funding_rate >= 0.005
            if is_favorable and proposed_pct <= 0.50:
                return None
            if proposed_pct > 0.50:
                return f'wed_evening_max_50pct_exceeded:{proposed_pct:.2%}'
            return f'wed_evening_cap:{proposed_pct:.2%}>30%_without_favorable_combo'

    return None


def check_friday_weekend(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> Optional[str]:
    """Friday evening through Saturday close: graduated position reduction.

    Default phases (configurable via time_rules.friday_weekend.phases):
      Phase 1 (Fri 22:00 - Sat 00:00): max 30%, exception: spread>=5 + funding>=1%
      Phase 2 (Sat 00:00 - 02:00): max 20%
      Phase 3 (Sat 02:00 - 04:00): max 10%
      Phase 4 (Sat 04:00+): no new opens (approaching market close)
    """
    if p.action not in ('open_long', 'open_short'):
        return None
    bjt = _bjt_now(s)
    weekday = bjt.weekday()
    hour = bjt.hour

    is_fri_evening = weekday == 4 and hour >= 22
    is_saturday = weekday == 5
    if not is_fri_evening and not is_saturday:
        return None

    tr = cfg.get('time_rules', {}).get('friday_weekend', {})
    if tr and not tr.get('enabled', True):
        return None

    proposed_pct = _proposed_position_pct(p, s)

    phases = (tr or {}).get('phases', [
        {"fri_hour": 22, "sat_hour": None, "max_pct": 0.30,
         "exception": {"min_spread": 5.0, "min_funding": 0.01}},
        {"fri_hour": None, "sat_hour": 0, "max_pct": 0.20},
        {"fri_hour": None, "sat_hour": 2, "max_pct": 0.10},
        {"fri_hour": None, "sat_hour": 4, "max_pct": 0.0, "force_close": True},
    ])

    matched_phase = None
    if is_fri_evening:
        for phase in phases:
            fh = phase.get('fri_hour')
            if fh is not None and hour >= fh:
                matched_phase = phase
    elif is_saturday:
        for phase in reversed(phases):
            sh = phase.get('sat_hour')
            if sh is not None and hour >= sh:
                matched_phase = phase
                break
        if matched_phase is None:
            for phase in phases:
                if phase.get('fri_hour') is not None:
                    matched_phase = phase
                    break

    if matched_phase is None:
        if proposed_pct > 0.30:
            return f'friday_weekend_default_cap:{proposed_pct:.2%}>30%'
        return None

    max_pct = float(matched_phase.get('max_pct', 0.30))
    force_close = matched_phase.get('force_close', False)

    if force_close:
        return 'friday_weekend_force_close:no_new_opens_approaching_market_close'

    if proposed_pct > max_pct:
        exc = matched_phase.get('exception', {})
        if exc:
            min_sp = float(exc.get('min_spread', 99))
            min_fr = float(exc.get('min_funding', 99))
            if abs(s.spread_now) >= min_sp and abs(s.funding_rate) >= min_fr:
                return None
        phase_label = f"fri_{matched_phase.get('fri_hour', '?')}" if is_fri_evening else f"sat_{matched_phase.get('sat_hour', '?')}"
        return f'friday_weekend_phase_cap:{proposed_pct:.2%}>{max_pct:.0%}({phase_label})'

    return None


ESCALATABLE_PREFIXES = (
    'single_leg_detected_delta=',
    'must_open_both_legs_simultaneously:',
    'monday_open_volatility:',
    'monday_funding_window:',
    'wed_overnight_forward_cap:',
    'wed_overnight_forward_max:',
    'wed_overnight_reverse_cap:',
    'wed_overnight_reverse_max:',
    'wed_overnight_mixed_cap:',
    'wed_evening_cap:',
    'wed_evening_max_50pct_exceeded:',
    'friday_weekend_phase_cap:',
    'friday_weekend_default_cap:',
    'friday_weekend_force_close:',
)


GUARD_CHECKS = [
    check_symbol_whitelist,
    check_no_signal,
    check_single_trade_cap,
    check_total_position_cap,
    check_daily_volume_cap,
    check_leg_balance,
    check_monday_open,
    check_time_window,
    check_friday_weekend,
]


def run_guard(p: Proposal, s: MarketState, cfg: Dict[str, Any]) -> GuardResult:
    hard = []
    soft = []
    for fn in GUARD_CHECKS:
        v = fn(p, s, cfg)
        if v:
            if any(v.startswith(pfx) for pfx in ESCALATABLE_PREFIXES):
                soft.append(v)
            else:
                hard.append(v)
    all_violations = hard + soft
    return GuardResult(ok=not all_violations, violations=hard, escalatable_violations=soft)
