import uuid
import enum
from typing import Optional
from datetime import datetime
from sqlalchemy import Column, String, Float, TIMESTAMP, ForeignKey
from sqlalchemy import inspect as sqla_inspect
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.platform import PlatformId


class OrderStatus(str, enum.Enum):
    """Order status enum"""
    NEW = "new"
    FILLED = "filled"
    CANCELED = "canceled"
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    MANUALLY_PROCESSED = "manually_processed"


class OrderRecord(Base):
    """Order record model for tracking all orders"""

    __tablename__ = "order_records"

    order_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.account_id"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False)  # XAUUSDT, XAUUSD+
    order_side = Column(String(10), nullable=False)  # buy, sell
    order_type = Column(String(10), nullable=False)  # limit, market
    price = Column(Float, nullable=False)
    qty = Column(Float, nullable=False)
    filled_qty = Column(Float, default=0.0, nullable=False)
    fee = Column(Float, default=0.0, nullable=False)  # Actual commission/fee from exchange
    source = Column(String(20), default="manual", nullable=False)  # manual, strategy, sync
    status = Column(String(20), nullable=False)  # new, filled, canceled, pending
    platform_order_id = Column(String(100))  # Platform's order ID
    create_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    update_time = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    account = relationship("Account", back_populates="orders")

    def __repr__(self):
        return f"<OrderRecord(order_id={self.order_id}, symbol={self.symbol}, side={self.order_side}, status={self.status})>"

    @property
    def platform(self) -> Optional[str]:
        """Canonical platform key ('binance' / 'bybit' / 'ic_markets' / 'gate') derived from
        `account.platform_id` via :class:`PlatformId`.

        Returns None when:
          - the `account` relationship has not been eager-loaded (we refuse to trigger an
            async lazy-load — that would crash with MissingGreenlet in async callers);
          - the account exists but its platform_id is unknown to PlatformId.

        Callers MUST eager-load the account:
            select(Order).options(selectinload(Order.account)).where(...)
        """
        state = sqla_inspect(self)
        if 'account' in state.unloaded:
            return None
        acc = self.account
        if acc is None:
            return None
        pid = PlatformId.from_key(acc.platform_id)
        return pid.key if pid else None


# Alias for backward compatibility
Order = OrderRecord
