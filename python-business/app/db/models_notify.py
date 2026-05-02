from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, func

from app.db.models import Base


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"

    id = Column(Integer, primary_key=True)
    template_name = Column(String(100), nullable=False)
    category = Column(String(30), nullable=False, default="system")
    title_template = Column(String(200), nullable=False, default="")
    content_template = Column(Text, nullable=False, default="")
    enable_feishu = Column(Boolean, default=True)
    enable_email = Column(Boolean, default=False)
    priority = Column(Integer, default=2)
    cooldown_seconds = Column(Integer, default=60)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True)
    template_name = Column(String(100), nullable=True)
    channel = Column(String(30), nullable=False, default="feishu")
    recipient = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="sent")
    content = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
