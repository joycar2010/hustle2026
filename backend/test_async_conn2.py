import asyncio
import asyncpg

async def test():
    try:
        conn = await asyncpg.connect('postgresql://postgres:postgres123@127.0.0.1:5432/postgres')
        print('asyncpg connection successful with postgres123')
        await conn.close()
    except Exception as e:
        print(f'asyncpg connection failed: {e}')

asyncio.run(test())
