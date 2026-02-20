"""Add role column to users table"""
import asyncio
from sqlalchemy import text
from app.core.database import engine


async def add_role_column():
    """Add role column to users table if it doesn't exist"""
    async with engine.begin() as conn:
        # Check if role column exists
        result = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='users' AND column_name='role'
        """))

        if result.fetchone() is None:
            # Add role column
            await conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN role VARCHAR(50) NOT NULL DEFAULT '交易员'
            """))
            print("✓ Role column added successfully")
        else:
            print("✓ Role column already exists")


if __name__ == "__main__":
    asyncio.run(add_role_column())
