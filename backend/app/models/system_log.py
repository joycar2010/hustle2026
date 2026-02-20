import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class SystemLog(Base):
    """System log model for tracking system events and errors"""

    __tablename__ = "system_logs"

    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), index=True)
    level = Column(String(20), nullable=False)  # info, warning, error, critical
    category = Column(String(50), nullable=False)  # api, trade, system, auth
    message = Column(Text, nullable=False)
    details = Column(Text)  # JSON string for additional details
    timestamp = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    user = relationship("User", backref="logs")

    __table_args__ = (
        Index('idx_system_logs_level_time', 'level', 'timestamp'),
        Index('idx_system_logs_category_time', 'category', 'timestamp'),
    )

    def __repr__(self):
        return f"<SystemLog(level={self.level}, category={self.category}, time={self.timestamp})>"
