from sqlalchemy import Column, SmallInteger, String
from sqlalchemy.orm import relationship
from ..core.database import Base

class Platform(Base):
    __tablename__ = "platforms"

    platform_id = Column(SmallInteger, primary_key=True, index=True)
    platform_name = Column(String(20), nullable=False)
    api_base_url = Column(String(100), nullable=False)
    ws_base_url = Column(String(100), nullable=False)
    account_api_type = Column(String(30), nullable=False)
    market_api_type = Column(String(30), nullable=False)

    # Relationships
    accounts = relationship("Account", back_populates="platform")
