import uuid
import enum
from datetime import datetime
from sqlalchemy import Column, String, Float, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class TaskStatus(str, enum.Enum):
    """Arbitrage task status enum"""
    OPEN = "open"
    CLOSED = "closed"
    FAILED = "failed"


class ArbitrageTask(Base):
    """Arbitrage task model for tracking arbitrage operations"""

    __tablename__ = "arbitrage_tasks"

    task_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    strategy_type = Column(String(20), nullable=False)  # forward, reverse
    open_spread = Column(Float, nullable=False)
    close_spread = Column(Float)
    status = Column(String(20), nullable=False)  # open, closed, failed
    open_time = Column(TIMESTAMP, nullable=False)
    close_time = Column(TIMESTAMP)
    profit = Column(Float)  # Net profit after fees

    # Relationships
    user = relationship("User", back_populates="arbitrage_tasks")

    def __repr__(self):
        return f"<ArbitrageTask(task_id={self.task_id}, type={self.strategy_type}, status={self.status})>"
