"""角色-权限关联模型"""
import uuid
from datetime import datetime
from sqlalchemy import Column, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class RolePermission(Base):
    """角色-权限关联模型"""

    __tablename__ = "role_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False, index=True)
    permission_id = Column(UUID(as_uuid=True), ForeignKey("permissions.permission_id", ondelete="CASCADE"), nullable=False, index=True)
    granted_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))

    # Relationships
    role = relationship("Role", back_populates="role_permissions")
    permission = relationship("Permission", back_populates="role_permissions")
    granter = relationship("User", foreign_keys=[granted_by])

    def __repr__(self):
        return f"<RolePermission(role_id={self.role_id}, permission_id={self.permission_id})>"
