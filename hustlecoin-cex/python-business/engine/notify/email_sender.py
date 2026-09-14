import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.db.models_notify import EmailConfig
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self):
        self._config: dict | None = None
        self._last_reload = 0

    def _ensure_config(self):
        import time
        now = time.time()
        if self._config and now - self._last_reload < 300:
            return
        db = SessionLocal()
        try:
            cfg = db.query(EmailConfig).first()
            if cfg and cfg.is_enabled and cfg.smtp_host:
                self._config = {
                    "host": cfg.smtp_host,
                    "port": cfg.smtp_port,
                    "user": cfg.smtp_user,
                    "password": cfg.smtp_password,
                    "from_addr": cfg.smtp_from or cfg.smtp_user,
                    "use_ssl": cfg.use_ssl,
                }
            else:
                self._config = None
            self._last_reload = now
        finally:
            db.close()

    def send(self, to: str, subject: str, body: str) -> bool:
        self._ensure_config()
        if not self._config:
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._config["from_addr"]
        msg["To"] = to
        msg.attach(MIMEText(body, "plain", "utf-8"))

        try:
            if self._config["use_ssl"]:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(self._config["host"], self._config["port"], context=ctx, timeout=15) as s:
                    s.login(self._config["user"], self._config["password"])
                    s.send_message(msg)
            else:
                with smtplib.SMTP(self._config["host"], self._config["port"], timeout=15) as s:
                    s.starttls()
                    s.login(self._config["user"], self._config["password"])
                    s.send_message(msg)
            return True
        except Exception as e:
            logger.warning(f"Email send failed: {e}")
            return False


email_sender = EmailSender()
