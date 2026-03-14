"""Fix test user password"""
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models.user import User

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Create sync engine
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def fix_password():
    """Update test user password"""
    db = SessionLocal()

    try:
        # Find test user
        user = db.query(User).filter(User.username == "test_user").first()

        if not user:
            print("❌ Test user not found!")
            return

        # Generate correct password hash for "test123"
        correct_hash = pwd_context.hash("test123")
        print(f"Generated hash: {correct_hash}")

        # Update password
        user.password_hash = correct_hash
        db.commit()

        print("✓ Password updated successfully!")
        print("Username: test_user")
        print("Password: test123")

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    fix_password()
