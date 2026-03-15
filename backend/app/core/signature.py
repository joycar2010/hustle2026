"""Request signature verification middleware"""
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import hmac
import hashlib
import time
from typing import Optional


class RequestSignatureMiddleware(BaseHTTPMiddleware):
    """Middleware to verify request signatures and prevent replay attacks"""

    def __init__(self, app, secret_key: str, enabled: bool = True):
        super().__init__(app)
        self.secret_key = secret_key
        self.enabled = enabled
        self.max_timestamp_diff = 300  # 5 minutes
        self.nonce_cache = set()  # Simple in-memory cache (use Redis in production)
        self.safe_paths = ["/docs", "/redoc", "/openapi.json", "/health", "/api/v1/auth/login"]

    async def dispatch(self, request: Request, call_next):
        """Verify request signature"""
        if not self.enabled:
            return await call_next(request)

        # Skip signature check for safe paths
        if any(request.url.path.startswith(path) for path in self.safe_paths):
            return await call_next(request)

        # Get signature headers
        timestamp = request.headers.get("X-Timestamp")
        nonce = request.headers.get("X-Nonce")
        signature = request.headers.get("X-Signature")

        if not all([timestamp, nonce, signature]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing signature headers (X-Timestamp, X-Nonce, X-Signature)"
            )

        # Verify timestamp (prevent replay attacks)
        try:
            request_time = int(timestamp)
            current_time = int(time.time())
            if abs(current_time - request_time) > self.max_timestamp_diff:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Request timestamp expired"
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid timestamp format"
            )

        # Verify nonce (prevent replay attacks)
        if nonce in self.nonce_cache:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Nonce already used (replay attack detected)"
            )

        # Read request body
        body = await request.body()

        # Calculate expected signature
        message = f"{request.method}:{request.url.path}:{timestamp}:{nonce}:{body.decode()}"
        expected_signature = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        # Verify signature
        if not hmac.compare_digest(signature, expected_signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid request signature"
            )

        # Add nonce to cache
        self.nonce_cache.add(nonce)

        # Clean old nonces (simple implementation)
        if len(self.nonce_cache) > 10000:
            self.nonce_cache.clear()

        # Continue with request
        return await call_next(request)


def generate_request_signature(
    method: str,
    path: str,
    body: str,
    secret_key: str,
    timestamp: Optional[int] = None,
    nonce: Optional[str] = None
) -> dict:
    """
    Generate request signature headers

    Returns:
        dict with X-Timestamp, X-Nonce, X-Signature headers
    """
    import secrets

    if timestamp is None:
        timestamp = int(time.time())
    if nonce is None:
        nonce = secrets.token_urlsafe(16)

    message = f"{method}:{path}:{timestamp}:{nonce}:{body}"
    signature = hmac.new(
        secret_key.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    return {
        "X-Timestamp": str(timestamp),
        "X-Nonce": nonce,
        "X-Signature": signature
    }
