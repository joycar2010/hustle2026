import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, TIMESTAMP, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class StrategyStatus(str, enum.Enum):
    """Strategy status enum"""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class Strategy(Base):
    """Automated strategy model"""

    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False, default="XAUUSD")
    direction = Column(String(20), nullable=False)  # forward, reverse
    min_spread = Column(Float, nullable=False)  # Minimum spread to trigger
    status = Column(String(20), default=StrategyStatus.STOPPED, nullable=False)
    params = Column(JSON, default=dict)  # Additional parameters
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="strategies")

    def __repr__(self):
        return f"<Strategy(id={self.id}, name={self.name}, status={self.status})>"


class StrategyConfig(Base):
    """Strategy configuration model for arbitrage strategies"""

    __tablename__ = "strategy_configs"

    config_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    strategy_type = Column(String(20), nullable=False)  # forward, reverse
    target_spread = Column(Float, nullable=False)  # Target spread for entry
    order_qty = Column(Float, nullable=False)  # Order quantity
    retry_times = Column(Integer, default=3, nullable=False)  # Chase order retry times
    mt5_stuck_threshold = Column(Integer, default=5, nullable=False)  # MT5 stuck detection threshold
    opening_sync_count = Column(Integer, default=3, nullable=False)  # Opening position data sync count
    closing_sync_count = Column(Integer, default=3, nullable=False)  # Closing position data sync count
    m_coin = Column(Float, default=5, nullable=False)  # Max lots per batch order (deprecated, use opening_m_coin)
    opening_m_coin = Column(Float, default=5, nullable=False)  # Opening max lots per batch order
    closing_m_coin = Column(Float, default=5, nullable=False)  # Closing max lots per batch order
    ladders = Column(JSONB, default=list, nullable=False)  # Ladder configs array
    is_enabled = Column(Boolean, default=False, nullable=False)
    create_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    update_time = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="strategy_configs")

    def __repr__(self):
        return f"<StrategyConfig(config_id={self.config_id}, type={self.strategy_type}, enabled={self.is_enabled})>"
