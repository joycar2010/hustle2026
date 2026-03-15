"""
Simple test user creation using direct SQL
"""
import psycopg2
from datetime import datetime
import uuid

# Database connection
conn = psycopg2.connect(
    host="localhost",
    port=5432,
    user="postgres",
    password="postgres",
    database="hustle_db"
)

cursor = conn.cursor()

# Check if user exists
cursor.execute("SELECT user_id FROM users WHERE username = 'admin'")
existing = cursor.fetchone()

if existing:
    print("✓ Test user 'admin' already exists")
    print(f"  Username: admin")
    print(f"  User ID: {existing[0]}")
else:
    # Create user with a simple bcrypt hash for "admin123"
    # This is a pre-computed hash for "admin123"
    user_id = str(uuid.uuid4())
    password_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYzS6ZzqM8u"  # admin123

    cursor.execute("""
        INSERT INTO users (user_id, username, password_hash, email, is_active, create_time, update_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        user_id,
        "admin",
        password_hash,
        "admin@hustle.com",
        True,
        datetime.utcnow(),
        datetime.utcnow()
    ))

    conn.commit()

    print("✓ Test user created successfully!")
    print(f"  Username: admin")
    print(f"  Password: admin123")
    print(f"  Email: admin@hustle.com")
    print(f"  User ID: {user_id}")

cursor.close()
conn.close()

print()
print("You can now log in to the frontend at http://localhost:3000")
