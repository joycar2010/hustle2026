"""IP whitelist middleware"""
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from typing import List, Set
import ipaddress
import logging

logger = logging.getLogger(__name__)


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """Middleware to restrict access by IP address"""

    def __init__(
        self,
        app,
        whitelist: List[str] = None,
        enabled: bool = False,
        admin_paths: List[str] = None
    ):
        super().__init__(app)
        self.enabled = enabled
        self.whitelist: Set[str] = set(whitelist or [])
        self.admin_paths = admin_paths or ["/api/v1/users", "/api/v1/system"]

        # Parse CIDR ranges
        self.ip_networks = []
        for ip_str in self.whitelist:
            try:
                self.ip_networks.append(ipaddress.ip_network(ip_str, strict=False))
            except ValueError:
                logger.warning(f"Invalid IP address or CIDR range: {ip_str}")

    async def dispatch(self, request: Request, call_next):
        """Check if client IP is whitelisted"""
        if not self.enabled:
            return await call_next(request)

        # Get client IP
        client_ip = self._get_client_ip(request)

        # Check if path requires IP whitelist
        requires_whitelist = any(
            request.url.path.startswith(path) for path in self.admin_paths
        )

        if requires_whitelist:
            if not self._is_ip_allowed(client_ip):
                logger.warning(f"Blocked request from unauthorized IP: {client_ip} to {request.url.path}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: IP not whitelisted"
                )

        response = await call_next(request)
        return response

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request"""
        # Check X-Forwarded-For header (if behind proxy)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()

        # Check X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        return request.client.host if request.client else "unknown"

    def _is_ip_allowed(self, ip_str: str) -> bool:
        """Check if IP is in whitelist"""
        try:
            client_ip = ipaddress.ip_address(ip_str)

            # Check exact match
            if ip_str in self.whitelist:
                return True

            # Check CIDR ranges
            for network in self.ip_networks:
                if client_ip in network:
                    return True

            return False
        except ValueError:
            logger.error(f"Invalid IP address: {ip_str}")
            return False
