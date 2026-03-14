"""检查数据库表结构"""
import asyncio
import asyncpg

async def check_schema():
    conn = await asyncpg.connect(
        host='localhost',
        port=5432,
        user='postgres',
        password='postgres',
        database='postgres'
    )

    print("\n=== strategy_performance table structure ===")
    result = await conn.fetch("""
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_name = 'strategy_performance'
        ORDER BY ordinal_position
    """)
    for row in result:
        print(f"{row['column_name']:30} {row['data_type']:20} ({row['udt_name']})")

    print("\n=== strategy_performance foreign keys ===")
    fk_result = await conn.fetch("""
        SELECT
            tc.constraint_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
        WHERE tc.table_name = 'strategy_performance'
        AND tc.constraint_type = 'FOREIGN KEY'
    """)
    for row in fk_result:
        print(f"{row['column_name']} -> {row['foreign_table_name']}.{row['foreign_column_name']}")

    print("\n=== strategies.id column type ===")
    strategies_result = await conn.fetch("""
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_name = 'strategies' AND column_name = 'id'
    """)
    for row in strategies_result:
        print(f"{row['column_name']:30} {row['data_type']:20} ({row['udt_name']})")

    print("\n=== strategy_configs.config_id column type ===")
    configs_result = await conn.fetch("""
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_name = 'strategy_configs' AND column_name = 'config_id'
    """)
    for row in configs_result:
        print(f"{row['column_name']:30} {row['data_type']:20} ({row['udt_name']})")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(check_schema())
