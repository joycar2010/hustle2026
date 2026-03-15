import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import AsyncSessionLocal
from app.models.notification_config import NotificationConfig
from app.services.feishu_service import get_feishu_service
from sqlalchemy import select

async def check_feishu_status():
    """Check Feishu service status"""
    print("=== Feishu Service Status Check ===\n")

    # Check database config
    print("1. Checking database configuration...")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(NotificationConfig).filter(
                NotificationConfig.service_type == 'feishu'
            )
        )
        config = result.scalar_one_or_none()

        if config:
            print(f"   Service Type: {config.service_type}")
            print(f"   Enabled: {config.is_enabled}")
            print(f"   App ID: {config.config_data.get('app_id', 'N/A')}")
            print(f"   Has Secret: {'Yes' if config.config_data.get('app_secret') else 'No'}")
            print(f"   Updated: {config.updated_at}")
        else:
            print("   ERROR: No Feishu config found in database")
            return False

    # Check service initialization
    print("\n2. Checking service initialization...")
    feishu = get_feishu_service()
    if feishu:
        print(f"   Status: Initialized")
        print(f"   App ID: {feishu.app_id}")
        print(f"   Has Secret: {'Yes' if feishu.app_secret else 'No'}")
    else:
        print("   Status: NOT initialized")
        print("   Action: Restart backend service to initialize")
        return False

    print("\n=== Status: OK ===")
    return True

if __name__ == "__main__":
    result = asyncio.run(check_feishu_status())
    sys.exit(0 if result else 1)
