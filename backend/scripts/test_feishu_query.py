import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import AsyncSessionLocal
from app.models.notification_config import NotificationConfig
from sqlalchemy import select

async def test_query():
    async with AsyncSessionLocal() as db:
        # Test query 1: without is_enabled filter
        result1 = await db.execute(
            select(NotificationConfig).filter(
                NotificationConfig.service_type == 'feishu'
            )
        )
        config1 = result1.scalar_one_or_none()
        print(f"Query 1 (no filter): {config1 is not None}")
        if config1:
            print(f"  is_enabled: {config1.is_enabled}")
            print(f"  config_data: {config1.config_data}")

        # Test query 2: with is_enabled filter
        result2 = await db.execute(
            select(NotificationConfig).filter(
                NotificationConfig.service_type == 'feishu',
                NotificationConfig.is_enabled == True
            )
        )
        config2 = result2.scalar_one_or_none()
        print(f"\nQuery 2 (with is_enabled=True): {config2 is not None}")
        if config2:
            print(f"  is_enabled: {config2.is_enabled}")
            print(f"  config_data: {config2.config_data}")

if __name__ == "__main__":
    asyncio.run(test_query())
