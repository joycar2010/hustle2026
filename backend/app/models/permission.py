"""RBAC权限模型"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class Permission(Base):
    """权限模型"""

    __tablename__ = "permissions"

    permission_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    permission_name = Column(String(100), nullable=False)
    permission_code = Column(String(100), nullable=False, unique=True, index=True)
    resource_type = Column(String(50), nullable=False, index=True)  # api, menu, button
    resource_path = Column(String(255))
    http_method = Column(String(10))
    description = Column(Text)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("permissions.permission_id"), index=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    role_permissions = relationship("RolePermission", back_populates="permission", cascade="all, delete-orphan")
    children = relationship("Permission", backref="parent", remote_side=[permission_id])

    def __repr__(self):
        return f"<Permission(permission_id={self.permission_id}, permission_code={self.permission_code})>"
