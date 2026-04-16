import uuid
from datetime import datetime
import sqlalchemy as sa
from sqlalchemy import Column, String, Boolean, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class User(Base):
    """User model for authentication and account management"""

    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=sa.text("gen_random_uuid()"))
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    email = Column(String(100), nullable=True, index=True)
    role = Column(String(50), default='交易员', nullable=False)
    feishu_open_id = Column(String(100), index=True, comment='飞书Open ID，用于发送飞书通知')
    feishu_mobile = Column(String(20), comment='飞书绑定的手机号')
    feishu_union_id = Column(String(100), comment='飞书Union ID，跨应用唯一标识')
    create_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    update_time = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    strategies = relationship("Strategy", back_populates="user", cascade="all, delete-orphan")
    strategy_configs = relationship("StrategyConfig", back_populates="user", cascade="all, delete-orphan")
    arbitrage_tasks = relationship("ArbitrageTask", back_populates="user", cascade="all, delete-orphan")
    risk_alerts = relationship("RiskAlert", back_populates="user", cascade="all, delete-orphan")
    risk_settings = relationship("RiskSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    user_roles = relationship("UserRole", foreign_keys="[UserRole.user_id]", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(user_id={self.user_id}, username={self.username})>"
