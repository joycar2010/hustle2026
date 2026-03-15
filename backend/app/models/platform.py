from sqlalchemy import Column, String, SmallInteger
from sqlalchemy.orm import relationship
from app.core.database import Base


class Platform(Base):
    """Platform configuration model for Binance and Bybit"""

    __tablename__ = "platforms"

    platform_id = Column(SmallInteger, primary_key=True)
    platform_name = Column(String(20), nullable=False)
    api_base_url = Column(String(100), nullable=False)
    ws_base_url = Column(String(100), nullable=False)
    account_api_type = Column(String(30), nullable=False)  # binance_futures, bybit_v5
    market_api_type = Column(String(30), nullable=False)  # binance_futures, bybit_mt5

    # Relationships
    accounts = relationship("Account", back_populates="platform")

    def __repr__(self):
        return f"<Platform(platform_id={self.platform_id}, name={self.platform_name})>"
