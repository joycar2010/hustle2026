import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.core.security import get_password_hash

async def reset_password():
    username = "test_user"
    new_password = "123123"

    async with AsyncSessionLocal() as session:
        # Find the user
        result = await session.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()

        if not user:
            print(f"ERROR: User '{username}' not found in database")
            return

        # Update password
        user.password_hash = get_password_hash(new_password)
        await session.commit()

        print(f"Password reset successfully!")
        print(f"  Username: {username}")
        print(f"  New password: {new_password}")
        print(f"  User ID: {user.user_id}")

if __name__ == "__main__":
    asyncio.run(reset_password())
