import uuid
import enum
from datetime import datetime
from sqlalchemy import Column, String, Float, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class OrderStatus(str, enum.Enum):
    """Order status enum"""
    NEW = "new"
    FILLED = "filled"
    CANCELED = "canceled"
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"


class OrderRecord(Base):
    """Order record model for tracking all orders"""

    __tablename__ = "order_records"

    order_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.account_id"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False)  # XAUUSDT, XAUUSD.s
    order_side = Column(String(10), nullable=False)  # buy, sell
    order_type = Column(String(10), nullable=False)  # limit, market
    price = Column(Float, nullable=False)
    qty = Column(Float, nullable=False)
    filled_qty = Column(Float, default=0.0, nullable=False)
    status = Column(String(20), nullable=False)  # new, filled, canceled, pending
    platform_order_id = Column(String(100))  # Platform's order ID
    create_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    update_time = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    account = relationship("Account", back_populates="orders")

    def __repr__(self):
        return f"<OrderRecord(order_id={self.order_id}, symbol={self.symbol}, side={self.order_side}, status={self.status})>"


# Alias for backward compatibility
Order = OrderRecord
