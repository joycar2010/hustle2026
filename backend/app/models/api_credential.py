import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class ApiCredential(Base):
    """API credential model for storing encrypted platform API keys"""

    __tablename__ = "api_credentials"

    credential_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    platform = Column(String(20), nullable=False)  # binance, bybit
    api_key = Column(Text, nullable=False)  # Encrypted
    api_secret = Column(Text, nullable=False)  # Encrypted
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", backref="api_credentials")

    __table_args__ = (
        Index('idx_api_credentials_user_platform', 'user_id', 'platform'),
    )

    def __repr__(self):
        return f"<ApiCredential(user_id={self.user_id}, platform={self.platform}, active={self.is_active})>"
