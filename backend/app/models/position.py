import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class Position(Base):
    """Position model for tracking open positions"""

    __tablename__ = "positions"

    position_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.account_id"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False)  # XAUUSDT, XAUUSD.s
    platform = Column(String(20), nullable=False)  # binance, bybit
    side = Column(String(10), nullable=False)  # long, short
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    leverage = Column(Integer, default=1, nullable=False)
    unrealized_pnl = Column(Float, default=0.0, nullable=False)
    realized_pnl = Column(Float, default=0.0, nullable=False)
    margin_used = Column(Float, nullable=False)
    is_open = Column(Boolean, default=True, nullable=False)
    open_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    close_time = Column(TIMESTAMP)
    update_time = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", backref="positions")
    account = relationship("Account", backref="positions")

    __table_args__ = (
        Index('idx_positions_user_open', 'user_id', 'is_open'),
    )

    def __repr__(self):
        return f"<Position(position_id={self.position_id}, symbol={self.symbol}, side={self.side}, pnl={self.unrealized_pnl})>"
