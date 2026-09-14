import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models_ssl import SSLCertificate, SSLCertificateLog
from app.db.session import get_db
from app.middleware.permissions import require_admin, get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/ssl/certificates", tags=["admin-ssl"])

SSL_DIR = Path("/etc/ssl/hustle")


class CertUploadRequest(BaseModel):
    cert_name: str
    domain_name: str
    cert_content: str
    key_content: str
    auto_renew: bool = False


def _parse_cert(pem_data: str) -> dict:
    try:
        cert = x509.load_pem_x509_certificate(pem_data.encode())
        issuer = cert.issuer.rfc4514_string()
        subject = cert.subject.rfc4514_string()
        serial = format(cert.serial_number, 'x')
        issued_at = cert.not_valid_before_utc
        expires_at = cert.not_valid_after_utc
        san_domains = []
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            san_domains = san.value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            pass
        return {
            "issuer": issuer,
            "subject": subject,
            "serial_number": serial,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "san_domains": san_domains,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid certificate: {e}")


def _validate_key(key_data: str):
    try:
        serialization.load_pem_private_key(key_data.encode(), password=None)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid private key: {e}")


def _cert_to_dict(cert: SSLCertificate) -> dict:
    days_left = None
    if cert.expires_at:
        delta = cert.expires_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        days_left = max(0, delta.days)
    return {
        "id": cert.id,
        "cert_name": cert.cert_name,
        "domain_name": cert.domain_name,
        "cert_type": cert.cert_type,
        "issuer": cert.issuer,
        "subject": cert.subject,
        "serial_number": cert.serial_number,
        "issued_at": str(cert.issued_at) if cert.issued_at else None,
        "expires_at": str(cert.expires_at) if cert.expires_at else None,
        "days_left": days_left,
        "status": cert.status,
        "is_deployed": cert.is_deployed,
        "deploy_path": cert.deploy_path,
        "auto_renew": cert.auto_renew,
        "created_at": str(cert.created_at) if cert.created_at else None,
    }


def _add_log(db: Session, cert_id: int, action: str, details: str = ""):
    log = SSLCertificateLog(certificate_id=cert_id, action=action, details=details)
    db.add(log)


@router.get("")
def list_certificates(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    certs = db.query(SSLCertificate).order_by(SSLCertificate.id.desc()).all()
    return [_cert_to_dict(c) for c in certs]


@router.post("")
def upload_certificate(data: CertUploadRequest, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    user_id = get_current_user_id(request)

    parsed = _parse_cert(data.cert_content)
    _validate_key(data.key_content)

    cert = SSLCertificate(
        cert_name=data.cert_name,
        domain_name=data.domain_name,
        cert_type="upload",
        cert_content=data.cert_content,
        key_content=data.key_content,
        issuer=parsed["issuer"],
        subject=parsed["subject"],
        serial_number=parsed["serial_number"],
        issued_at=parsed["issued_at"],
        expires_at=parsed["expires_at"],
        auto_renew=data.auto_renew,
        created_by=user_id,
    )
    db.add(cert)
    db.flush()
    _add_log(db, cert.id, "upload", f"Uploaded by user {user_id}")
    db.commit()
    db.refresh(cert)
    return _cert_to_dict(cert)


@router.post("/scan-letsencrypt")
def scan_letsencrypt(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    user_id = get_current_user_id(request)

    le_dir = Path("/etc/letsencrypt/live")
    if not le_dir.exists():
        return {"scanned": 0, "added": 0, "domains": []}

    added_domains = []
    for domain_dir in le_dir.iterdir():
        if not domain_dir.is_dir():
            continue
        cert_file = domain_dir / "fullchain.pem"
        key_file = domain_dir / "privkey.pem"
        if not cert_file.exists() or not key_file.exists():
            continue

        try:
            cert_content = cert_file.read_text()
            key_content = key_file.read_text()
            parsed = _parse_cert(cert_content)

            domains_to_add = parsed.get("san_domains", []) or [domain_dir.name]

            for domain in domains_to_add:
                existing = db.query(SSLCertificate).filter(
                    SSLCertificate.domain_name == domain,
                    SSLCertificate.cert_type == "letsencrypt",
                ).first()
                if existing:
                    continue

                cert = SSLCertificate(
                    cert_name=f"LE-{domain}",
                    domain_name=domain,
                    cert_type="letsencrypt",
                    cert_content=cert_content,
                    key_content=key_content,
                    issuer=parsed["issuer"],
                    subject=parsed["subject"],
                    serial_number=parsed.get("serial_number"),
                    issued_at=parsed["issued_at"],
                    expires_at=parsed["expires_at"],
                    is_deployed=True,
                    deploy_path=str(cert_file),
                    status="active",
                    auto_renew=True,
                    created_by=user_id,
                )
                db.add(cert)
                db.flush()
                _add_log(db, cert.id, "scan_import", f"Imported from {cert_file} (SAN: {domain})")
                added_domains.append(domain)
        except Exception as e:
            logger.warning(f"Failed to import cert for {domain_dir.name}: {e}")

    db.commit()
    return {"scanned": len(list(le_dir.iterdir())), "added": len(added_domains), "domains": added_domains}


@router.get("/{cert_id}")
def get_certificate(cert_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    cert = db.query(SSLCertificate).filter(SSLCertificate.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return _cert_to_dict(cert)


@router.delete("/{cert_id}")
def delete_certificate(cert_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    cert = db.query(SSLCertificate).filter(SSLCertificate.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if cert.is_deployed:
        raise HTTPException(status_code=400, detail="Cannot delete deployed certificate. Undeploy first.")
    db.delete(cert)
    db.commit()
    return {"message": f"Certificate {cert.cert_name} deleted"}


@router.post("/{cert_id}/deploy")
def deploy_certificate(cert_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    cert = db.query(SSLCertificate).filter(SSLCertificate.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    try:
        SSL_DIR.mkdir(parents=True, exist_ok=True)

        safe_name = cert.domain_name.replace("*", "wildcard").replace(" ", "_")
        cert_path = SSL_DIR / f"{safe_name}.crt"
        key_path = SSL_DIR / f"{safe_name}.key"

        cert_path.write_text(cert.cert_content)
        key_path.write_text(cert.key_content)
        key_path.chmod(0o600)

        cert.is_deployed = True
        cert.deploy_path = str(cert_path)
        cert.status = "active"
        _add_log(db, cert.id, "deploy", f"Deployed to {cert_path}")

        try:
            subprocess.run(["nginx", "-t"], check=True, capture_output=True, timeout=10)
            subprocess.run(["systemctl", "reload", "nginx"], check=True, capture_output=True, timeout=10)
            _add_log(db, cert.id, "nginx_reload", "Nginx reloaded successfully")
        except Exception as e:
            _add_log(db, cert.id, "nginx_reload_failed", str(e))

        db.commit()
        return {"message": f"Certificate deployed to {cert_path}"}
    except Exception as e:
        _add_log(db, cert.id, "deploy_failed", str(e))
        db.commit()
        raise HTTPException(status_code=500, detail=f"Deploy failed: {e}")


@router.get("/{cert_id}/status")
def check_certificate_status(cert_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    cert = db.query(SSLCertificate).filter(SSLCertificate.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    now = datetime.now(timezone.utc)
    if cert.expires_at:
        expires = cert.expires_at.replace(tzinfo=timezone.utc)
        days_left = (expires - now).days
        if days_left < 0:
            status = "expired"
        elif days_left < 7:
            status = "critical"
        elif days_left < 30:
            status = "warning"
        else:
            status = "ok"
    else:
        days_left = None
        status = "unknown"

    return {
        "id": cert.id,
        "domain_name": cert.domain_name,
        "status": status,
        "days_left": days_left,
        "is_deployed": cert.is_deployed,
        "expires_at": str(cert.expires_at) if cert.expires_at else None,
    }


@router.get("/{cert_id}/logs")
def get_certificate_logs(cert_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    cert = db.query(SSLCertificate).filter(SSLCertificate.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    logs = db.query(SSLCertificateLog).filter(
        SSLCertificateLog.certificate_id == cert_id,
    ).order_by(SSLCertificateLog.id.desc()).limit(50).all()

    return [
        {
            "id": log.id,
            "action": log.action,
            "details": log.details,
            "created_at": str(log.created_at) if log.created_at else None,
        }
        for log in logs
    ]
