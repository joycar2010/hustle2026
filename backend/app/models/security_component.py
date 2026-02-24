"""安全组件配置模型"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class SecurityComponent(Base):
    """安全组件配置模型"""

    __tablename__ = "security_components"

    component_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_code = Column(String(50), nullable=False, unique=True, index=True)
    component_name = Column(String(100), nullable=False)
    component_type = Column(String(50), nullable=False, index=True)  # middleware, service, protection
    description = Column(Text)
    is_enabled = Column(Boolean, default=False, nullable=False, index=True)
    config_json = Column(JSONB)  # 组件配置参数
    priority = Column(Integer, default=0)  # 执行优先级
    status = Column(String(20), default='inactive')  # active, inactive, error
    last_check_at = Column(TIMESTAMP)
    error_message = Column(Text)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))

    # Relationships
    logs = relationship("SecurityComponentLog", back_populates="component", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<SecurityComponent(component_code={self.component_code}, is_enabled={self.is_enabled})>"


class SecurityComponentLog(Base):
    """安全组件操作日志模型"""

    __tablename__ = "security_component_logs"

    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_id = Column(UUID(as_uuid=True), ForeignKey("security_components.component_id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(50), nullable=False, index=True)  # enable, disable, config_update, error
    old_config = Column(JSONB)
    new_config = Column(JSONB)
    result = Column(String(20), nullable=False)  # success, failure
    error_message = Column(Text)
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    performed_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)
    ip_address = Column(String(45))

    # Relationships
    component = relationship("SecurityComponent", back_populates="logs")
    performer = relationship("User", foreign_keys=[performed_by])

    def __repr__(self):
        return f"<SecurityComponentLog(component_id={self.component_id}, action={self.action})>"
