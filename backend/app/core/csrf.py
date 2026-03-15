"""CSRF protection middleware"""
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import secrets
import hashlib
import time
from typing import Optional


class CSRFProtection(BaseHTTPMiddleware):
    """CSRF protection middleware for state-changing operations"""

    def __init__(self, app, secret_key: str):
        super().__init__(app)
        self.secret_key = secret_key
        self.safe_methods = {"GET", "HEAD", "OPTIONS", "TRACE"}

    async def dispatch(self, request: Request, call_next):
        """Check CSRF token for unsafe methods"""
        # Skip CSRF check for safe methods
        if request.method in self.safe_methods:
            response = await call_next(request)
            return response

        # Skip CSRF check for WebSocket and auth endpoints
        if request.url.path.startswith("/ws") or request.url.path.startswith("/api/v1/auth/login"):
            response = await call_next(request)
            return response

        # Verify CSRF token
        csrf_token = request.headers.get("X-CSRF-Token")
        if not csrf_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token missing"
            )

        # Validate token (simple implementation - can be enhanced)
        if not self._validate_token(csrf_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid CSRF token"
            )

        response = await call_next(request)
        return response

    def _validate_token(self, token: str) -> bool:
        """Validate CSRF token"""
        try:
            # Token format: timestamp:hash
            parts = token.split(":")
            if len(parts) != 2:
                return False

            timestamp_str, token_hash = parts
            timestamp = int(timestamp_str)

            # Check if token is not expired (valid for 1 hour)
            current_time = int(time.time())
            if current_time - timestamp > 3600:
                return False

            # Verify hash
            expected_hash = hashlib.sha256(
                f"{timestamp_str}:{self.secret_key}".encode()
            ).hexdigest()

            return token_hash == expected_hash
        except:
            return False


def generate_csrf_token(secret_key: str) -> str:
    """Generate a new CSRF token"""
    timestamp = int(time.time())
    token_hash = hashlib.sha256(
        f"{timestamp}:{secret_key}".encode()
    ).hexdigest()
    return f"{timestamp}:{token_hash}"
