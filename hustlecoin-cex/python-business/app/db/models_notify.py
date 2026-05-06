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
    enable_marquee = Column(Boolean, default=True)
    priority = Column(Integer, default=2)
    cooldown_seconds = Column(Integer, default=60)
    marquee_color = Column(String(20), default="#3b82f6")
    marquee_blink = Column(Boolean, default=False)
    sound_key = Column(String(30), default="none")
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


class EmailConfig(Base):
    __tablename__ = "email_config"

    id = Column(Integer, primary_key=True)
    smtp_host = Column(String(200), default="")
    smtp_port = Column(Integer, default=465)
    smtp_user = Column(String(200), default="")
    smtp_password = Column(String(200), default="")
    smtp_from = Column(String(200), default="")
    use_ssl = Column(Boolean, default=True)
    is_enabled = Column(Boolean, default=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
