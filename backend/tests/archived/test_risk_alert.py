"""Test risk alert manually"""
import asyncio
from app.core.database import AsyncSessionLocal
from app.models.risk_settings import RiskSettings
from app.services.risk_alert_service import RiskAlertService
from sqlalchemy import select

async def test():
    async with AsyncSessionLocal() as db:
        # Get risk settings
        result = await db.execute(select(RiskSettings))
        settings = result.scalars().first()

        if not settings:
            print("No risk settings found")
            return

        print(f"Found risk settings for user: {settings.user_id}")
        print(f"Total net asset threshold: {settings.total_net_asset}")

        # Create risk alert service
        risk_alert_service = RiskAlertService(db)

        # Trigger total asset alert
        print("\nTriggering total asset alert...")
        result = await risk_alert_service.check_total_net_asset(
            user_id=str(settings.user_id),
            current_asset=500.0,  # Below threshold of 600
            threshold=settings.total_net_asset,
            is_below=True
        )

        print(f"Alert sent: {result}")

if __name__ == "__main__":
    asyncio.run(test())
