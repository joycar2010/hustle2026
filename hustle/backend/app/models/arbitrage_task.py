from sqlalchemy import Column, String, DateTime, ForeignKey, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from ..core.database import Base

class ArbitrageTask(Base):
    __tablename__ = "arbitrage_tasks"

    task_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    strategy_type = Column(String(20), nullable=False)
    open_spread = Column(Float, nullable=False)
    close_spread = Column(Float, nullable=True)
    status = Column(String(20), nullable=False)
    open_time = Column(DateTime(timezone=True), nullable=False)
    close_time = Column(DateTime(timezone=True), nullable=True)
    profit = Column(Float, nullable=True)

    # Relationships
    user = relationship("User", back_populates="arbitrage_tasks")
    order_records = relationship("OrderRecord", back_populates="arbitrage_task", cascade="all, delete-orphan")
