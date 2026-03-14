"""
Database and ORM Model Consistency Checker

This script checks if all ORM models have corresponding database tables
and identifies any tables in the database that are not defined in ORM models.

Usage:
    python check_db_consistency.py
"""
import asyncio
from sqlalchemy import text
from app.models import *
from app.core.database import engine, Base


async def check_consistency():
    """Check consistency between database tables and ORM models"""
    async with engine.begin() as conn:
        # Get all tables from database
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        )
        db_tables = {row[0] for row in result}
        
        # Get all tables from ORM models
        orm_tables = {table.name for table in Base.metadata.tables.values()}
        
        # Calculate differences
        missing_in_db = orm_tables - db_tables
        extra_in_db = db_tables - orm_tables
        
        # Print results
        print("=" * 60)
        print("Database and ORM Model Consistency Check")
        print("=" * 60)
        print()
        
        if missing_in_db:
            print(f"ORM models defined but missing in database ({len(missing_in_db)}):")
            for table in sorted(missing_in_db):
                print(f"  - {table}")
            print()
        
        if extra_in_db:
            print(f"Database tables not defined in ORM ({len(extra_in_db)}):")
            for table in sorted(extra_in_db):
                print(f"  - {table}")
            print()
        
        if not missing_in_db and not extra_in_db:
            print("Database tables and ORM models are fully consistent")
            print()
        
        print(f"Total ORM tables: {len(orm_tables)}")
        print(f"Total DB tables: {len(db_tables)}")
        print()
        
        # Return status
        if missing_in_db:
            print("ACTION REQUIRED: Create missing tables using Alembic migrations")
            return False
        else:
            print("STATUS: All ORM models have corresponding database tables")
            return True


if __name__ == "__main__":
    success = asyncio.run(check_consistency())
    exit(0 if success else 1)
