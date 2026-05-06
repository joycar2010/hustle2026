from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, ForeignKey, func,
)

from app.db.models import Base


class SSLCertificate(Base):
    __tablename__ = "ssl_certificates"

    id = Column(Integer, primary_key=True)
    cert_name = Column(String(100), nullable=False)
    domain_name = Column(String(200), nullable=False, index=True)
    cert_type = Column(String(20), nullable=False, default="upload")

    cert_content = Column(Text, nullable=False)
    key_content = Column(Text, nullable=False)

    issuer = Column(String(200), nullable=True)
    subject = Column(String(200), nullable=True)
    serial_number = Column(String(100), nullable=True)
    issued_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    status = Column(String(20), nullable=False, default="active")
    is_deployed = Column(Boolean, default=False)
    deploy_path = Column(String(300), nullable=True)
    auto_renew = Column(Boolean, default=False)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SSLCertificateLog(Base):
    __tablename__ = "ssl_certificate_logs"

    id = Column(Integer, primary_key=True)
    certificate_id = Column(Integer, ForeignKey("ssl_certificates.id"), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
