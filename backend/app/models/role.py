"""RBAC角色模型"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, TIMESTAMP, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class Role(Base):
    """角色模型"""

    __tablename__ = "roles"

    role_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_name = Column(String(50), nullable=False, unique=True, index=True)
    role_code = Column(String(50), nullable=False, unique=True, index=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_system = Column(Boolean, default=False, nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))

    # Relationships
    user_roles = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")
    role_permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Role(role_id={self.role_id}, role_code={self.role_code}, role_name={self.role_name})>"
