"""Request ID tracking middleware"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import uuid
import logging
import time

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add unique request ID to each request"""

    async def dispatch(self, request: Request, call_next):
        """Add request ID and track request timing"""
        # Generate or use existing request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Add request ID to request state
        request.state.request_id = request_id

        # Track request start time
        start_time = time.time()

        # Log request
        logger.info(
            f"[{request_id}] {request.method} {request.url.path}",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path}
        )

        # Process request
        response = await call_next(request)

        # Calculate request duration
        duration = time.time() - start_time

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        # Log response
        logger.info(
            f"[{request_id}] {response.status_code} - {duration:.3f}s",
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
                "duration": duration
            }
        )

        return response


def get_request_id(request: Request) -> str:
    """Get request ID from request state"""
    return getattr(request.state, "request_id", "unknown")
