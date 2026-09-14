"""Persistent server-monitor notification subscriptions."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func

from app.db.models import Base


class ServerMonitorSubscription(Base):
    __tablename__ = "server_monitor_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    target = Column(String(32), nullable=False, index=True)  # rust | python
    enabled = Column(Boolean, nullable=False, default=True)
    feishu = Column(Boolean, nullable=False, default=True)
    email = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
