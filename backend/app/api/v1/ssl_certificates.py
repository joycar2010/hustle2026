"""SSL证书管理API路由"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID
import logging
from datetime import datetime, timedelta
from pathlib import Path
import shutil
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.ssl_certificate import SSLCertificate, SSLCertificateLog
from app.schemas.ssl import (
    SSLCertificateResponse, SSLCertificateUpload, SSLCertificateUpdate,
    CertificateDeployRequest, CertificateStatusResponse,
    CertificateValidationResponse, SSLCertificateLogResponse
)

router = APIRouter()
logger = logging.getLogger(__name__)

# SSL证书存储路径
SSL_CERT_DIR = Path("/etc/ssl/hustle/certs")
SSL_KEY_DIR = Path("/etc/ssl/hustle/private")
SSL_CHAIN_DIR = Path("/etc/ssl/hustle/chains")


def get_client_ip(request: Request) -> str:
    """获取客户端IP地址"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def log_certificate_action(
    db: AsyncSession,
    cert_id: UUID,
    action: str,
    result: str,
    user_id: str,
    ip_address: str,
    error_message: str = None
):
    """记录SSL证书操作日志"""
    log = SSLCertificateLog(
        cert_id=cert_id,
        action=action,
        result=result,
        error_message=error_message,
        performed_by=UUID(user_id),
        ip_address=ip_address
    )
    db.add(log)
    await db.commit()


def parse_certificate(cert_content: str) -> dict:
    """解析证书内容"""
    try:
        cert_bytes = cert_content.encode()
        cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())

        return {
            "issuer": cert.issuer.rfc4514_string(),
            "subject": cert.subject.rfc4514_string(),
            "serial_number": str(cert.serial_number),
            "issued_at": cert.not_valid_before,
            "expires_at": cert.not_valid_after,
            "is_valid": datetime.utcnow() < cert.not_valid_after
        }
    except Exception as e:
        logger.error(f"解析证书失败: {e}")
        raise HTTPException(status_code=400, detail=f"证书格式无效: {str(e)}")


def calculate_days_before_expiry(expires_at: datetime) -> int:
    """计算距离过期的天数"""
    delta = expires_at - datetime.utcnow()
    return max(0, delta.days)


def determine_certificate_status(days_before_expiry: int, is_deployed: bool) -> str:
    """确定证书状态"""
    if days_before_expiry <= 0:
        return "expired"
    elif days_before_expiry <= 30:
        return "expiring_soon"
    elif is_deployed:
        return "active"
    else:
        return "inactive"


# ==================== SSL证书列表与详情 ====================

