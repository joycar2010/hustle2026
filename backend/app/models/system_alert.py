"""系统告警模型"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class SystemAlert(Base):
    """系统告警模型"""

    __tablename__ = "system_alerts"

    alert_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False, index=True)  # risk, spread, system, trade
    severity = Column(String(20), nullable=False, index=True)  # info, warning, error, critical
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    timestamp = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<SystemAlert(alert_id={self.alert_id}, type={self.alert_type}, severity={self.severity})>"
