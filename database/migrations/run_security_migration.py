"""
执行安全组件数据迁移
"""
import asyncio
import asyncpg
from pathlib import Path

async def run_migration():
    # 数据库连接配置
    conn = await asyncpg.connect(
        host='localhost',
        port=5432,
        user='postgres',
        password='postgres',
        database='postgres'
    )

    try:
        # 读取SQL文件
        sql_file = Path(__file__).parent / 'insert_security_components.sql'
        with open(sql_file, 'r', encoding='utf-8') as f:
            sql = f.read()

        # 执行SQL
        await conn.execute(sql)

        # 查询结果
        result = await conn.fetch("""
            SELECT
                COUNT(*) as total_components,
                SUM(CASE WHEN is_enabled THEN 1 ELSE 0 END) as enabled_components,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_components
            FROM security_components
        """)

        print("Security components migration successful!")
        print(f"Total components: {result[0]['total_components']}")
        print(f"Enabled: {result[0]['enabled_components']}")
        print(f"Active: {result[0]['active_components']}")

    except Exception as e:
        print(f"Migration failed: {e}")
        raise
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(run_migration())
