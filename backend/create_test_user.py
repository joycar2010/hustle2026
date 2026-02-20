"""
Create a test user for the Hustle XAU system
"""
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.user import User


async def create_test_user():
    """Create a test user"""
    async with AsyncSessionLocal() as session:
        # Check if user already exists
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.username == "admin")
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            print("✓ Test user 'admin' already exists")
            print(f"  Username: admin")
            print(f"  Email: {existing_user.email}")
            return

        # Create new user
        user = User(
            username="admin",
            email="admin@hustle.com",
            password_hash=get_password_hash("admin123"),
            is_active=True,
            role="管理员"
        )

        session.add(user)
        await session.commit()
        await session.refresh(user)

        print("✓ Test user created successfully!")
        print(f"  Username: admin")
        print(f"  Password: admin123")
        print(f"  Email: admin@hustle.com")
        print(f"  User ID: {user.user_id}")
        print("")
        print("You can now log in to the frontend at http://localhost:3000")


if __name__ == "__main__":
    asyncio.run(create_test_user())
