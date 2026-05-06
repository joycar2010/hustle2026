from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, func

from app.db.models import Base


class PendingBlacklist(Base):
    __tablename__ = "pending_blacklist"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)
    reason = Column(String(500), nullable=True)
    source = Column(String(50), default="binance_announcement")
    announcement_title = Column(Text, nullable=True)
    announcement_url = Column(String(500), nullable=True)
    is_confirmed = Column(Boolean, default=False)
    confirmed_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
