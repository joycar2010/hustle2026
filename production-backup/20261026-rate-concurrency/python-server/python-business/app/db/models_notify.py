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
    # Optional voice persona used by the notification centre.  ``sound_key``
    # remains the legacy WebAudio cue (ding/alert/...), so existing workers
    # and browsers continue to understand old payloads while the new Chinese
    # female TTS metadata travels alongside it.
    sound_persona_key = Column(String(40), nullable=True)
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


class NotificationMaintenance(Base):
    """Singleton website-maintenance state owned by the coin admin centre.

    The row is deliberately separate from trading positions/rules.  Enabling
    maintenance only changes admission gates and user-facing announcements;
    existing positions remain available for reduce/close/repay workflows.
    """

    __tablename__ = "notification_maintenance"

    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    stop_strategy = Column(Boolean, nullable=False, default=True, server_default="true")
    block_trading = Column(Boolean, nullable=False, default=True, server_default="true")
    block_login = Column(Boolean, nullable=False, default=False, server_default="false")
    title = Column(String(120), nullable=False, default="系统维护中", server_default="系统维护中")
    content = Column(Text, nullable=False, default="", server_default="")
    until_at = Column(DateTime(timezone=True), nullable=True)
    updated_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NotificationSoundPersona(Base):
    """Configurable Chinese female voice profile used by notification TTS."""

    __tablename__ = "notification_sound_personas"

    id = Column(Integer, primary_key=True)
    # ``skey`` matches the MIX notification contract and is what templates
    # persist.  It is unique so a rename cannot silently duplicate a voice.
    skey = Column(String(40), nullable=False, unique=True)
    name = Column(String(60), nullable=False, default="")
    voice = Column(String(80), nullable=False, default="zh-CN-XiaoxiaoNeural")
    style = Column(String(120), nullable=False, default="")
    rate_pct = Column(Integer, nullable=False, default=0)
    pitch_pct = Column(Integer, nullable=False, default=0)
    sample = Column(String(300), nullable=False, default="")
    is_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    updated_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# Short alias used by a few integrations and by the MIX naming convention.
SoundPersona = NotificationSoundPersona
