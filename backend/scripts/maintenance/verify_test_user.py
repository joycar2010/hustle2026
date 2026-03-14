import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.core.security import verify_password

async def verify_login():
    username = "test_user"
    password = "123123"

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()

        if not user:
            print(f"User '{username}' not found")
            return

        is_valid = verify_password(password, user.password_hash)
        print(f"User: {username}")
        print(f"Password '{password}' is valid: {is_valid}")

        if is_valid:
            print("\nSUCCESS: Password verification works!")
        else:
            print("\nERROR: Password verification failed!")

if __name__ == "__main__":
    asyncio.run(verify_login())
