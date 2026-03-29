"""Redis权限缓存服务"""
import json
from typing import Set, Optional, Dict, Any
import redis.asyncio as redis
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class PermissionCacheService:
    """权限缓存服务 - 使用Redis异步客户端"""

    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.user_permissions_prefix = "user_permissions:"
        self.role_permissions_prefix = "role_permissions:"
        self.component_status_prefix = "security_component:"
        self.ws_connections_prefix = "ws_connections:"

        # 缓存过期时间（秒）
        self.user_permissions_ttl = 3600  # 1小时
        self.role_permissions_ttl = 86400  # 24小时
        self.component_status_ttl = 300  # 5分钟
        self.ws_connections_ttl = 7200  # 2小时

    async def connect(self):
        """连接Redis"""
        try:
            self.redis_client = await redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis_client.ping()
            logger.info("Redis连接成功")
        except Exception as e:
            logger.error(f"Redis连接失败: {e}")
            raise

    async def close(self):
        """关闭Redis连接"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis连接已关闭")

    # ==================== 用户权限缓存 ====================

    async def get_user_permissions(self, user_id: str) -> Optional[Set[str]]:
        """获取用户权限缓存"""
        try:
            key = f"{self.user_permissions_prefix}{user_id}"
            permissions = await self.redis_client.smembers(key)
            return set(permissions) if permissions else None
        except Exception as e:
            logger.error(f"获取用户权限缓存失败: {e}")
            return None

    async def set_user_permissions(self, user_id: str, permissions: Set[str]):
        """设置用户权限缓存"""
        try:
            key = f"{self.user_permissions_prefix}{user_id}"
            if permissions:
                await self.redis_client.delete(key)
                await self.redis_client.sadd(key, *permissions)
                await self.redis_client.expire(key, self.user_permissions_ttl)
                logger.info(f"用户 {user_id} 权限缓存已更新，共 {len(permissions)} 个权限")
        except Exception as e:
            logger.error(f"设置用户权限缓存失败: {e}")

    async def delete_user_permissions(self, user_id: str):
        """删除用户权限缓存"""
        try:
            key = f"{self.user_permissions_prefix}{user_id}"
            await self.redis_client.delete(key)
            logger.info(f"用户 {user_id} 权限缓存已删除")
        except Exception as e:
            logger.error(f"删除用户权限缓存失败: {e}")

    async def has_permission(self, user_id: str, permission_code: str) -> bool:
        """检查用户是否拥有指定权限"""
        try:
            key = f"{self.user_permissions_prefix}{user_id}"
            return await self.redis_client.sismember(key, permission_code)
        except Exception as e:
            logger.error(f"检查用户权限失败: {e}")
            return False

    # ==================== 角色权限缓存 ====================

    async def get_role_permissions(self, role_id: str) -> Optional[Set[str]]:
        """获取角色权限缓存"""
        try:
            key = f"{self.role_permissions_prefix}{role_id}"
            permissions = await self.redis_client.smembers(key)
            return set(permissions) if permissions else None
        except Exception as e:
            logger.error(f"获取角色权限缓存失败: {e}")
            return None

    async def set_role_permissions(self, role_id: str, permissions: Set[str]):
        """设置角色权限缓存"""
        try:
            key = f"{self.role_permissions_prefix}{role_id}"
            if permissions:
                await self.redis_client.delete(key)
                await self.redis_client.sadd(key, *permissions)
                await self.redis_client.expire(key, self.role_permissions_ttl)
                logger.info(f"角色 {role_id} 权限缓存已更新")
        except Exception as e:
            logger.error(f"设置角色权限缓存失败: {e}")

    async def delete_role_permissions(self, role_id: str):
        """删除角色权限缓存"""
        try:
            key = f"{self.role_permissions_prefix}{role_id}"
            await self.redis_client.delete(key)
            logger.info(f"角色 {role_id} 权限缓存已删除")
        except Exception as e:
            logger.error(f"删除角色权限缓存失败: {e}")

    # ==================== 安全组件状态缓存 ====================

    async def get_component_status(self, component_code: str) -> Optional[Dict[str, Any]]:
        """获取安全组件状态缓存"""
        try:
            key = f"{self.component_status_prefix}{component_code}"
            data = await self.redis_client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"获取组件状态缓存失败: {e}")
            return None

    async def set_component_status(self, component_code: str, status_data: Dict[str, Any]):
        """设置安全组件状态缓存"""
        try:
            key = f"{self.component_status_prefix}{component_code}"
            await self.redis_client.setex(
                key,
                self.component_status_ttl,
                json.dumps(status_data)
            )
            logger.info(f"组件 {component_code} 状态缓存已更新")
        except Exception as e:
            logger.error(f"设置组件状态缓存失败: {e}")

    async def delete_component_status(self, component_code: str):
        """删除安全组件状态缓存"""
        try:
            key = f"{self.component_status_prefix}{component_code}"
            await self.redis_client.delete(key)
        except Exception as e:
            logger.error(f"删除组件状态缓存失败: {e}")

    # ==================== WebSocket连接状态缓存 ====================

    async def add_ws_connection(self, user_id: str, connection_id: str):
        """添加WebSocket连接"""
        try:
            key = f"{self.ws_connections_prefix}{user_id}"
            await self.redis_client.sadd(key, connection_id)
            await self.redis_client.expire(key, self.ws_connections_ttl)
            logger.info(f"用户 {user_id} WebSocket连接 {connection_id} 已添加")
        except Exception as e:
            logger.error(f"添加WebSocket连接失败: {e}")

    async def remove_ws_connection(self, user_id: str, connection_id: str):
        """移除WebSocket连接"""
        try:
            key = f"{self.ws_connections_prefix}{user_id}"
            await self.redis_client.srem(key, connection_id)
            logger.info(f"用户 {user_id} WebSocket连接 {connection_id} 已移除")
        except Exception as e:
            logger.error(f"移除WebSocket连接失败: {e}")

    async def get_user_connections(self, user_id: str) -> Set[str]:
        """获取用户的所有WebSocket连接"""
        try:
            key = f"{self.ws_connections_prefix}{user_id}"
            connections = await self.redis_client.smembers(key)
            return set(connections) if connections else set()
        except Exception as e:
            logger.error(f"获取用户连接失败: {e}")
            return set()

    # ==================== 批量操作 ====================

    async def clear_all_user_permissions(self):
        """清空所有用户权限缓存"""
        try:
            pattern = f"{self.user_permissions_prefix}*"
            async for key in self.redis_client.scan_iter(match=pattern):
                await self.redis_client.delete(key)
            logger.info("所有用户权限缓存已清空")
        except Exception as e:
            logger.error(f"清空用户权限缓存失败: {e}")

    async def clear_all_role_permissions(self):
        """清空所有角色权限缓存"""
        try:
            pattern = f"{self.role_permissions_prefix}*"
            async for key in self.redis_client.scan_iter(match=pattern):
                await self.redis_client.delete(key)
            logger.info("所有角色权限缓存已清空")
        except Exception as e:
            logger.error(f"清空角色权限缓存失败: {e}")


# 全局缓存服务实例
permission_cache = PermissionCacheService()
