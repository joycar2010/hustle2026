import asyncio
import asyncpg

async def run_migration():
    conn = await asyncpg.connect(
        host='localhost',
        port=5432,
        user='postgres',
        password='hustle2026',
        database='hustle_db'
    )

    try:
        # Add alert_sound column
        await conn.execute("""
            ALTER TABLE notification_templates
            ADD COLUMN IF NOT EXISTS alert_sound VARCHAR(500)
        """)

        # Add repeat_count column
        await conn.execute("""
            ALTER TABLE notification_templates
            ADD COLUMN IF NOT EXISTS repeat_count INTEGER DEFAULT 3
        """)

        print("Migration completed successfully!")
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
