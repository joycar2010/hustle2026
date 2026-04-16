import uuid
from datetime import datetime
from sqlalchemy import Column, Float, Integer, String, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class RiskSettings(Base):
    """Risk settings model for storing user-specific risk control thresholds"""

    __tablename__ = "risk_settings"

    settings_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True)
    pair_code = Column(String(30), nullable=False, default='XAU')  # hedging pair code

    # Account Net Asset Alerts
    binance_net_asset = Column(Float, nullable=True)
    bybit_mt5_net_asset = Column(Float, nullable=True)
    total_net_asset = Column(Float, nullable=True)

    # Liquidation Price Alerts
    binance_liquidation_price = Column(Float, nullable=True)
    bybit_mt5_liquidation_price = Column(Float, nullable=True)

    # MT5 Lag Count
    mt5_lag_count = Column(Integer, nullable=True)

    # Reverse Arbitrage (Long Bybit)
    reverse_open_price = Column(Float, nullable=True)
    reverse_open_sync_count = Column(Integer, nullable=True)
    reverse_close_price = Column(Float, nullable=True)
    reverse_close_sync_count = Column(Integer, nullable=True)

    # Forward Arbitrage (Long Binance)
    forward_open_price = Column(Float, nullable=True)
    forward_open_sync_count = Column(Integer, nullable=True)
    forward_close_price = Column(Float, nullable=True)
    forward_close_sync_count = Column(Integer, nullable=True)

    # Alert Sound Settings (file paths for uploaded MP3 files)
    single_leg_alert_sound = Column(String, nullable=True)  # Sound for single-leg trading alerts
    single_leg_alert_repeat_count = Column(Integer, nullable=True)  # Number of times to repeat single-leg alert sound
    spread_alert_sound = Column(String, nullable=True)  # Sound for spread alerts
    spread_alert_repeat_count = Column(Integer, nullable=True)  # Number of times to repeat spread alert sound
    net_asset_alert_sound = Column(String, nullable=True)  # Sound for net asset alerts
    net_asset_alert_repeat_count = Column(Integer, nullable=True)  # Number of times to repeat net asset alert sound
    mt5_alert_sound = Column(String, nullable=True)  # Sound for MT5 status alerts
    mt5_alert_repeat_count = Column(Integer, nullable=True)  # Number of times to repeat MT5 alert sound
    liquidation_alert_sound = Column(String, nullable=True)  # Sound for liquidation alerts
    liquidation_alert_repeat_count = Column(Integer, nullable=True)  # Number of times to repeat liquidation alert sound

    create_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    update_time = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="risk_settings")

    def __repr__(self):
        return f"<RiskSettings(user_id={self.user_id}, settings_id={self.settings_id})>"
