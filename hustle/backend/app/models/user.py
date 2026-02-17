from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from ..core.database import Base

class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    email = Column(String(100), unique=True, index=True)
    create_time = Column(DateTime(timezone=True), server_default=func.now())
    update_time = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_active = Column(Boolean, default=True)

    # Relationships
    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    strategy_configs = relationship("StrategyConfig", back_populates="user", cascade="all, delete-orphan")
    arbitrage_tasks = relationship("ArbitrageTask", back_populates="user", cascade="all, delete-orphan")
    risk_alerts = relationship("RiskAlert", back_populates="user", cascade="all, delete-orphan")
