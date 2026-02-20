import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'order_records')"))
        exists = result.scalar()
        print(f'order_records table exists: {exists}')

        if not exists:
            print('order_records table does NOT exist!')
            print('Please run: alembic upgrade head')
        else:
            # Check if there are any orders
            count_result = await session.execute(text("SELECT COUNT(*) FROM order_records"))
            count = count_result.scalar()
            print(f'Number of orders in database: {count}')

asyncio.run(check())
