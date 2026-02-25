"""交易记录模型"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class Trade(Base):
    """交易记录模型"""

    __tablename__ = "trades"

    trade_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False, index=True)
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.position_id", ondelete="SET NULL"))
    symbol = Column(String(20), nullable=False, index=True)
    platform = Column(String(20), nullable=False)  # binance, bybit
    side = Column(String(10), nullable=False)  # buy, sell
    trade_type = Column(String(20), nullable=False)  # open, close, partial_close
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    fee = Column(Float)
    realized_pnl = Column(Float)
    timestamp = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User")
    account = relationship("Account")
    position = relationship("Position")

    def __repr__(self):
        return f"<Trade(trade_id={self.trade_id}, symbol={self.symbol}, side={self.side}, price={self.price})>"
