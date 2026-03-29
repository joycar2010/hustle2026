import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check_templates():
    """Check all templates popup config"""
    engine = create_async_engine(
        'postgresql+asyncpg://postgres:postgres@localhost/postgres'
    )

    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT
                    template_key,
                    template_name,
                    popup_title_template,
                    popup_content_template,
                    alert_sound_file,
                    alert_sound_repeat
                FROM notification_templates
                ORDER BY template_key
            """))

            rows = result.fetchall()
            print(f"Total templates: {len(rows)}\n")

            for row in rows:
                print(f"Template: {row[0]}")
                print(f"  popup_title_template: {'[HAS VALUE]' if row[2] else '[EMPTY/NULL]'}")
                print(f"  popup_content_template: {'[HAS VALUE]' if row[3] else '[EMPTY/NULL]'}")
                print(f"  alert_sound_file: {'[HAS VALUE]' if row[4] else '[EMPTY/NULL]'}")
                print(f"  alert_sound_repeat: {row[5]}")
                print()

    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_templates())
