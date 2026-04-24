import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def check():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users' ORDER BY ordinal_position"))
        for row in r.fetchall():
            print(row[0])

asyncio.run(check())
