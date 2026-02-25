import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/postgres')
    rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    print("=== existing tables ===")
    for r in rows:
        print(r['tablename'])
    await conn.close()

asyncio.run(main())
