import asyncio
from sqlalchemy import select, delete
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.core.security import get_password_hash

async def recreate_admin():
    async with AsyncSessionLocal() as session:
        # Delete existing admin user
        await session.execute(
            delete(User).where(User.username == "admin")
        )
        await session.commit()
        print("Deleted existing admin user")

        # Create new admin user with correct password
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

        print("\n✓ Admin user recreated successfully!")
        print(f"  Username: admin")
        print(f"  Password: admin123")
        print(f"  Email: admin@hustle.com")
        print(f"  User ID: {user.user_id}")

if __name__ == "__main__":
    asyncio.run(recreate_admin())
