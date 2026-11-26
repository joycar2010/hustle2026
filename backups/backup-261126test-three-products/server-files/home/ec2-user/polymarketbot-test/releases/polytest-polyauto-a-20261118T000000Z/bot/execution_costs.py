"""Pure executable-price/fee accounting shared by Live admission and Paper.

Amounts are evaluated with Decimal. Book VWAP already includes the spread and
depth slippage; callers must not subtract the same costs a second time. Maker
estimates describe a conditional fill and never assert that a quote will fill.
No signing, network, configuration mutation or predicted rebate is performed.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
import math
import time
from typing import Any, Mapping

MICRO = Decimal('0.000001')
ZERO = Decimal(0)


def number(value: Any, name: str, *, minimum=None, maximum=None) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f'{name} is missing or invalid')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{name} is invalid') from None
    if not result.is_finite():
        raise ValueError(f'{name} must be finite')
    if minimum is not None and result < Decimal(str(minimum)):
        raise ValueError(f'{name} is below minimum')
    if maximum is not None and result > Decimal(str(maximum)):
        raise ValueError(f'{name} is above maximum')
    return result


@dataclass(frozen=True)
class FeeSchedule:
    rate: float
    exponent: float = 1.0
    taker_only: bool = True
    source: str = 'explicit_paper_scenario'
    as_of: float | None = None

    def __post_init__(self):
        number(self.rate, 'fee rate', minimum=0, maximum=1)
        number(self.exponent, 'fee exponent', minimum=0, maximum=10)
        if self.taker_only is not True:
            raise ValueError('Only an explicit taker-only fee schedule is supported')
        if not self.source:
            raise ValueError('Fee provenance is required')
        if self.as_of is not None:
            number(self.as_of, 'fee timestamp', minimum=0)

    @classmethod
    def from_market(cls, metadata: Mapping, *, as_of=None):
        """Read the market's current schedule; never infer from old baseFee."""
        if not isinstance(metadata, Mapping):
            raise ValueError('Market fee metadata is missing')
        schedule = metadata.get('feeSchedule') or metadata.get('fee_schedule')
        if isinstance(schedule, Mapping):
            if 'rate' not in schedule or 'exponent' not in schedule:
                raise ValueError('Market fee schedule is incomplete')
            taker_only = schedule.get('takerOnly', schedule.get('taker_only'))
            return cls(float(number(schedule['rate'], 'market fee rate', minimum=0, maximum=1)),
                       float(number(schedule['exponent'], 'market fee exponent', minimum=0, maximum=10)),
                       taker_only, 'market_fee_schedule', as_of)
        if metadata.get('feesEnabled') is False or metadata.get('fees_enabled') is False:
            return cls(0., 1., True, 'market_fees_disabled', as_of)
        raise ValueError('Market fee schedule is unavailable')

    def fee(self, quantity, price, *, role='TAKER', conservative=False) -> Decimal:
        quantity = number(quantity, 'fee quantity', minimum=0)
        price = number(price, 'fee price', minimum=0, maximum=1)
        role = str(role).upper()
        if role not in {'MAKER', 'TAKER', 'SETTLEMENT'}:
            raise ValueError('Unknown liquidity role')
        if role != 'TAKER' or quantity == 0:
            return ZERO
        raw = quantity * number(self.rate, 'fee rate') * ((price * (1-price)) ** number(self.exponent, 'fee exponent'))
        return raw.quantize(MICRO, rounding=ROUND_CEILING if conservative else ROUND_HALF_UP)


@dataclass(frozen=True)
class ExecutionEstimate:
    available: bool
    reason: str | None
    side: str
    requested_size: float
    filled_size: float
    gross_amount_usd: float
    fee_usd: float                 # positive expense, not signed ledger delta
    net_cash_change_usd: float    # BUY negative, SELL positive
    vwap: float | None
    worst_price: float | None
    complete: bool
    liquidity_role: str
    levels: tuple[tuple[float, float, float], ...] = ()
    book_as_of: float | None = None


def _unavailable(reason, side, size, role, stamp=None):
    return ExecutionEstimate(False, reason, side, float(size), 0., 0., 0., 0., None, None, False, role, (), stamp)


