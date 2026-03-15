"""
创建arbitrage_opportunities表并迁移数据
"""
import asyncio
import sys
sys.path.append('.')

from app.core.database import engine, AsyncSessionLocal
from app.models.arbitrage_opportunity import ArbitrageOpportunity
from app.services.arbitrage_opportunity_service import arbitrage_opportunity_service
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_table():
    """创建arbitrage_opportunities表"""
    try:
        async with engine.begin() as conn:
            # 创建表
            await conn.run_sync(ArbitrageOpportunity.__table__.create, checkfirst=True)
        logger.info("✓ arbitrage_opportunities table created successfully")
        return True
    except Exception as e:
        logger.error(f"✗ Error creating table: {e}")
        return False


async def migrate_data():
    """从spread_records迁移数据到arbitrage_opportunities"""
    try:
        async with AsyncSessionLocal() as db:
            logger.info("Starting data migration...")
            result = await arbitrage_opportunity_service.extract_opportunities(db)
            logger.info(f"✓ Migration completed: {result}")
            return True
    except Exception as e:
        logger.error(f"✗ Error migrating data: {e}")
        return False


async def main():
    """主函数"""
    logger.info("=== Arbitrage Opportunities Table Migration ===\n")

    # 步骤1: 创建表
    logger.info("Step 1: Creating arbitrage_opportunities table...")
    if not await create_table():
        logger.error("Failed to create table. Aborting.")
        return

    # 步骤2: 迁移数据
    logger.info("\nStep 2: Migrating data from spread_records...")
    if not await migrate_data():
        logger.error("Failed to migrate data.")
        return

    logger.info("\n=== Migration completed successfully ===")


if __name__ == "__main__":
    asyncio.run(main())
