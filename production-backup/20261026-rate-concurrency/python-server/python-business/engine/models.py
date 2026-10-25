import re

from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, Text, ForeignKey, Boolean,
    func, event,
)

from app.db.models import Base


def canonical_position_symbol(value: object) -> str:
    """Return the canonical Binance USDT pair used by active-position guards.

    Older rows and several API callers accepted ``BTC``, ``BTC-USDT`` and
    ``btcusdt`` interchangeably.  The database key must collapse those forms
    to one value.  Coin currently trades USDT pairs only; unknown/blank input
    is returned as an empty string and is rejected by execution code.
    """
    raw = re.sub(r"[-_\s]+", "", str(value or "").strip().upper())
    if not raw:
        return ""
    if raw.endswith("USDT"):
        return raw
    return f"{raw}USDT"


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    sub_account_id = Column(Integer, ForeignKey("sub_accounts.id"), nullable=False, index=True)
    symbol = Column(String(30), nullable=False, index=True)
    # Filled for all new ORM rows and backfilled by the active-position
    # uniqueness migration.  It remains nullable in the model so rolling
    # upgrades can read legacy rows before the migration is applied.
    canonical_symbol = Column(String(30), nullable=True, index=True)
    base_asset = Column(String(20), nullable=False)

    status = Column(String(30), nullable=False, default="PENDING_BORROW", index=True)

    # opening
    open_spread = Column(Numeric(10, 4))
    borrow_qty = Column(Numeric(20, 8))
    # Immutable USDT notional captured when the borrow is confirmed.  The
    # cumulative borrow cap must not shrink merely because the coin price
    # falls before a later bite.
    borrow_usdt_amount = Column(Numeric(15, 4))
    borrowed_at = Column(DateTime(timezone=True))
    borrow_interest_rate = Column(Numeric(10, 8))
    spot_sell_qty = Column(Numeric(20, 8))
    spot_sell_price = Column(Numeric(20, 8))
    spot_sell_order_id = Column(String(40))
    futures_long_qty = Column(Numeric(20, 8))
    futures_long_price = Column(Numeric(20, 8))
    futures_long_order_id = Column(String(40))
    open_usdt_amount = Column(Numeric(15, 4))

    # closing
    close_spread = Column(Numeric(10, 4))
    futures_close_price = Column(Numeric(20, 8))
    futures_close_order_id = Column(String(40))
    spot_buy_qty = Column(Numeric(20, 8))
    spot_buy_price = Column(Numeric(20, 8))
    spot_buy_order_id = Column(String(40))
    repay_qty = Column(Numeric(20, 8))
    repay_interest = Column(Numeric(20, 8))

    # funding tracking
    cumulative_funding_fee = Column(Numeric(15, 8), server_default='0')
    cumulative_interest = Column(Numeric(15, 8), server_default='0')
    funding_rate_ratio = Column(Numeric(10, 4), nullable=True)

    # pnl
    realized_pnl = Column(Numeric(15, 4))
    fee_total = Column(Numeric(15, 4))
    # 净期望闸(P0-1): 开仓时预期净收益 E(USDT) + 各分项JSON;平仓时本回路真实净损益(=realized+已结算资金费)
    expected_e = Column(Numeric(15, 4), nullable=True)
    round_net_pnl = Column(Numeric(15, 4), nullable=True)
    e_breakdown = Column(Text, nullable=True)

    # timestamps + error
    opened_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    user_id = Column(Integer, nullable=True)
    # 合约腿执行账户: NULL/"sub"=子账户自身(原行为), "master"=主账户(hedge_via_master)。
    # 平仓/资金费按此归属选 client,与全局开关解耦(开关中途翻转不影响存量仓位)。
    hedge_account = Column(String(10), nullable=True)


@event.listens_for(Position, "before_insert")
def _position_canonicalize_before_insert(_mapper, _connection, target):
    canonical = canonical_position_symbol(getattr(target, "symbol", None))
    if canonical:
        target.canonical_symbol = canonical
        # Keep newly-created rows consistent with the key used by all worker
        # queries.  The migration performs the same normalization for legacy
        # rows, so this does not create a second spelling of an active pair.
        target.symbol = canonical
        if not getattr(target, "base_asset", None):
            target.base_asset = canonical[:-4]


@event.listens_for(Position, "before_update")
def _position_canonicalize_before_update(_mapper, _connection, target):
    canonical = canonical_position_symbol(getattr(target, "symbol", None))
    if canonical:
        target.canonical_symbol = canonical
        target.symbol = canonical


class TradeLog(Base):
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True, index=True)
    sub_account_id = Column(Integer, nullable=False, index=True)
    action = Column(String(30), nullable=False)
    symbol = Column(String(30))
    side = Column(String(10))
    quantity = Column(Numeric(20, 8))
    price = Column(Numeric(20, 8))
    order_id = Column(String(40))
    status = Column(String(20), nullable=False)
    error_message = Column(Text)
    latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user_id = Column(Integer, nullable=True)


class EngineState(Base):
    __tablename__ = "engine_state"

    id = Column(Integer, primary_key=True)
    scope = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default="STOPPED")
    pid = Column(Integer)
    started_at = Column(DateTime(timezone=True))
    last_heartbeat = Column(DateTime(timezone=True))
    active_positions = Column(Integer, default=0)
    total_cycles = Column(Integer, default=0)
    error_message = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    user_id = Column(Integer, nullable=True)
