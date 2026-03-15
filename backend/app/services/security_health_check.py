"""
安全组件健康检查服务
"""
from typing import Dict, Any, Optional
from datetime import datetime
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from uuid import UUID

from app.models.security_component import SecurityComponent

logger = logging.getLogger(__name__)


class SecurityComponentHealthCheck:
    """安全组件健康检查服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_component_health(self, component_code: str) -> Dict[str, Any]:
        """
        检查单个组件的健康状态

        Args:
            component_code: 组件代码

        Returns:
            健康检查结果
        """
        try:
            # 获取组件信息
            result = await self.db.execute(
                select(SecurityComponent).where(
                    SecurityComponent.component_code == component_code
                )
            )
            component = result.scalar_one_or_none()

            if not component:
                return {
                    "healthy": False,
                    "status": "not_found",
                    "message": f"Component {component_code} not found"
                }

            # 根据组件类型执行不同的健康检查
            health_result = await self._check_by_type(component)

            # 更新组件状态
            await self._update_component_status(
                component.component_id,
                health_result["status"],
                health_result.get("error_message")
            )

            return health_result

        except Exception as e:
            logger.error(f"Health check failed for {component_code}: {e}")
            return {
                "healthy": False,
                "status": "error",
                "message": str(e)
            }

    async def check_all_components(self) -> Dict[str, Any]:
        """
        检查所有启用的组件健康状态

        Returns:
            所有组件的健康检查结果
        """
        result = await self.db.execute(
            select(SecurityComponent).where(
                SecurityComponent.is_enabled == True
            )
        )
        components = result.scalars().all()

        results = {
            "total": len(components),
            "healthy": 0,
            "unhealthy": 0,
            "components": {}
        }

        for component in components:
            health = await self.check_component_health(component.component_code)
            results["components"][component.component_code] = health

            if health["healthy"]:
                results["healthy"] += 1
            else:
                results["unhealthy"] += 1

        return results

    async def _check_by_type(self, component: SecurityComponent) -> Dict[str, Any]:
        """根据组件类型执行健康检查"""

        if not component.is_enabled:
            return {
                "healthy": False,
                "status": "inactive",
                "message": "Component is disabled"
            }

        # 根据组件代码执行特定检查
        checker_map = {
            "jwt_auth": self._check_jwt_auth,
            "bcrypt_hash": self._check_bcrypt_hash,
            "api_key_encryption": self._check_api_key_encryption,
            "cors_protection": self._check_cors_protection,
            "rate_limiting": self._check_rate_limiting,
            "input_validation": self._check_input_validation,
            "key_management": self._check_key_management,
        }

        checker = checker_map.get(component.component_code, self._check_default)
        return await checker(component)

    async def _check_jwt_auth(self, component: SecurityComponent) -> Dict[str, Any]:
        """检查JWT认证组件"""
        try:
            from app.core.security import create_access_token, decode_access_token

            # 测试token生成和解析
            test_token = create_access_token(data={"sub": "health_check"})
            payload = decode_access_token(test_token)

            if payload.get("sub") == "health_check":
                return {
                    "healthy": True,
                    "status": "active",
                    "message": "JWT authentication is working",
                    "last_check": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "healthy": False,
                    "status": "error",
                    "message": "JWT token validation failed",
                    "error_message": "Token payload mismatch"
                }
        except Exception as e:
            return {
                "healthy": False,
                "status": "error",
                "message": "JWT authentication check failed",
                "error_message": str(e)
            }

    async def _check_bcrypt_hash(self, component: SecurityComponent) -> Dict[str, Any]:
        """检查Bcrypt哈希组件"""
        try:
            from app.core.security import get_password_hash, verify_password

            # 测试密码哈希和验证
            test_password = "health_check_password"
            hashed = get_password_hash(test_password)
            verified = verify_password(test_password, hashed)

            if verified:
                return {
                    "healthy": True,
                    "status": "active",
                    "message": "Bcrypt hashing is working",
                    "last_check": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "healthy": False,
                    "status": "error",
                    "message": "Bcrypt verification failed",
                    "error_message": "Password verification mismatch"
                }
        except Exception as e:
            return {
                "healthy": False,
                "status": "error",
                "message": "Bcrypt check failed",
                "error_message": str(e)
            }

    async def _check_api_key_encryption(self, component: SecurityComponent) -> Dict[str, Any]:
        """检查API密钥加密组件"""
        try:
            from app.core.encryption import encrypt_api_key, decrypt_api_key

            # 测试加密和解密
            test_key = "test_api_key_12345"
            encrypted = encrypt_api_key(test_key)
            decrypted = decrypt_api_key(encrypted)

            if decrypted == test_key:
                return {
                    "healthy": True,
                    "status": "active",
                    "message": "API key encryption is working",
                    "last_check": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "healthy": False,
                    "status": "error",
                    "message": "API key decryption mismatch",
                    "error_message": "Decrypted value does not match original"
                }
        except Exception as e:
            return {
                "healthy": False,
                "status": "error",
                "message": "API key encryption check failed",
                "error_message": str(e)
            }

    async def _check_cors_protection(self, component: SecurityComponent) -> Dict[str, Any]:
        """检查CORS保护组件"""
        try:
            from app.core.config import settings

            # 检查CORS配置
            if hasattr(settings, 'cors_origins_list') and settings.cors_origins_list:
                return {
                    "healthy": True,
                    "status": "active",
                    "message": f"CORS protection configured with {len(settings.cors_origins_list)} origins",
                    "last_check": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "healthy": False,
                    "status": "error",
                    "message": "CORS origins not configured",
                    "error_message": "No allowed origins found"
                }
        except Exception as e:
            return {
                "healthy": False,
                "status": "error",
                "message": "CORS check failed",
                "error_message": str(e)
            }

    async def _check_rate_limiting(self, component: SecurityComponent) -> Dict[str, Any]:
        """检查速率限制组件"""
        # 速率限制通常需要Redis，检查Redis连接
        try:
            from app.core.redis_client import redis_client

            if redis_client.client:
                # 测试Redis连接
                await redis_client.client.ping()
                return {
                    "healthy": True,
                    "status": "active",
                    "message": "Rate limiting (Redis) is working",
                    "last_check": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "healthy": False,
                    "status": "inactive",
                    "message": "Redis client not initialized",
                    "error_message": "Rate limiting requires Redis"
                }
        except Exception as e:
            return {
                "healthy": False,
                "status": "error",
                "message": "Rate limiting check failed",
                "error_message": str(e)
            }

    async def _check_input_validation(self, component: SecurityComponent) -> Dict[str, Any]:
        """检查输入验证组件"""
        try:
            from pydantic import BaseModel, ValidationError

            # 测试Pydantic验证
            class TestModel(BaseModel):
                test_field: str

            # 正常验证
            TestModel(test_field="test")

            # 异常验证
            try:
                TestModel(test_field=123)  # 应该失败
                return {
                    "healthy": False,
                    "status": "error",
                    "message": "Input validation not working properly",
                    "error_message": "Validation should have failed but didn't"
                }
            except ValidationError:
                # 预期的错误
                return {
                    "healthy": True,
                    "status": "active",
                    "message": "Input validation is working",
                    "last_check": datetime.utcnow().isoformat()
                }
        except Exception as e:
            return {
                "healthy": False,
                "status": "error",
                "message": "Input validation check failed",
                "error_message": str(e)
            }

    async def _check_key_management(self, component: SecurityComponent) -> Dict[str, Any]:
        """检查密钥管理组件"""
        try:
            from app.services.key_management import get_key_management_service

            # 获取密钥管理服务实例
            key_service = get_key_management_service(self.db)

            # 执行健康检查
            health_result = await key_service.check_health()

            return health_result

        except Exception as e:
            return {
                "healthy": False,
                "status": "error",
                "message": "Key management check failed",
                "error_message": str(e)
            }

    async def _check_default(self, component: SecurityComponent) -> Dict[str, Any]:
        """默认健康检查（未实现的组件）"""
        return {
            "healthy": False,
            "status": "inactive",
            "message": f"Component {component.component_code} not yet implemented",
            "error_message": "Health check not available for this component"
        }

    async def _update_component_status(
        self,
        component_id: UUID,
        status: str,
        error_message: Optional[str] = None
    ):
        """更新组件状态"""
        try:
            await self.db.execute(
                update(SecurityComponent)
                .where(SecurityComponent.component_id == component_id)
                .values(
                    status=status,
                    last_check_at=datetime.utcnow(),
                    error_message=error_message
                )
            )
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to update component status: {e}")
            await self.db.rollback()
