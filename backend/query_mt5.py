import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def query():
    engine = create_async_engine('postgresql+asyncpg://postgres:Aq987456!@localhost:5432/hustle')
    async with engine.connect() as conn:
        result = await conn.execute(text('SELECT client_id, client_name, mt5_login, connection_status FROM mt5_clients'))
        rows = result.fetchall()
        for row in rows:
            print(row)

asyncio.run(query())
