import uuid
from datetime import datetime
from sqlalchemy import Column, Float, Integer, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class RiskSettings(Base):
    """Risk settings model for storing user-specific risk control thresholds"""

    __tablename__ = "risk_settings"

    settings_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, unique=True, index=True)

    # Account Net Asset Alerts
    binance_net_asset = Column(Float, default=10000, nullable=False)
    bybit_mt5_net_asset = Column(Float, default=10000, nullable=False)
    total_net_asset = Column(Float, default=20000, nullable=False)

    # Liquidation Price Alerts
    binance_liquidation_price = Column(Float, default=2000, nullable=False)
    bybit_mt5_liquidation_price = Column(Float, default=2000, nullable=False)

    # MT5 Lag Count
    mt5_lag_count = Column(Integer, default=5, nullable=False)

    # Reverse Arbitrage (Long Bybit)
    reverse_open_price = Column(Float, default=0.5, nullable=False)
    reverse_open_sync_count = Column(Integer, default=3, nullable=False)
    reverse_close_price = Column(Float, default=0.2, nullable=False)
    reverse_close_sync_count = Column(Integer, default=3, nullable=False)

    # Forward Arbitrage (Long Binance)
    forward_open_price = Column(Float, default=0.5, nullable=False)
    forward_open_sync_count = Column(Integer, default=3, nullable=False)
    forward_close_price = Column(Float, default=0.2, nullable=False)
    forward_close_sync_count = Column(Integer, default=3, nullable=False)

    create_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    update_time = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="risk_settings")

    def __repr__(self):
        return f"<RiskSettings(user_id={self.user_id}, settings_id={self.settings_id})>"
