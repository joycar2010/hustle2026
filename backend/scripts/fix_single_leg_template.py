import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def fix_template():
    """Fix single leg alert popup template"""
    engine = create_async_engine(
        'postgresql+asyncpg://postgres:postgres@localhost/postgres'
    )

    try:
        async with engine.begin() as conn:
            # Update single leg alert template
            await conn.execute(text("""
                UPDATE notification_templates
                SET
                    popup_title_template = '单腿交易警告',
                    popup_content_template = '{exchange} {direction}单腿持仓 {quantity} 手，持续 {duration} 秒'
                WHERE template_key = 'single_leg_alert'
            """))

            print("[OK] Single leg alert popup template fixed successfully")

            # Verify the update
            result = await conn.execute(text("""
                SELECT template_key, popup_title_template, popup_content_template
                FROM notification_templates
                WHERE template_key = 'single_leg_alert'
            """))

            row = result.fetchone()
            if row:
                print(f"\nTemplate key: {row[0]}")
                print("Popup title and content updated successfully")

    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(fix_template())
