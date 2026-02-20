import uuid
from datetime import datetime
from sqlalchemy import Column, String, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class RiskAlert(Base):
    """Risk alert model for tracking risk notifications"""

    __tablename__ = "risk_alerts"

    alert_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    alert_level = Column(String(10), nullable=False)  # warning, danger, info
    alert_message = Column(String(200), nullable=False)
    create_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    expire_time = Column(TIMESTAMP)  # Auto-expire after 5 minutes

    # Relationships
    user = relationship("User", back_populates="risk_alerts")

    def __repr__(self):
        return f"<RiskAlert(alert_id={self.alert_id}, level={self.alert_level}, message={self.alert_message[:30]})>"
