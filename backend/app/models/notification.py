import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class Notification(Base):
    """Notification model for user alerts and messages"""

    __tablename__ = "notifications"

    notification_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # trade, alert, system, info
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    user = relationship("User", backref="notifications")

    __table_args__ = (
        Index('idx_notifications_user_read', 'user_id', 'is_read'),
    )

    def __repr__(self):
        return f"<Notification(user_id={self.user_id}, type={self.type}, read={self.is_read})>"
