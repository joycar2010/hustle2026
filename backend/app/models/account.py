import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, TIMESTAMP, SmallInteger, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Account(Base):
    """Account model for managing Binance and Bybit MT5 accounts.

    ⚠️ PITFALL — `platform` vs `platform_id`:
      * `platform_id` (SmallInteger, 1/2/3/4) IS the authoritative platform discriminator.
        Business logic MUST use this column, compared against :class:`app.core.platform.PlatformId`
        members (IntEnum): e.g. `if account.platform_id == PlatformId.BINANCE: ...`.
      * `platform` is a SQLAlchemy *relationship* that returns a :class:`Platform` ORM object
        (lazy-loaded row from the `platforms` table). Never compare it to a string or an int —
        `account.platform == "binance"` and `account.platform == 1` are BOTH always False,
        silently. Historical code that did this never ran (see commit that fixed
        account_sync_service).
      * Lowercase string keys ("binance", "bybit", ...) belong on varchar columns
        (`orders.platform`, `platforms.platform_name`) and at API boundaries. Use
        `PlatformId.BINANCE.key` there — never a bare literal.
      * Order-level platform derivation is provided by :prop:`OrderRecord.platform`; it
        resolves through `account.platform_id` and returns the canonical `PlatformId.*.key`.
    """

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

    # Leverage settings
    leverage = Column(Integer, nullable=True)  # Leverage multiplier (e.g., 20, 100)

    # IPIPGO / static IP proxy configuration (JSONB)
    proxy_config = Column(JSONB, nullable=True, comment='IPIPGO静态IP代理配置')

    # Account status
    is_default = Column(Boolean, default=False, nullable=False)
    account_role = Column(String(10), nullable=True, comment='primary=主账号, hedge=对冲账号')
    is_active = Column(Boolean, default=True, nullable=False)
    create_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    update_time = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships — see class docstring: business logic MUST use `platform_id` + PlatformId.
    user = relationship("User", back_populates="accounts")
    platform = relationship("Platform", back_populates="accounts")  # ⚠️ ORM object, NEVER compare to str/int
    orders = relationship("OrderRecord", back_populates="account", cascade="all, delete-orphan")

    def __repr__(self):
        # Include resolved PlatformId name so log lines are self-explanatory; fall back gracefully.
        try:
            from app.core.platform import PlatformId
            pid = PlatformId.from_key(self.platform_id)
            tag = pid.name if pid else f"unknown({self.platform_id})"
        except Exception:
            tag = f"pid={self.platform_id}"
        return f"<Account(id={self.account_id}, name={self.account_name}, platform={tag})>"
