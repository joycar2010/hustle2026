"""Initialize platform data in database"""
import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.platform import Platform


async def init_platforms():
    """Initialize platform data"""
    async with AsyncSessionLocal() as session:
        # Check if platforms already exist
        result = await session.execute(select(Platform))
        existing = result.scalars().all()

        if existing:
            print("Platforms already initialized")
            return

        # Create Binance platform
        binance = Platform(
            platform_id=1,
            platform_name="Binance",
            api_base_url="https://fapi.binance.com",
            ws_base_url="wss://fstream.binance.com",
            account_api_type="binance_futures",
            market_api_type="binance_futures",
        )

        # Create Bybit platform
        bybit = Platform(
            platform_id=2,
            platform_name="Bybit",
            api_base_url="https://api.bybit.com",
            ws_base_url="wss://stream.bybit.com",
            account_api_type="bybit_v5",
            market_api_type="bybit_mt5",
        )

        session.add(binance)
        session.add(bybit)

        await session.commit()

        print("Platforms initialized successfully")
        print("- Binance (ID: 1)")
        print("- Bybit (ID: 2)")


if __name__ == "__main__":
    asyncio.run(init_platforms())
