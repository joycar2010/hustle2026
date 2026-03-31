#!/usr/bin/env python3
"""Fix admin password in database"""
import asyncio
import asyncpg
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def main():
    # Generate new password hash
    password = "admin123"
    password_hash = pwd_context.hash(password)
    print(f"Generated hash: {password_hash}")

    # Connect to database
    conn = await asyncpg.connect(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password="Lk106504",
        database="postgres"
    )

    try:
        # Update admin password
        result = await conn.execute(
            "UPDATE users SET password_hash = $1 WHERE username = $2",
            password_hash,
            "admin"
        )
        print(f"Update result: {result}")

        # Verify
        row = await conn.fetchrow(
            "SELECT username, password_hash FROM users WHERE username = $1",
            "admin"
        )
        print(f"Verified - Username: {row['username']}, Hash: {row['password_hash'][:30]}...")

        # Test verification
        is_valid = pwd_context.verify(password, row['password_hash'])
        print(f"Password verification test: {is_valid}")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
