"""SMTP Email Notification Service"""
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)


class EmailService:
    """Send HTML emails via SMTP based on notification_configs settings."""

    async def get_smtp_config(self, db: AsyncSession) -> Optional[dict]:
        from app.models.notification_config import NotificationConfig
        result = await db.execute(
            select(NotificationConfig).where(
                NotificationConfig.service_type == 'email'
            )
        )
        cfg = result.scalar_one_or_none()
        if not cfg or not cfg.is_enabled:
            return None
        data = cfg.config_data or {}
        if not data.get('smtp_host') or not data.get('from_email'):
            return None
        return data

    async def send_email(
        self,
        db: AsyncSession,
        to_addresses: List[str],
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
    ) -> bool:
        """Send email to one or more recipients. Returns True on success."""
        cfg = await self.get_smtp_config(db)
        if not cfg:
            logger.warning('[EmailService] SMTP not configured or not enabled')
            return False

        smtp_host = cfg['smtp_host']
        smtp_port = int(cfg.get('smtp_port', 587))
        username = cfg.get('username', '')
        password = cfg.get('password', '')
        from_email = cfg['from_email']

        if not to_addresses:
            logger.warning('[EmailService] No recipients')
            return False

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = ', '.join(to_addresses)

        if body_text:
            msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        try:
            context = ssl.create_default_context()
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=10) as server:
                    if username and password:
                        server.login(username, password)
                    server.sendmail(from_email, to_addresses, msg.as_string())
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    server.ehlo()
                    if smtp_port != 25:
                        server.starttls(context=context)
                        server.ehlo()
                    if username and password:
                        server.login(username, password)
                    server.sendmail(from_email, to_addresses, msg.as_string())

            logger.info(f'[EmailService] Sent to {to_addresses}: {subject}')
            return True
        except Exception as e:
            logger.error(f'[EmailService] Send failed: {e}')
            return False

    async def send_alert_email(
        self,
        db: AsyncSession,
        to_email: str,
        title: str,
        content: str,
    ) -> bool:
        """Send a formatted alert notification email."""
        html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; background:#0b0e11; color:#e6e6e6; margin:0; padding:20px; }}
  .card {{ background:#1e2329; border:1px solid #2b3139; border-radius:8px; max-width:600px; margin:0 auto; padding:24px; }}
  .title {{ font-size:18px; font-weight:bold; color:#f0b90b; margin-bottom:16px; }}
  .body {{ font-size:14px; line-height:1.7; white-space:pre-line; }}
  .footer {{ font-size:11px; color:#848e9c; margin-top:20px; border-top:1px solid #2b3139; padding-top:12px; }}
</style>
</head>
<body>
  <div class="card">
    <div class="title">{title}</div>
    <div class="body">{content}</div>
    <div class="footer">来自 Hustle XAU 套利系统 — 自动通知</div>
  </div>
</body>
</html>'''
        return await self.send_email(db, [to_email], title, html, content)


email_service = EmailService()
