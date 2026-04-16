"""Pending Order model for order persistence and recovery"""
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.core.database import Base
import uuid


class PendingOrder(Base):
    """待处理订单表 - 用于订单持久化和网络中断恢复"""

    __tablename__ = "pending_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    strategy_type = Column(String(20), nullable=False, comment="forward_opening, reverse_closing, etc.")
    platform = Column(String(20), nullable=False, comment="binance, bybit")
    order_id = Column(String(100), nullable=True, comment="Exchange order ID")
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False, comment="BUY, SELL")
    quantity = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8), nullable=True)
    order_type = Column(String(20), nullable=False, comment="LIMIT, MARKET")
    status = Column(String(20), nullable=False, comment="PENDING, FILLED, PARTIAL, CANCELLED, FAILED")
    filled_quantity = Column(Numeric(20, 8), nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime, nullable=True)
    extra_data = Column(JSONB, nullable=True, comment="Additional metadata")

    __table_args__ = (
        Index('idx_pending_orders_user_status', 'user_id', 'status'),
        Index('idx_pending_orders_created_at', 'created_at'),
        Index('idx_pending_orders_expires_at', 'expires_at'),
        Index('idx_pending_orders_order_id', 'order_id'),
    )

    def __repr__(self):
        return f"<PendingOrder(id={self.id}, platform={self.platform}, order_id={self.order_id}, status={self.status})>"
