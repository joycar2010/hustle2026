"""权限拦截中间件"""
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional, List
import logging
from uuid import UUID

from app.services.permission_cache import PermissionCacheService
from app.core.security import decode_access_token

logger = logging.getLogger(__name__)


class PermissionInterceptor(BaseHTTPMiddleware):
    """权限拦截中间件 - 自动验证API权限"""

    # 权限映射表: {路径模式: 所需权限}
    PERMISSION_MAP = {
        # RBAC权限管理
        "GET:/api/v1/rbac/roles": "rbac:role:list",
        "POST:/api/v1/rbac/roles": "rbac:role:create",
        "PUT:/api/v1/rbac/roles/*": "rbac:role:update",
        "DELETE:/api/v1/rbac/roles/*": "rbac:role:delete",
        "POST:/api/v1/rbac/roles/*/copy": "rbac:role:copy",
        "GET:/api/v1/rbac/permissions": "rbac:permission:list",
        "POST:/api/v1/rbac/roles/*/permissions": "rbac:role:assign_permission",
        "POST:/api/v1/rbac/users/*/roles": "rbac:user:assign_role",
        "GET:/api/v1/rbac/users/*/permissions": "rbac:user:query_permission",

        # 安全组件管理
        "GET:/api/v1/security/components": "security:component:list",
        "GET:/api/v1/security/components/*": "security:component:detail",
        "POST:/api/v1/security/components/*/enable": "security:component:enable",
        "POST:/api/v1/security/components/*/disable": "security:component:disable",
        "PUT:/api/v1/security/components/*/config": "security:component:config",
        "GET:/api/v1/security/components/*/status": "security:component:status",
        "GET:/api/v1/security/components/*/logs": "security:component:logs",

        # SSL证书管理
        "GET:/api/v1/ssl/certificates": "ssl:certificate:list",
        "GET:/api/v1/ssl/certificates/*": "ssl:certificate:detail",
        "POST:/api/v1/ssl/certificates": "ssl:certificate:upload",
        "POST:/api/v1/ssl/certificates/*/deploy": "ssl:certificate:deploy",
        "DELETE:/api/v1/ssl/certificates/*": "ssl:certificate:delete",
        "GET:/api/v1/ssl/certificates/*/status": "ssl:certificate:status",
        "GET:/api/v1/ssl/certificates/*/logs": "ssl:certificate:logs",
    }

    # 白名单路径（不需要权限验证）
    WHITELIST_PATHS = [
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/health",
    ]

    def __init__(self, app, redis_client):
        super().__init__(app)
        self.permission_cache = PermissionCacheService(redis_client)

    async def dispatch(self, request: Request, call_next):
        """拦截请求并验证权限"""
        path = request.url.path
        method = request.method

        # 检查是否在白名单中
        if self._is_whitelisted(path):
            return await call_next(request)

        # 获取用户ID
        user_id = await self._get_user_id_from_token(request)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权访问"
            )

        # 获取所需权限
        required_permission = self._get_required_permission(method, path)
        if not required_permission:
            # 没有配置权限要求，允许访问
            return await call_next(request)

        # 验证用户权限
        has_permission = await self._check_user_permission(user_id, required_permission)
        if not has_permission:
            logger.warning(
                f"权限拒绝: user_id={user_id}, "
                f"path={path}, method={method}, "
                f"required_permission={required_permission}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"缺少权限: {required_permission}"
            )

        # 权限验证通过，继续处理请求
        logger.info(f"权限验证通过: user_id={user_id}, permission={required_permission}")
        return await call_next(request)

    def _is_whitelisted(self, path: str) -> bool:
        """检查路径是否在白名单中"""
        for whitelist_path in self.WHITELIST_PATHS:
            if path.startswith(whitelist_path):
                return True
        return False

    async def _get_user_id_from_token(self, request: Request) -> Optional[str]:
        """从请求中获取用户ID"""
        try:
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return None

            token = auth_header.replace("Bearer ", "")
            payload = decode_access_token(token)
            return payload.get("sub")
        except Exception as e:
            logger.error(f"解析token失败: {e}")
            return None

    def _get_required_permission(self, method: str, path: str) -> Optional[str]:
        """获取路径所需的权限"""
        # 精确匹配
        key = f"{method}:{path}"
        if key in self.PERMISSION_MAP:
            return self.PERMISSION_MAP[key]

        # 模糊匹配（支持通配符*）
        for pattern, permission in self.PERMISSION_MAP.items():
            if self._match_pattern(pattern, key):
                return permission

        return None

    def _match_pattern(self, pattern: str, key: str) -> bool:
        """匹配路径模式（支持*通配符）"""
        if "*" not in pattern:
            return pattern == key

        # 将模式转换为正则表达式
        import re
        regex_pattern = pattern.replace("*", "[^/]+")
        regex_pattern = f"^{regex_pattern}$"
        return bool(re.match(regex_pattern, key))

    async def _check_user_permission(self, user_id: str, permission: str) -> bool:
        """检查用户是否拥有指定权限"""
        try:
            # 从缓存获取用户权限
            user_permissions = await self.permission_cache.get_user_permissions(UUID(user_id))
            if user_permissions is None:
                logger.warning(f"无法获取用户权限: user_id={user_id}")
                return False

            # 检查是否拥有该权限
            return permission in user_permissions
        except Exception as e:
            logger.error(f"检查用户权限失败: {e}")
            return False
