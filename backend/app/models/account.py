import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, TIMESTAMP, SmallInteger, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class Account(Base):
    """Account model for managing Binance and Bybit MT5 accounts"""

    __tablename__ = "accounts"

    account_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    platform_id = Column(SmallInteger, ForeignKey("platforms.platform_id"), nullable=False)
    account_name = Column(String(50), nullable=False)
    api_key = Column(String(256), nullable=False)
    api_secret = Column(String(256), nullable=False)
    passphrase = Column(String(100))  # Optional, for Bybit V5

    # MT5-specific fields
    mt5_id = Column(String(100))  # MT5 account ID
    mt5_server = Column(String(100))  # MT5 server address
    mt5_primary_pwd = Column(String(256))  # Encrypted MT5 primary password
    is_mt5_account = Column(Boolean, default=False, nullable=False)

    # Account status
    is_default = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    create_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    update_time = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="accounts")
    platform = relationship("Platform", back_populates="accounts")
    orders = relationship("OrderRecord", back_populates="account", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Account(account_id={self.account_id}, name={self.account_name}, platform_id={self.platform_id})>"
