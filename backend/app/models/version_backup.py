"""版本备份模型"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class VersionBackup(Base):
    """版本备份模型"""

    __tablename__ = "version_backups"

    backup_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    backup_filename = Column(String(255), nullable=False, unique=True, index=True)
    timestamp = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)
    description = Column(Text)
    status = Column(String(20), nullable=False, default='completed')  # pending, completed, failed

    def __repr__(self):
        return f"<VersionBackup(backup_id={self.backup_id}, filename={self.backup_filename}, status={self.status})>"
