"""初始化安全组件数据脚本"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import async_session_maker
from app.models.security_component import SecurityComponent
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 预定义的安全组件配置
SECURITY_COMPONENTS = [
    {
        "component_code": "csrf_protection",
        "component_name": "CSRF保护",
        "component_type": "middleware",
        "description": "防止跨站请求伪造攻击，验证请求中的CSRF Token",
        "config_json": {
            "enabled_methods": ["POST", "PUT", "DELETE", "PATCH"],
            "excluded_paths": ["/api/v1/auth/login", "/ws"],
            "token_header": "X-CSRF-Token",
            "token_expiry": 3600
        },
        "priority": 90,
        "is_enabled": False
    },
    {
        "component_code": "request_signature",
        "component_name": "请求签名验证",
        "component_type": "middleware",
        "description": "验证API请求签名，防止重放攻击",
        "config_json": {
            "algorithm": "HMAC-SHA256",
            "max_timestamp_diff": 300,
            "excluded_paths": ["/docs", "/health", "/api/v1/auth/login"],
            "require_nonce": True
        },
        "priority": 85,
        "is_enabled": False
    },
    {
        "component_code": "ip_whitelist",
        "component_name": "IP白名单",
        "component_type": "middleware",
        "description": "限制特定IP地址访问管理接口",
        "config_json": {
            "whitelist": ["127.0.0.1", "::1"],
            "protected_paths": ["/api/v1/users", "/api/v1/system", "/api/v1/rbac"],
            "enabled": False
        },
        "priority": 95,
        "is_enabled": False
    },
    {
        "component_code": "rate_limiting",
        "component_name": "API速率限制",
        "component_type": "middleware",
        "description": "限制API请求频率，防止滥用",
        "config_json": {
            "default_limit": "100/minute",
            "auth_limit": "10/minute",
            "trading_limit": "50/minute",
            "burst_size": 10
        },
        "priority": 80,
        "is_enabled": True
    },
    {
        "component_code": "log_sanitizer",
        "component_name": "日志脱敏",
        "component_type": "service",
        "description": "自动过滤日志中的敏感信息",
        "config_json": {
            "sensitive_fields": ["password", "api_key", "api_secret", "token", "secret_key"],
            "mask_string": "***",
            "enabled": True
        },
        "priority": 100,
        "is_enabled": True
    },
    {
        "component_code": "encryption_service",
        "component_name": "数据加密服务",
        "component_type": "service",
        "description": "API密钥和敏感数据加密存储",
        "config_json": {
            "algorithm": "Fernet",
            "key_rotation_days": 90,
            "enabled": True
        },
        "priority": 100,
        "is_enabled": True
    },
    {
        "component_code": "sql_injection_protection",
        "component_name": "SQL注入防护",
        "component_type": "protection",
        "description": "检测和阻止SQL注入攻击",
        "config_json": {
            "use_parameterized_queries": True,
            "block_suspicious_patterns": True,
            "log_attempts": True
        },
        "priority": 100,
        "is_enabled": True
    },
    {
        "component_code": "xss_protection",
        "component_name": "XSS跨站脚本防护",
        "component_type": "protection",
        "description": "防止跨站脚本攻击",
        "config_json": {
            "sanitize_input": True,
            "escape_output": True,
            "content_security_policy": "default-src 'self'"
        },
        "priority": 90,
        "is_enabled": True
    },
    {
        "component_code": "brute_force_protection",
        "component_name": "暴力破解防护",
        "component_type": "protection",
        "description": "防止暴力破解登录",
        "config_json": {
            "max_attempts": 5,
            "lockout_duration": 900,
            "reset_after": 3600,
            "protected_endpoints": ["/api/v1/auth/login"]
        },
        "priority": 95,
        "is_enabled": True
    },
    {
        "component_code": "session_management",
        "component_name": "会话管理",
        "component_type": "service",
        "description": "安全的用户会话管理",
        "config_json": {
            "session_timeout": 1800,
            "max_sessions_per_user": 5,
            "secure_cookie": True,
            "httponly_cookie": True
        },
        "priority": 85,
        "is_enabled": True
    },
    {
        "component_code": "audit_logging",
        "component_name": "审计日志",
        "component_type": "service",
        "description": "记录所有敏感操作的审计日志",
        "config_json": {
            "log_level": "INFO",
            "retention_days": 90,
            "log_sensitive_operations": True,
            "include_ip_address": True
        },
        "priority": 75,
        "is_enabled": True
    },
    {
        "component_code": "websocket_auth",
        "component_name": "WebSocket认证",
        "component_type": "middleware",
        "description": "WebSocket连接强制Token认证",
        "config_json": {
            "require_token": True,
            "token_param": "token",
            "close_code_on_failure": 1008
        },
        "priority": 100,
        "is_enabled": True
    }
]


async def init_security_components():
    """初始化安全组件数据"""
    async with async_session_maker() as session:
        try:
            logger.info("开始初始化安全组件数据...")

            created_count = 0
            updated_count = 0
            skipped_count = 0

            for component_data in SECURITY_COMPONENTS:
                # 检查组件是否已存在
                result = await session.execute(
                    select(SecurityComponent).where(
                        SecurityComponent.component_code == component_data["component_code"]
                    )
                )
                existing_component = result.scalar_one_or_none()

                if existing_component:
                    # 更新现有组件（仅更新描述和默认配置，不改变启用状态）
                    existing_component.component_name = component_data["component_name"]
                    existing_component.description = component_data["description"]
                    existing_component.component_type = component_data["component_type"]
                    existing_component.priority = component_data["priority"]

                    # 只在组件未启用时更新配置
                    if not existing_component.is_enabled:
                        existing_component.config_json = component_data["config_json"]

                    updated_count += 1
                    logger.info(f"更新组件: {component_data['component_code']}")
                else:
                    # 创建新组件
                    new_component = SecurityComponent(
                        component_code=component_data["component_code"],
                        component_name=component_data["component_name"],
                        component_type=component_data["component_type"],
                        description=component_data["description"],
                        config_json=component_data["config_json"],
                        priority=component_data["priority"],
                        is_enabled=component_data["is_enabled"],
                        status='active' if component_data["is_enabled"] else 'inactive'
                    )
                    session.add(new_component)
                    created_count += 1
                    logger.info(f"创建组件: {component_data['component_code']}")

            await session.commit()

            logger.info(f"安全组件初始化完成！")
            logger.info(f"  - 新创建: {created_count} 个")
            logger.info(f"  - 已更新: {updated_count} 个")
            logger.info(f"  - 总计: {len(SECURITY_COMPONENTS)} 个")

            # 显示已启用的组件
            result = await session.execute(
                select(SecurityComponent).where(SecurityComponent.is_enabled == True)
            )
            enabled_components = result.scalars().all()

            logger.info(f"\n已启用的安全组件 ({len(enabled_components)} 个):")
            for comp in enabled_components:
                logger.info(f"  ✓ {comp.component_name} ({comp.component_code})")

        except Exception as e:
            await session.rollback()
            logger.error(f"初始化安全组件失败: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(init_security_components())
