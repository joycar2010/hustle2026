"""
Update admin user password with correct bcrypt hash
"""
import psycopg2
import bcrypt

# Database connection
conn = psycopg2.connect(
    host="localhost",
    port=5432,
    user="postgres",
    password="postgres",
    database="hustle_db"
)

cursor = conn.cursor()

# Generate new password hash with current bcrypt version
password = "admin123"
password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# Update the admin user's password
cursor.execute("""
    UPDATE users
    SET password_hash = %s
    WHERE username = 'admin'
""", (password_hash,))

conn.commit()

print("✓ Admin password updated successfully!")
print(f"  Username: admin")
print(f"  Password: admin123")
print(f"  New hash: {password_hash}")

cursor.close()
conn.close()
