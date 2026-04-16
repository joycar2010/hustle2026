"""
音频文件模型 - 存储上传的音频文件及其飞书file_key
"""
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime
from app.core.database import Base


class AudioFile(Base):
    """音频文件表"""
    __tablename__ = "audio_files"

    file_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_name = Column(String(255), nullable=False, unique=True, comment="文件名")
    file_path = Column(String(500), nullable=False, comment="本地文件路径")
    file_key = Column(String(255), nullable=True, comment="飞书file_key")
    file_size = Column(String(50), nullable=True, comment="文件大小")
    is_synced = Column(Boolean, default=False, comment="是否已同步到飞书")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    synced_at = Column(DateTime, nullable=True, comment="同步到飞书的时间")
