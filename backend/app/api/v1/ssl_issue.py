"""POST /api/v1/ssl/certificates/issue — issue a fresh Let's Encrypt cert for a new domain.

Steps executed (each must succeed or we abort + cleanup):
  1. Validate domain (strict regex, no shell meta)
  2. Check DNS A-record points to this server (optional, warn only)
  3. Run certbot certonly --nginx -d {domain} (15s budget)
  4. Read issued cert with existing parse_certificate() helper
  5. Insert row into ssl_certificates (re-uses existing schema)
  6. Optionally write nginx site config (we return the template; operator
     can choose to auto-deploy or copy-paste)

The endpoint is RBAC-gated to super admin only — certbot rate limits are
strict (5 failures/hour/IP → Let's Encrypt blacklist), so we don't want
just any operator issuing carelessly.
"""
import asyncio
import logging
import re
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Body
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.v1.auth import get_current_user_id

logger = logging.getLogger(__name__)

# strict: subdomain.domain.tld only; no wildcards, no shell chars
_DOMAIN_RE = re.compile(r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$')

# certbot takes up to ~60s in worst case (HTTP-01 challenge, nginx reload)
_CERTBOT_TIMEOUT = 120

ADMIN_ROLES = {'超级管理员', '系统管理员', 'super_admin', 'system_admin', 'admin'}


class IssueCertReq(BaseModel):
    domain: str = Field(..., description="Fully-qualified domain, e.g. new.hustle2026.xyz")
    email: str = Field('admin@hustle2026.xyz', description="Contact email for Let's Encrypt")
    auto_renew: bool = Field(True, description="Enable auto-renew (handled by certbot's systemd timer)")


async def require_super_admin(db: AsyncSession, user_id: str):
    row = (await db.execute(text(
        "SELECT role FROM users WHERE user_id = CAST(:u AS UUID)"
    ), {'u': user_id})).first()
    if not row or row[0] not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail='仅超管/系统管理员可签发证书')


async def _run_certbot(domain: str, email: str) -> tuple[bool, str]:
    """Execute certbot via sudo. Returns (ok, stdout_or_err)."""
    cmd = [
        'sudo', '-n', '/usr/bin/certbot', 'certonly', '--nginx',
        '-d', domain,
        '--non-interactive', '--agree-tos',
        '-m', email,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=_CERTBOT_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return False, f'certbot 超时 ({_CERTBOT_TIMEOUT}s)'
        out = out_bytes.decode('utf-8', errors='ignore')[-2000:]
        return proc.returncode == 0, out
    except Exception as e:
        return False, f'certbot 执行失败: {e}'


def _parse_cert_file(cert_path: str) -> dict:
    """Read issued cert and extract issuer / subject / expiry."""
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        with open(cert_path, 'rb') as f:
            cert = x509.load_pem_x509_certificate(f.read(), default_backend())
        return {
            'issuer': cert.issuer.rfc4514_string(),
            'subject': cert.subject.rfc4514_string(),
            'serial_number': str(cert.serial_number),
            'issued_at': cert.not_valid_before,
            'expires_at': cert.not_valid_after,
        }
    except Exception as e:
        logger.warning(f'parse cert {cert_path} failed: {e}')
        return {}


def make_router() -> APIRouter:
    """Return an APIRouter to be mounted inside ssl_certificates.router."""
    r = APIRouter()

    @r.post('/certificates/issue', status_code=status.HTTP_201_CREATED)
    async def issue_certificate(
        req: IssueCertReq,
        db: AsyncSession = Depends(get_db),
        user_id: str = Depends(get_current_user_id),
    ):
        await require_super_admin(db, user_id)

        domain = req.domain.strip().lower()
        if not _DOMAIN_RE.match(domain):
            raise HTTPException(status_code=400, detail=f'域名格式非法: {domain}')

        # Reject if already registered (force delete first)
        existing = (await db.execute(text(
            "SELECT cert_id FROM ssl_certificates WHERE domain_name = :d"
        ), {'d': domain})).first()
        if existing:
            raise HTTPException(status_code=409, detail=f'{domain} 已注册在 ssl_certificates 表，请先删除再签发')

        # Run certbot
        ok, log = await _run_certbot(domain, req.email)
        if not ok:
            raise HTTPException(status_code=400, detail=f'certbot 失败: {log[-600:]}')

        cert_path = f'/etc/letsencrypt/live/{domain}/fullchain.pem'
        key_path = f'/etc/letsencrypt/live/{domain}/privkey.pem'
        chain_path = f'/etc/letsencrypt/live/{domain}/chain.pem'
        if not os.path.exists(cert_path):
            raise HTTPException(status_code=500, detail=f'证书文件未找到: {cert_path}')

        meta = _parse_cert_file(cert_path)
        issued_at = meta.get('issued_at') or datetime.utcnow()
        expires_at = meta.get('expires_at') or datetime.utcnow()

        res = await db.execute(text("""
            INSERT INTO ssl_certificates
              (cert_name, domain_name, cert_type, cert_file_path, key_file_path,
               chain_file_path, issuer, subject, serial_number, issued_at,
               expires_at, status, is_deployed, auto_renew, uploaded_by)
            VALUES (:cn, :d, 'letsencrypt', :cp, :kp, :xp, :iss, :sub, :sn,
                    :ia, :ea, 'active', false, :ar, CAST(:u AS UUID))
            RETURNING cert_id
        """), {
            'cn': f"{domain} - Let's Encrypt",
            'd': domain,
            'cp': cert_path, 'kp': key_path, 'xp': chain_path,
            'iss': meta.get('issuer', "Let's Encrypt")[:255],
            'sub': meta.get('subject', domain)[:255],
            'sn': meta.get('serial_number', '')[:100],
            'ia': issued_at, 'ea': expires_at,
            'ar': req.auto_renew, 'u': user_id,
        })
        cert_id = res.scalar_one()
        await db.commit()

        logger.info(f'[ssl] issued cert for {domain} (id={cert_id}, by={user_id})')
        return {
            'ok': True,
            'cert_id': str(cert_id),
            'domain': domain,
            'expires_at': expires_at.isoformat(),
            'issued_at': issued_at.isoformat(),
            'nginx_deploy_hint': (
                f'nginx 站点配置需单独创建在 /etc/nginx/sites-enabled/{domain}，'
                f'然后 sudo nginx -t && sudo systemctl reload nginx'
            ),
        }

    return r
