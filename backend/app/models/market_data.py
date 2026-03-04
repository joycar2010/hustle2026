import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, TIMESTAMP, Index
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class MarketData(Base):
    """Market data model for storing real-time price information"""

    __tablename__ = "market_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False)  # XAUUSDT, XAUUSD.s
    platform = Column(String(20), nullable=False)  # binance, bybit
    bid_price = Column(Float, nullable=False)
    ask_price = Column(Float, nullable=False)
    mid_price = Column(Float, nullable=False)
    timestamp = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index('idx_market_data_symbol_platform_time', 'symbol', 'platform', 'timestamp'),
    )

    def __repr__(self):
        return f"<MarketData(symbol={self.symbol}, platform={self.platform}, mid={self.mid_price})>"


class SpreadRecord(Base):
    """Spread record model for storing historical spread data"""

    __tablename__ = "spread_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False, default="XAUUSDT")
    binance_bid = Column(Float, nullable=False)
    binance_ask = Column(Float, nullable=False)
    bybit_bid = Column(Float, nullable=False)
    bybit_ask = Column(Float, nullable=False)
    forward_spread = Column(Float, nullable=False)  # 正向开仓: bybit_bid - binance_bid
    reverse_spread = Column(Float, nullable=False)  # 反向开仓: binance_ask - bybit_ask
    timestamp = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index('idx_spread_records_time', 'timestamp'),
    )

    def __repr__(self):
        return f"<SpreadRecord(forward={self.forward_spread}, reverse={self.reverse_spread})>"
