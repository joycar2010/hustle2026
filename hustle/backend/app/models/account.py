from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, SmallInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from ..core.database import Base

class Account(Base):
    __tablename__ = "accounts"

    account_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    platform_id = Column(SmallInteger, ForeignKey("platforms.platform_id"), nullable=False)
    account_name = Column(String(50), nullable=False)
    api_key = Column(String(256), nullable=False)
    api_secret = Column(String(256), nullable=False)
    passphrase = Column(String(100), nullable=True)
    mt5_id = Column(String(100), nullable=True)
    mt5_server = Column(String(100), nullable=True)
    mt5_primary_pwd = Column(String(256), nullable=True)
    is_mt5_account = Column(Boolean, default=False)
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    create_time = Column(DateTime(timezone=True), server_default=func.now())
    update_time = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="accounts")
    platform = relationship("Platform", back_populates="accounts")
    order_records = relationship("OrderRecord", back_populates="account", cascade="all, delete-orphan")
