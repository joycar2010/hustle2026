"""用户-角色关联模型"""
import uuid
from datetime import datetime
from sqlalchemy import Column, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class UserRole(Base):
    """用户-角色关联模型"""

    __tablename__ = "user_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    expires_at = Column(TIMESTAMP)  # NULL表示永久有效

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="user_roles")
    role = relationship("Role", back_populates="user_roles")
    assigner = relationship("User", foreign_keys=[assigned_by])

    def __repr__(self):
        return f"<UserRole(user_id={self.user_id}, role_id={self.role_id})>"
