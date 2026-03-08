"""Notification configuration models"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class NotificationConfig(Base):
    """Notification service configuration"""

    __tablename__ = "notification_configs"

    config_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_type = Column(String(50), nullable=False, unique=True)  # email, sms, feishu
    is_enabled = Column(Boolean, default=False, nullable=False)
    config_data = Column(JSON, nullable=False)  # Service-specific configuration
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<NotificationConfig(type={self.service_type}, enabled={self.is_enabled})>"


class NotificationTemplate(Base):
    """Notification message templates"""

    __tablename__ = "notification_templates"

    template_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_key = Column(String(100), nullable=False, unique=True)  # trade_executed, balance_alert, etc.
    template_name = Column(String(200), nullable=False)
    category = Column(String(50), nullable=False)  # trading, risk, system

    # 生鲜商品配送语模板（规避敏感词）
    title_template = Column(String(500), nullable=False)
    content_template = Column(Text, nullable=False)

    # 通知渠道配置
    enable_email = Column(Boolean, default=False)
    enable_sms = Column(Boolean, default=False)
    enable_feishu = Column(Boolean, default=False)

    # 优先级和频率控制
    priority = Column(Integer, default=1)  # 1=low, 2=medium, 3=high, 4=urgent
    cooldown_seconds = Column(Integer, default=0)  # 冷却时间，防止频繁通知

    # 声音提醒设置
    alert_sound = Column(String(500), nullable=True)  # 提醒声音文件路径（旧字段，保留兼容）
    repeat_count = Column(Integer, default=3)  # 声音重复次数（旧字段，保留兼容）

    # 前端弹窗配置（新字段）
    popup_title_template = Column(Text, nullable=True)  # 前端弹窗标题模板
    popup_content_template = Column(Text, nullable=True)  # 前端弹窗内容模板
    alert_sound_file = Column(String(500), nullable=True)  # 提醒音频文件路径
    alert_sound_repeat = Column(Integer, default=3)  # 音频重复次数

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<NotificationTemplate(key={self.template_key}, name={self.template_name})>"


class NotificationLog(Base):
    """Notification sending log"""

    __tablename__ = "notification_logs"

    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True)  # Null for system-wide notifications
    template_key = Column(String(100), nullable=False)
    service_type = Column(String(50), nullable=False)  # email, sms, feishu
    recipient = Column(String(500), nullable=False)  # Email, phone, or Feishu user ID
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(50), nullable=False)  # pending, sent, failed
    error_message = Column(Text, nullable=True)
    sent_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<NotificationLog(template={self.template_key}, status={self.status})>"
