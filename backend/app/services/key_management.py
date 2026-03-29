"""密钥管理服务 - 集中管理系统密钥,支持密钥轮换和版本控制"""
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_
import logging

from app.core.encryption import encryption_service

logger = logging.getLogger(__name__)


# 全局密钥缓存(跨请求共享)
_global_key_cache: Dict[str, Dict[str, Any]] = {}


class KeyManagementService:
    """密钥管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        # 使用全局缓存而不是实例缓存
        self._key_cache = _global_key_cache

    def generate_key(self, key_type: str = "api", length: int = 32) -> str:
        """
        生成新密钥

        Args:
            key_type: 密钥类型 (api, encryption, signing)
            length: 密钥长度(字节)

        Returns:
            生成的密钥(hex编码)
        """
        if key_type == "api":
            # API密钥使用URL安全的base64编码
            return secrets.token_urlsafe(length)
        elif key_type == "encryption":
            # 加密密钥使用hex编码
            return secrets.token_hex(length)
        elif key_type == "signing":
            # 签名密钥使用hex编码
            return secrets.token_hex(length)
        else:
            # 默认使用hex编码
            return secrets.token_hex(length)

    async def store_key(
        self,
        key_name: str,
        key_value: str,
        key_type: str = "api",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        存储密钥

        Args:
            key_name: 密钥名称
            key_value: 密钥值
            key_type: 密钥类型
            metadata: 元数据

        Returns:
            存储的密钥信息
        """
        # 加密密钥值
        encrypted_value = encryption_service.encrypt(key_value)

        # 创建密钥记录
        key_record = {
            "key_name": key_name,
            "key_type": key_type,
            "encrypted_value": encrypted_value,
            "version": 1,
            "created_at": datetime.utcnow(),
            "expires_at": None,
            "is_active": True,
            "metadata": metadata or {}
        }

        # 存储到缓存
        if key_name not in self._key_cache:
            self._key_cache[key_name] = {"versions": []}

        self._key_cache[key_name]["versions"].append(key_record)
        self._key_cache[key_name]["current_version"] = 1

        logger.info(f"Stored key: {key_name}, type: {key_type}, version: 1")
        return key_record

    async def get_key(
        self,
        key_name: str,
        version: Optional[int] = None
    ) -> Optional[str]:
        """
        获取密钥

        Args:
            key_name: 密钥名称
            version: 密钥版本(None表示获取当前版本)

        Returns:
            解密后的密钥值
        """
        if key_name not in self._key_cache:
            logger.warning(f"Key not found: {key_name}")
            return None

        key_data = self._key_cache[key_name]

        if version is None:
            version = key_data.get("current_version", 1)

        # 查找指定版本
        for key_record in key_data["versions"]:
            if key_record["version"] == version and key_record["is_active"]:
                # 解密密钥值
                decrypted_value = encryption_service.decrypt(
                    key_record["encrypted_value"]
                )
                return decrypted_value

        logger.warning(f"Key version not found: {key_name}, version: {version}")
        return None

    async def rotate_key(
        self,
        key_name: str,
        max_versions: int = 3
    ) -> Dict[str, Any]:
        """
        轮换密钥

        Args:
            key_name: 密钥名称
            max_versions: 保留的最大版本数

        Returns:
            新密钥信息
        """
        if key_name not in self._key_cache:
            raise ValueError(f"Key not found: {key_name}")

        key_data = self._key_cache[key_name]
        current_version = key_data.get("current_version", 0)
        new_version = current_version + 1

        # 获取旧密钥的类型
        old_key_type = "api"
        if key_data["versions"]:
            old_key_type = key_data["versions"][-1]["key_type"]

        # 生成新密钥
        new_key_value = self.generate_key(key_type=old_key_type)
        encrypted_value = encryption_service.encrypt(new_key_value)

        # 创建新版本
        new_key_record = {
            "key_name": key_name,
            "key_type": old_key_type,
            "encrypted_value": encrypted_value,
            "version": new_version,
            "created_at": datetime.utcnow(),
            "expires_at": None,
            "is_active": True,
            "metadata": {"rotated_from": current_version}
        }

        # 添加新版本
        key_data["versions"].append(new_key_record)
        key_data["current_version"] = new_version

        # 清理旧版本(保留最近的max_versions个版本)
        if len(key_data["versions"]) > max_versions:
            # 标记旧版本为非活跃
            versions_to_keep = key_data["versions"][-max_versions:]
            for old_version in key_data["versions"][:-max_versions]:
                old_version["is_active"] = False

            key_data["versions"] = versions_to_keep

        logger.info(
            f"Rotated key: {key_name}, "
            f"old version: {current_version}, "
            f"new version: {new_version}"
        )

        return new_key_record

    async def list_keys(self) -> List[Dict[str, Any]]:
        """
        列出所有密钥

        Returns:
            密钥列表(不包含密钥值)
        """
        keys_list = []
        for key_name, key_data in self._key_cache.items():
            current_version = key_data.get("current_version", 1)
            versions_count = len(key_data["versions"])

            # 获取当前版本的信息
            current_key = None
            for key_record in key_data["versions"]:
                if key_record["version"] == current_version:
                    current_key = key_record
                    break

            if current_key:
                keys_list.append({
                    "key_name": key_name,
                    "key_type": current_key["key_type"],
                    "current_version": current_version,
                    "versions_count": versions_count,
                    "created_at": current_key["created_at"],
                    "is_active": current_key["is_active"]
                })

        return keys_list

    async def delete_key(self, key_name: str) -> bool:
        """
        删除密钥

        Args:
            key_name: 密钥名称

        Returns:
            是否删除成功
        """
        if key_name in self._key_cache:
            del self._key_cache[key_name]
            logger.info(f"Deleted key: {key_name}")
            return True

        logger.warning(f"Key not found for deletion: {key_name}")
        return False

    async def check_health(self) -> Dict[str, Any]:
        """
        检查密钥管理服务健康状态

        Returns:
            健康检查结果
        """
        try:
            # 测试密钥生成
            test_key = self.generate_key("api", 16)
            if not test_key or len(test_key) == 0:
                return {
                    "healthy": False,
                    "status": "error",
                    "message": "Key generation failed",
                    "error_message": "Generated key is empty"
                }

            # 测试密钥存储和检索
            test_key_name = "_health_check_key"
            await self.store_key(test_key_name, test_key, "api")
            retrieved_key = await self.get_key(test_key_name)

            if retrieved_key != test_key:
                return {
                    "healthy": False,
                    "status": "error",
                    "message": "Key storage/retrieval failed",
                    "error_message": "Retrieved key does not match stored key"
                }

            # 清理测试密钥
            await self.delete_key(test_key_name)

            # 获取密钥统计
            keys_count = len(self._key_cache)

            return {
                "healthy": True,
                "status": "active",
                "message": f"Key management is working, {keys_count} keys stored",
                "last_check": datetime.utcnow().isoformat(),
                "details": {
                    "keys_count": keys_count,
                    "test_passed": True
                }
            }

        except Exception as e:
            logger.error(f"Key management health check failed: {e}")
            return {
                "healthy": False,
                "status": "error",
                "message": "Key management health check failed",
                "error_message": str(e)
            }


# 全局密钥管理服务实例(实际应该使用依赖注入)
_key_management_service: Optional[KeyManagementService] = None


def get_key_management_service(db: AsyncSession) -> KeyManagementService:
    """获取密钥管理服务实例"""
    return KeyManagementService(db)
