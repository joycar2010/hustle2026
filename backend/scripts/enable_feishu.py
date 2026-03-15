"""
飞书服务配置脚本
执行此脚本可立即启用飞书服务
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import AsyncSessionLocal
from app.models.notification_config import NotificationConfig
from sqlalchemy import select
import uuid
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def enable_feishu_service():
    """启用飞书服务配置"""
    try:
        async with AsyncSessionLocal() as db:
            # 检查是否已存在配置
            result = await db.execute(
                select(NotificationConfig).filter(
                    NotificationConfig.service_type == 'feishu'
                )
            )
            config = result.scalar_one_or_none()

            feishu_config_data = {
                "app_id": "cli_a9235819f078dcbd",
                "app_secret": "KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE"
            }

            if config:
                # 更新现有配置
                config.is_enabled = True
                config.config_data = feishu_config_data
                logger.info("更新现有飞书配置")
            else:
                # 创建新配置
                config = NotificationConfig(
                    config_id=uuid.UUID('3ba11638-7585-4fc8-ad3c-e12ed070501a'),
                    service_type='feishu',
                    is_enabled=True,
                    config_data=feishu_config_data
                )
                db.add(config)
                logger.info("创建新飞书配置")

            await db.commit()

            # 验证配置
            result = await db.execute(
                select(NotificationConfig).filter(
                    NotificationConfig.service_type == 'feishu'
                )
            )
            verified_config = result.scalar_one_or_none()

            if verified_config:
                logger.info("✅ 飞书服务配置成功！")
                logger.info(f"   服务类型: {verified_config.service_type}")
                logger.info(f"   启用状态: {verified_config.is_enabled}")
                logger.info(f"   App ID: {verified_config.config_data.get('app_id')}")
                logger.info(f"   更新时间: {verified_config.updated_at}")
                logger.info("\n⚠️  请重启后端服务以使配置生效")
                return True
            else:
                logger.error("❌ 配置验证失败")
                return False

    except Exception as e:
        logger.error(f"❌ 配置飞书服务失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(enable_feishu_service())
    sys.exit(0 if success else 1)
