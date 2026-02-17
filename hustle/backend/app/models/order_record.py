from sqlalchemy import Column, String, DateTime, ForeignKey, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from ..core.database import Base

class OrderRecord(Base):
    __tablename__ = "order_records"

    order_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.account_id"), nullable=False)
    task_id = Column(UUID(as_uuid=True), ForeignKey("arbitrage_tasks.task_id"), nullable=True)
    symbol = Column(String(20), nullable=False)
    order_side = Column(String(10), nullable=False)
    order_type = Column(String(10), nullable=False)
    price = Column(Float, nullable=False)
    qty = Column(Float, nullable=False)
    filled_qty = Column(Float, default=0)
    status = Column(String(20), nullable=False)
    platform_order_id = Column(String(100), nullable=True)
    create_time = Column(DateTime(timezone=True), server_default=func.now())
    update_time = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    account = relationship("Account", back_populates="order_records")
    arbitrage_task = relationship("ArbitrageTask", back_populates="order_records")
