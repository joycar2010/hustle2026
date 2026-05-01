from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, Text, ForeignKey, Boolean,
    func,
)

from app.db.models import Base


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    sub_account_id = Column(Integer, ForeignKey("sub_accounts.id"), nullable=False, index=True)
    symbol = Column(String(30), nullable=False, index=True)
    base_asset = Column(String(20), nullable=False)

    status = Column(String(30), nullable=False, default="PENDING_BORROW", index=True)

    # opening
    open_spread = Column(Numeric(10, 4))
    borrow_qty = Column(Numeric(20, 8))
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

    # pnl
    realized_pnl = Column(Numeric(15, 4))
    fee_total = Column(Numeric(15, 4))

    # timestamps + error
    opened_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)


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


class EngineState(Base):
    __tablename__ = "engine_state"

    id = Column(Integer, primary_key=True)
    scope = Column(String(30), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="STOPPED")
    pid = Column(Integer)
    started_at = Column(DateTime(timezone=True))
    last_heartbeat = Column(DateTime(timezone=True))
    active_positions = Column(Integer, default=0)
    total_cycles = Column(Integer, default=0)
    error_message = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
