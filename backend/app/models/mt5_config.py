"""MT5 Config model - global key-value configuration for MT5 services"""
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class MT5Config(Base):
    __tablename__ = "mt5_config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    description = Column(String(500))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
