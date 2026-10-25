import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.db.models_auth import AuditLog
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

AUDIT_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if request.method in AUDIT_METHODS and request.url.path.startswith("/api"):
            try:
                user = getattr(request.state, "user", None)
                user_id = getattr(request.state, "user_id", None)
                ip = request.client.host if request.client else None
                # 处理器可在 request.state.audit_details 写入字段级 before/after diff(JSON)
                details = getattr(request.state, "audit_details", None)
                db = SessionLocal()
                try:
                    log = AuditLog(
                        user=user,
                        user_id=user_id,
                        action=request.method,
                        resource=request.url.path,
                        ip_address=ip,
                        details=details,
                    )
                    db.add(log)
                    db.commit()
                finally:
                    db.close()
            except Exception as e:
                logger.warning(f"Audit log failed: {e}")

        return response
