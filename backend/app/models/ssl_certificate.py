"""SSL证书管理模型"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class SSLCertificate(Base):
    """SSL证书模型"""

    __tablename__ = "ssl_certificates"

    cert_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cert_name = Column(String(100), nullable=False)
    domain_name = Column(String(255), nullable=False, index=True)
    cert_type = Column(String(20), nullable=False)  # self_signed, ca_signed, letsencrypt
    cert_file_path = Column(String(500))
    key_file_path = Column(String(500))
    chain_file_path = Column(String(500))
    issuer = Column(String(255))
    subject = Column(String(255))
    serial_number = Column(String(100))
    issued_at = Column(TIMESTAMP)
    expires_at = Column(TIMESTAMP, nullable=False, index=True)
    status = Column(String(20), default='inactive', index=True)  # active, inactive, expired, expiring_soon
    is_deployed = Column(Boolean, default=False)
    auto_renew = Column(Boolean, default=False)
    days_before_expiry = Column(Integer)
    last_check_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))

    # Relationships
    logs = relationship("SSLCertificateLog", back_populates="certificate", cascade="all, delete-orphan")
    uploader = relationship("User", foreign_keys=[uploaded_by])

    def __repr__(self):
        return f"<SSLCertificate(domain={self.domain_name}, status={self.status})>"


class SSLCertificateLog(Base):
    """SSL证书操作日志模型"""

    __tablename__ = "ssl_certificate_logs"

    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cert_id = Column(UUID(as_uuid=True), ForeignKey("ssl_certificates.cert_id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(50), nullable=False, index=True)  # upload, deploy, renew, revoke, delete
    result = Column(String(20), nullable=False)  # success, failure
    error_message = Column(Text)
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    performed_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)
    ip_address = Column(String(45))

    # Relationships
    certificate = relationship("SSLCertificate", back_populates="logs")
    performer = relationship("User", foreign_keys=[performed_by])

    def __repr__(self):
        return f"<SSLCertificateLog(cert_id={self.cert_id}, action={self.action})>"
