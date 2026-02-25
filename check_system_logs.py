import asyncio
import sys
sys.path.insert(0, 'backend')
from sqlalchemy import text
from app.core.database import engine

async def check_table():
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'system_logs'
            )
        """))
        exists = result.scalar()
        print(f"system_logs table exists: {exists}")

        if exists:
            result = await conn.execute(text("SELECT COUNT(*) FROM system_logs"))
            count = result.scalar()
            print(f"Number of records: {count}")

asyncio.run(check_table())