def estimate_execution(book, side, size, limit_price, schedule: FeeSchedule | None,
                       *, now=None, max_book_age_sec=1.5, liquidity_role='TAKER',
                       require_complete=True, conservative_fees=True) -> ExecutionEstimate:
    """Walk the executable book, retaining exact level fees and filled size.

    For MAKER, this is only a conditional-at-limit quote valuation. Use the
    Paper queue engine / real order evidence to determine whether it fills.
    """
    now = time.time() if now is None else float(number(now, 'execution time', minimum=0))
    side, role = str(side).upper(), str(liquidity_role).upper()
    quantity = number(size, 'requested size', minimum=0)
    limit = number(limit_price, 'limit price', minimum=0, maximum=1)
    if side not in {'BUY','SELL'} or role not in {'MAKER','TAKER'}:
        raise ValueError('Invalid execution side or role')
    if quantity <= 0 or limit <= 0 or limit >= 1:
        return _unavailable('invalid_size_or_price', side, quantity, role)
    if not isinstance(schedule, FeeSchedule):
        return _unavailable('fee_schedule_unavailable', side, quantity, role)
    stamp = getattr(book, 'fetched_at', None)
    try:
        stamp = float(number(stamp, 'book timestamp', minimum=0))
    except ValueError:
        return _unavailable('book_timestamp_unavailable', side, quantity, role)
    max_age = float(number(max_book_age_sec, 'book maximum age', minimum=0))
    if stamp <= 0 or now-stamp > max_age or stamp-now > .25:
        return _unavailable('book_stale_or_future', side, quantity, role, stamp)
    if role == 'MAKER':
        fee = schedule.fee(quantity, limit, role=role)
        gross = quantity*limit
        signed = -(gross+fee) if side=='BUY' else gross-fee
        return ExecutionEstimate(True,None,side,float(quantity),float(quantity),float(gross),float(fee),
                                 float(signed),float(limit),float(limit),True,role,
                                 ((float(limit),float(quantity),float(fee)),),stamp)
    levels = getattr(book, 'asks' if side=='BUY' else 'bids', ())
    parsed=[]
    for level in levels:
        try:
            p = number(level.price, 'depth price', minimum=0, maximum=1)
            q = number(level.size, 'depth size', minimum=0)
        except (ValueError, AttributeError):
            return _unavailable('book_depth_invalid', side, quantity, role, stamp)
        if p>0 and q>0:
            parsed.append((p,q))
    parsed.sort(key=lambda level: level[0], reverse=side=='SELL')
    left, gross, fees, fills = quantity, ZERO, ZERO, []
    for p,q in parsed:
        if (side=='BUY' and p>limit) or (side=='SELL' and p<limit):
            continue
        taken=min(left,q)
        if taken<=0: break
        fee=schedule.fee(taken,p,role=role,conservative=conservative_fees)
        gross+=taken*p; fees+=fee; left-=taken
        fills.append((float(p),float(taken),float(fee)))
    done=quantity-left
    complete=left<=Decimal('0.00000001')
    if done<=0:
        return _unavailable('no_executable_depth', side, quantity, role, stamp)
    if require_complete and not complete:
        return _unavailable('insufficient_executable_depth', side, quantity, role, stamp)
    signed=-(gross+fees) if side=='BUY' else gross-fees
    return ExecutionEstimate(True,None,side,float(quantity),float(done),float(gross),float(fees),float(signed),
                             float(gross/done),fills[-1][0],complete,role,tuple(fills),stamp)


@dataclass(frozen=True)
class NetExitDecision:
    available: bool
    should_exit: bool
    reason: str
    net_proceeds_usd: float | None
    allocated_cost_usd: float | None
    net_profit_usd: float | None
    net_profit_fraction: float | None
    required_net_profit_usd: float | None
    fee_usd: float | None


def evaluate_net_exit(estimate: ExecutionEstimate, *, position_size, remaining_cost_usd,
                      entry_fees_usd=0, target_fraction=.05,
                      minimum_profit_usd=0, profit_buffer_usd=0,
                      extra_exit_cost_usd=0) -> NetExitDecision:
    """Compare net liquidation proceeds with *remaining* actual paid cost.

    remaining_cost_usd EXCLUDES paid entry_fees_usd. If a caller's cost already
    includes fees, pass entry_fees_usd=0. Both are allocated pro rata for a
    partial exit; earlier sold quantities/costs must not be charged again.
    Spread and depth are already represented by estimate's executable VWAP.
    """
    try:
        size=number(position_size,'remaining position size',minimum=0)
        cost=number(remaining_cost_usd,'remaining entry cost',minimum=0)
        paid=number(entry_fees_usd,'remaining paid entry fee',minimum=0)
        target=number(target_fraction,'net profit target',minimum=0)
        minimum=number(minimum_profit_usd,'minimum net profit',minimum=0)
        buffer=number(profit_buffer_usd,'additional net profit buffer',minimum=0)
        extra=number(extra_exit_cost_usd,'additional exit cost',minimum=0)
        if not isinstance(estimate,ExecutionEstimate) or not estimate.available or estimate.side!='SELL':
            raise ValueError(getattr(estimate,'reason',None) or 'exit_estimate_unavailable')
        filled=number(estimate.filled_size,'estimated exit size',minimum=0)
        if size<=0 or cost+paid<=0 or filled<=0 or filled>size+Decimal('0.00000001'):
            raise ValueError('position_cost_or_quantity_unavailable')
        allocated=(cost+paid)*min(filled/size,Decimal(1))
        proceeds=number(estimate.net_cash_change_usd,'net proceeds')-extra
        profit=proceeds-allocated
        required=max(allocated*target+buffer,minimum)
        return NetExitDecision(True,profit>=required,'net_target_met' if profit>=required else 'net_target_not_met',
                               float(proceeds),float(allocated),float(profit),float(profit/allocated),
                               float(required),estimate.fee_usd)
    except (ValueError,TypeError,InvalidOperation) as exc:
        return NetExitDecision(False,False,str(exc),None,None,None,None,None,None)


def executable_entry_edge(probability, estimate: ExecutionEstimate, *, uncertainty_buffer=0,
                          expected_future_exit_cost_usd=0) -> float | None:
    """Per-share hold-to-settlement EV; early-exit policies need path replay."""
    try:
        p=number(probability,'calibrated probability',minimum=0,maximum=1)
        uncertainty=number(uncertainty_buffer,'probability uncertainty',minimum=0,maximum=1)
        future=number(expected_future_exit_cost_usd,'future exit cost',minimum=0)
        if not estimate.available or not estimate.complete or estimate.side!='BUY' or estimate.filled_size<=0:
            return None
        q=number(estimate.filled_size,'entry quantity',minimum=0)
        cost=-number(estimate.net_cash_change_usd,'entry net cash')+future
        return float(p-uncertainty-cost/q)
    except (ValueError,TypeError):
        return None
