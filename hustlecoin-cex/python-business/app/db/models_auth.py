from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Enum, func
import enum

from app.db.models import Base


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    USER = "USER"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    email = Column(String(100), nullable=True)
    display_name = Column(String(50), nullable=True)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.USER)
    is_active = Column(Boolean, default=True)
    max_sub_accounts = Column(Integer, default=5)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    login_ip = Column(String(50), nullable=True)
    feishu_open_id = Column(String(100), nullable=True)
    feishu_phone = Column(String(20), nullable=True)
    feishu_union_id = Column(String(100), nullable=True)


# Keep AdminUser as alias for backward compatibility during migration
AdminUser = User


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    user = Column(String(50), nullable=True)
    user_id = Column(Integer, nullable=True, index=True)
    action = Column(String(10), nullable=False)
    resource = Column(String(200), nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
