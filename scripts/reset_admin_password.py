#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/ubuntu/hustle2026/backend')

from app.core.security import get_password_hash
from app.core.database import engine
from sqlalchemy import text
import asyncio

async def update_admin_password():
    password = 'admin123'
    password_hash = get_password_hash(password)
    print(f"Generated hash: {password_hash}")

    async with engine.begin() as conn:
        result = await conn.execute(
            text("UPDATE users SET password_hash = :hash WHERE username = 'admin'"),
            {"hash": password_hash}
        )
        print(f"Updated {result.rowcount} rows")

        # Verify
        result = await conn.execute(
            text("SELECT username, password_hash FROM users WHERE username = 'admin'")
        )
        row = result.fetchone()
        print(f"Verified: {row[0]} - {row[1][:20]}...")

if __name__ == "__main__":
    asyncio.run(update_admin_password())