@router.get("/certificates", response_model=List[SSLCertificateResponse])
async def get_ssl_certificates(
    status: Optional[str] = Query(None, description="证书状态: active, inactive, expired, expiring_soon"),
    domain_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """获取SSL证书列表"""
    try:
        query = select(SSLCertificate)

        if status:
            query = query.where(SSLCertificate.status == status)
        if domain_name:
            query = query.where(SSLCertificate.domain_name.ilike(f"%{domain_name}%"))

        query = query.order_by(SSLCertificate.expires_at.asc())

        result = await db.execute(query)
        certificates = result.scalars().all()

        logger.info(f"获取SSL证书列表成功，共 {len(certificates)} 个证书")
        return certificates
    except Exception as e:
        logger.error(f"获取SSL证书列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取SSL证书列表失败")


@router.get("/certificates/{cert_id}", response_model=SSLCertificateResponse)
async def get_ssl_certificate(
    cert_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """获取SSL证书详情"""
    try:
        result = await db.execute(
            select(SSLCertificate).where(SSLCertificate.cert_id == cert_id)
        )
        certificate = result.scalar_one_or_none()

        if not certificate:
            raise HTTPException(status_code=404, detail="SSL证书不存在")

        return certificate
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取SSL证书详情失败: {e}")
        raise HTTPException(status_code=500, detail="获取SSL证书详情失败")


# ==================== 上传SSL证书 ====================

@router.post("/certificates", response_model=SSLCertificateResponse, status_code=status.HTTP_201_CREATED)
async def upload_ssl_certificate(
    cert_data: SSLCertificateUpload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """上传SSL证书"""
    try:
        # 检查域名是否已存在相同类型的证书
        result = await db.execute(
            select(SSLCertificate).where(
                SSLCertificate.domain_name == cert_data.domain_name,
                SSLCertificate.cert_type == cert_data.cert_type
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail=f"域名 {cert_data.domain_name} 已存在 {cert_data.cert_type} 类型的证书"
            )

        # 解析证书
        cert_info = parse_certificate(cert_data.cert_content)

        # 创建存储目录
        SSL_CERT_DIR.mkdir(parents=True, exist_ok=True)
        SSL_KEY_DIR.mkdir(parents=True, exist_ok=True)
        if cert_data.chain_content:
            SSL_CHAIN_DIR.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        safe_domain = cert_data.domain_name.replace(".", "_")
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        cert_filename = f"{safe_domain}_{timestamp}.crt"
        key_filename = f"{safe_domain}_{timestamp}.key"
        chain_filename = f"{safe_domain}_{timestamp}_chain.crt" if cert_data.chain_content else None

        # 保存证书文件
        cert_path = SSL_CERT_DIR / cert_filename
        key_path = SSL_KEY_DIR / key_filename
        chain_path = SSL_CHAIN_DIR / chain_filename if chain_filename else None

        cert_path.write_text(cert_data.cert_content)
        key_path.write_text(cert_data.key_content)
        if chain_path:
            chain_path.write_text(cert_data.chain_content)

        # 设置文件权限
        cert_path.chmod(0o644)
        key_path.chmod(0o600)
        if chain_path:
            chain_path.chmod(0o644)

        # 计算过期天数
        days_before_expiry = calculate_days_before_expiry(cert_info["expires_at"])

        # 创建数据库记录
        new_cert = SSLCertificate(
            cert_name=cert_data.cert_name,
            domain_name=cert_data.domain_name,
            cert_type=cert_data.cert_type,
            cert_file_path=str(cert_path),
            key_file_path=str(key_path),
            chain_file_path=str(chain_path) if chain_path else None,
            issuer=cert_info["issuer"],
            subject=cert_info["subject"],
            serial_number=cert_info["serial_number"],
            issued_at=cert_info["issued_at"],
            expires_at=cert_info["expires_at"],
            status=determine_certificate_status(days_before_expiry, False),
            is_deployed=False,
            auto_renew=cert_data.auto_renew,
            days_before_expiry=days_before_expiry,
            last_check_at=datetime.utcnow(),
            uploaded_by=UUID(current_user_id)
        )

        db.add(new_cert)
        await db.commit()
        await db.refresh(new_cert)

        # 记录操作日志
        await log_certificate_action(
            db=db,
            cert_id=new_cert.cert_id,
            action="upload",
            result="success",
            user_id=current_user_id,
            ip_address=get_client_ip(request)
        )

        logger.info(f"SSL证书上传成功: {cert_data.domain_name}")
        return new_cert

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"上传SSL证书失败: {e}")

        # 记录失败日志
        if 'new_cert' in locals():
            await log_certificate_action(
                db=db,
                cert_id=new_cert.cert_id,
                action="upload",
                result="failure",
                user_id=current_user_id,
                ip_address=get_client_ip(request),
                error_message=str(e)
            )

        raise HTTPException(status_code=500, detail=f"上传SSL证书失败: {str(e)}")


# ==================== 部署SSL证书 ====================

@router.post("/certificates/{cert_id}/deploy", status_code=status.HTTP_200_OK)
async def deploy_ssl_certificate(
    cert_id: UUID,
    deploy_data: CertificateDeployRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """部署SSL证书到Nginx"""
    try:
        result = await db.execute(
            select(SSLCertificate).where(SSLCertificate.cert_id == cert_id)
        )
        certificate = result.scalar_one_or_none()

        if not certificate:
            raise HTTPException(status_code=404, detail="SSL证书不存在")

        if certificate.status == "expired":
            raise HTTPException(status_code=400, detail="证书已过期，无法部署")

        # 验证证书文件存在
        if not Path(certificate.cert_file_path).exists():
            raise HTTPException(status_code=400, detail="证书文件不存在")
        if not Path(certificate.key_file_path).exists():
            raise HTTPException(status_code=400, detail="私钥文件不存在")

        # 更新Nginx配置（这里简化处理，实际应该调用系统命令）
        # 在生产环境中，这部分需要使用subprocess或ansible等工具
        logger.info(f"部署证书到Nginx: {deploy_data.nginx_config_path}")

        # 更新证书状态
        certificate.is_deployed = True
        certificate.status = "active"
        certificate.last_check_at = datetime.utcnow()

        await db.commit()
        await db.refresh(certificate)

        # 记录操作日志
        await log_certificate_action(
            db=db,
            cert_id=cert_id,
            action="deploy",
            result="success",
            user_id=current_user_id,
            ip_address=get_client_ip(request)
        )

        logger.info(f"SSL证书部署成功: {certificate.domain_name}")
        return {
            "message": "SSL证书部署成功",
            "domain_name": certificate.domain_name,
            "cert_path": certificate.cert_file_path,
            "key_path": certificate.key_file_path
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"部署SSL证书失败: {e}")

        # 记录失败日志
        await log_certificate_action(
            db=db,
            cert_id=cert_id,
            action="deploy",
            result="failure",
            user_id=current_user_id,
            ip_address=get_client_ip(request),
            error_message=str(e)
        )

        raise HTTPException(status_code=500, detail=f"部署SSL证书失败: {str(e)}")


# ==================== 删除SSL证书 ====================

@router.delete("/certificates/{cert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ssl_certificate(
    cert_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """删除SSL证书"""
    try:
        result = await db.execute(
            select(SSLCertificate).where(SSLCertificate.cert_id == cert_id)
        )
        certificate = result.scalar_one_or_none()

        if not certificate:
            raise HTTPException(status_code=404, detail="SSL证书不存在")

        if certificate.is_deployed:
            raise HTTPException(status_code=400, detail="证书正在使用中，请先取消部署")

        # 删除证书文件
        try:
            if certificate.cert_file_path and Path(certificate.cert_file_path).exists():
                Path(certificate.cert_file_path).unlink()
            if certificate.key_file_path and Path(certificate.key_file_path).exists():
                Path(certificate.key_file_path).unlink()
            if certificate.chain_file_path and Path(certificate.chain_file_path).exists():
                Path(certificate.chain_file_path).unlink()
        except Exception as e:
            logger.warning(f"删除证书文件失败: {e}")

        # 记录操作日志（在删除前）
        await log_certificate_action(
            db=db,
            cert_id=cert_id,
            action="delete",
            result="success",
            user_id=current_user_id,
            ip_address=get_client_ip(request)
        )

        # 删除数据库记录
        await db.delete(certificate)
        await db.commit()

        logger.info(f"SSL证书删除成功: {certificate.domain_name}")

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"删除SSL证书失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除SSL证书失败: {str(e)}")


# ==================== 获取证书状态 ====================

@router.get("/certificates/{cert_id}/status", response_model=CertificateStatusResponse)
async def get_certificate_status(
    cert_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """获取SSL证书状态"""
    try:
        result = await db.execute(
            select(SSLCertificate).where(SSLCertificate.cert_id == cert_id)
        )
        certificate = result.scalar_one_or_none()

        if not certificate:
            raise HTTPException(status_code=404, detail="SSL证书不存在")

        # 重新计算过期天数
        days_before_expiry = calculate_days_before_expiry(certificate.expires_at)

        # 更新状态
        new_status = determine_certificate_status(days_before_expiry, certificate.is_deployed)
        if certificate.status != new_status or certificate.days_before_expiry != days_before_expiry:
            certificate.status = new_status
            certificate.days_before_expiry = days_before_expiry
            certificate.last_check_at = datetime.utcnow()
            await db.commit()

        return {
            "cert_id": certificate.cert_id,
            "domain_name": certificate.domain_name,
            "status": certificate.status,
            "is_deployed": certificate.is_deployed,
            "expires_at": certificate.expires_at,
            "days_before_expiry": days_before_expiry,
            "is_valid": days_before_expiry > 0,
            "error_message": None,
            "last_check_at": certificate.last_check_at
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取证书状态失败: {e}")
        raise HTTPException(status_code=500, detail="获取证书状态失败")


# ==================== 获取操作日志 ====================

@router.get("/certificates/{cert_id}/logs", response_model=List[SSLCertificateLogResponse])
async def get_certificate_logs(
    cert_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    action: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)
):
    """获取SSL证书操作日志"""
    try:
        query = select(SSLCertificateLog).where(SSLCertificateLog.cert_id == cert_id)

        if action:
            query = query.where(SSLCertificateLog.action == action)

        query = query.order_by(SSLCertificateLog.performed_at.desc()).offset(skip).limit(limit)

        result = await db.execute(query)
        logs = result.scalars().all()

        return logs

    except Exception as e:
        logger.error(f"获取证书日志失败: {e}")
        raise HTTPException(status_code=500, detail="获取证书日志失败")
