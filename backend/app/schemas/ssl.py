"""SSL证书相关Pydantic Schemas"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
import re


# ==================== SSL证书 Schemas ====================

class SSLCertificateBase(BaseModel):
    """SSL证书基础Schema"""
    cert_name: str = Field(..., min_length=2, max_length=100, description="证书名称")
    domain_name: str = Field(..., min_length=3, max_length=255, description="域名")
    cert_type: str = Field(..., description="证书类型: self_signed, ca_signed, letsencrypt")
    auto_renew: bool = Field(default=False, description="是否自动续期")

    @field_validator('domain_name')
    @classmethod
    def validate_domain(cls, v: str) -> str:
        """验证域名格式"""
        # 简单的域名格式验证
        pattern = r'^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$|^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'
        if not re.match(pattern, v):
            raise ValueError('Invalid domain name format')
        return v

    @field_validator('cert_type')
    @classmethod
    def validate_cert_type(cls, v: str) -> str:
        """验证证书类型"""
        valid_types = ['self_signed', 'ca_signed', 'letsencrypt']
        if v not in valid_types:
            raise ValueError(f'cert_type must be one of: {", ".join(valid_types)}')
        return v


class SSLCertificateUpload(SSLCertificateBase):
    """上传SSL证书Schema"""
    cert_content: str = Field(..., description="证书文件内容（PEM格式）")
    key_content: str = Field(..., description="私钥文件内容（PEM格式）")
    chain_content: Optional[str] = Field(None, description="证书链文件内容（可选）")


class SSLCertificateUpdate(BaseModel):
    """更新SSL证书Schema"""
    cert_name: Optional[str] = Field(None, min_length=2, max_length=100)
    auto_renew: Optional[bool] = None


class SSLCertificateResponse(SSLCertificateBase):
    """SSL证书响应Schema"""
    cert_id: UUID
    cert_file_path: Optional[str]
    key_file_path: Optional[str]
    chain_file_path: Optional[str]
    issuer: Optional[str]
    subject: Optional[str]
    serial_number: Optional[str]
    issued_at: Optional[datetime]
    expires_at: datetime
    status: str
    is_deployed: bool
    days_before_expiry: Optional[int]
    last_check_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    uploaded_by: Optional[UUID]

    class Config:
        from_attributes = True


# ==================== 证书操作 Schemas ====================

class CertificateDeployRequest(BaseModel):
    """部署证书请求Schema"""
    nginx_config_path: str = Field(
        default="/etc/nginx/sites-available/hustle",
        description="Nginx配置文件路径"
    )
    reload_nginx: bool = Field(default=True, description="是否重启Nginx")
    backup_old_cert: bool = Field(default=True, description="是否备份旧证书")


class CertificateStatusResponse(BaseModel):
    """证书状态响应Schema"""
    cert_id: UUID
    domain_name: str
    status: str
    is_deployed: bool
    expires_at: datetime
    days_before_expiry: int
    is_valid: bool
    error_message: Optional[str]
    last_check_at: datetime


class CertificateRenewRequest(BaseModel):
    """证书续期请求Schema"""
    force_renew: bool = Field(default=False, description="是否强制续期")
    deploy_after_renew: bool = Field(default=True, description="续期后是否自动部署")


# ==================== 证书验证 Schemas ====================

class CertificateValidationResponse(BaseModel):
    """证书验证响应Schema"""
    is_valid: bool
    domain_match: bool
    not_expired: bool
    issuer: Optional[str]
    subject: Optional[str]
    valid_from: Optional[datetime]
    valid_until: Optional[datetime]
    days_remaining: Optional[int]
    errors: list[str] = Field(default_factory=list)


# ==================== 证书日志 Schemas ====================

class SSLCertificateLogResponse(BaseModel):
    """SSL证书日志响应Schema"""
    log_id: UUID
    cert_id: UUID
    action: str
    result: str
    error_message: Optional[str]
    performed_by: Optional[UUID]
    performed_at: datetime
    ip_address: Optional[str]

    class Config:
        from_attributes = True


# ==================== 批量操作 Schemas ====================

class CertificateBatchCheckRequest(BaseModel):
    """批量检查证书请求Schema"""
    cert_ids: list[UUID] = Field(..., min_items=1, description="证书ID列表")


class CertificateBatchCheckResponse(BaseModel):
    """批量检查证书响应Schema"""
    total: int
    expiring_soon: int  # 30天内过期
    expired: int
    valid: int
    certificates: list[CertificateStatusResponse]
