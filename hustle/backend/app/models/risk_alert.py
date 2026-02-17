from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from ..core.database import Base

class RiskAlert(Base):
    __tablename__ = "risk_alerts"

    alert_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    alert_level = Column(String(10), nullable=False)
    alert_message = Column(String(200), nullable=False)
    create_time = Column(DateTime(timezone=True), server_default=func.now())
    expire_time = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="risk_alerts")
