from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from ..core.database import Base

class StrategyConfig(Base):
    __tablename__ = "strategy_configs"

    config_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    strategy_type = Column(String(20), nullable=False)
    target_spread = Column(Float, nullable=False)
    order_qty = Column(Float, nullable=False)
    retry_times = Column(Integer, default=3)
    mt5_stuck_threshold = Column(Integer, default=5)
    is_enabled = Column(Boolean, default=False)
    create_time = Column(DateTime(timezone=True), server_default=func.now())
    update_time = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="strategy_configs")
