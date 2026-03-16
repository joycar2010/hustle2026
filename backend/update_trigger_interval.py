#!/usr/bin/env python3
"""Update trigger_check_interval from 50ms to 500ms in database"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from app.core.database import AsyncSessionLocal


async def update_trigger_interval():
    """Update all strategy configs with trigger_check_interval < 0.1 to 0.5"""
    async with AsyncSessionLocal() as session:
        try:
            # Update records
            result = await session.execute(
                text("UPDATE strategy_configs SET trigger_check_interval = 0.5 WHERE trigger_check_interval < 0.1")
            )
            await session.commit()

            print(f"[OK] Updated {result.rowcount} records from 50ms to 500ms")

            # Verify update
            verify_result = await session.execute(
                text("SELECT COUNT(*) FROM strategy_configs WHERE trigger_check_interval = 0.5")
            )
            count = verify_result.scalar()
            print(f"[OK] Total records with 500ms: {count}")

        except Exception as e:
            print(f"[ERROR] Error updating database: {e}")
            await session.rollback()
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(update_trigger_interval())
