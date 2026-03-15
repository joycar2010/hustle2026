"""
Reset database for Hustle XAU
Drops and recreates the database with fresh schema
"""
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Database connection parameters
DB_HOST = "localhost"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "postgres"
DB_NAME = "hustle_db"
APP_USER = "hustle_user"
APP_PASSWORD = "hustle_password"

def reset_database():
    """Drop and recreate the database"""
    print("=" * 50)
    print("Hustle XAU - Database Reset")
    print("=" * 50)
    print()

    # Connect to PostgreSQL server (not to specific database)
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database="postgres"
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        print(f"✓ Connected to PostgreSQL as {DB_USER}")
        print()

        # Terminate existing connections to the database
        print(f"Terminating connections to {DB_NAME}...")
        cursor.execute(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{DB_NAME}'
            AND pid <> pg_backend_pid();
        """)
        print("✓ Connections terminated")
        print()

        # Drop database if exists
        print(f"Dropping database {DB_NAME}...")
        cursor.execute(f"DROP DATABASE IF EXISTS {DB_NAME};")
        print("✓ Database dropped")
        print()

        # Create fresh database
        print(f"Creating database {DB_NAME}...")
        cursor.execute(f"CREATE DATABASE {DB_NAME};")
        print("✓ Database created")
        print()

        # Create user if not exists
        print(f"Creating user {APP_USER}...")
        cursor.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_user WHERE usename = '{APP_USER}') THEN
                    CREATE USER {APP_USER} WITH PASSWORD '{APP_PASSWORD}';
                END IF;
            END
            $$;
        """)
        print("✓ User created/verified")
        print()

        # Grant privileges
        print(f"Granting privileges...")
        cursor.execute(f"GRANT ALL PRIVILEGES ON DATABASE {DB_NAME} TO {APP_USER};")
        cursor.execute(f"ALTER DATABASE {DB_NAME} OWNER TO {APP_USER};")
        print("✓ Privileges granted")
        print()

        cursor.close()
        conn.close()

        print("=" * 50)
        print("Database reset complete!")
        print("=" * 50)
        print()
        print("Next steps:")
        print("  1. Run migrations: alembic upgrade head")
        print("  2. Create test user: python create_test_user.py")
        print("  3. Start backend: uvicorn app.main:app --reload")
        print()

    except psycopg2.Error as e:
        print(f"✗ Error: {e}")
        print()
        print("Make sure:")
        print("  - PostgreSQL is running")
        print("  - You have the correct password for 'postgres' user")
        print("  - Update DB_PASSWORD in this script if needed")
        return False

    return True


if __name__ == "__main__":
    import sys

    print("WARNING: This will delete all data in the hustle_db database!")
    response = input("Are you sure you want to continue? (yes/no): ")

    if response.lower() in ['yes', 'y']:
        reset_database()
    else:
        print("Operation cancelled.")
        sys.exit(0)
