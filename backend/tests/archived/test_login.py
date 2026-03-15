import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.core.security import verify_password

async def check_login():
    async with AsyncSessionLocal() as session:
        # Get admin user
        result = await session.execute(
            select(User).where(User.username == "admin")
        )
        user = result.scalar_one_or_none()

        if not user:
            print("ERROR: Admin user not found in database")
            return

        print(f"User found: {user.username}")
        print(f"Email: {user.email}")
        print(f"Active: {user.is_active}")

        # Test password verification
        test_password = "admin123"
        is_valid = verify_password(test_password, user.password_hash)
        print(f"\nPassword verification test:")
        print(f"Password '{test_password}' is valid: {is_valid}")

        if not is_valid:
            print("\nERROR: Password verification failed!")
            print("This means the stored password hash doesn't match 'admin123'")
        else:
            print("\nSUCCESS: Password verification works correctly")

if __name__ == "__main__":
    asyncio.run(check_login())
