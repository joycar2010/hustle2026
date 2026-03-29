import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check_template():
    """Check single leg alert template"""
    engine = create_async_engine(
        'postgresql+asyncpg://postgres:postgres@localhost/postgres'
    )

    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT
                    template_key,
                    title_template,
                    content_template,
                    popup_title_template,
                    popup_content_template,
                    alert_sound_file,
                    alert_sound_repeat
                FROM notification_templates
                WHERE template_key = 'single_leg_alert'
            """))

            row = result.fetchone()
            if row:
                print("Single leg alert template:")
                print(f"  template_key: {row[0]}")
                print(f"  title_template: {'[HAS VALUE]' if row[1] else '[EMPTY]'}")
                print(f"  content_template: {'[HAS VALUE]' if row[2] else '[EMPTY]'}")
                print(f"  popup_title_template: {'[HAS VALUE]' if row[3] else '[EMPTY]'}")
                print(f"  popup_content_template: {'[HAS VALUE]' if row[4] else '[EMPTY]'}")
                print(f"  alert_sound_file: {'[HAS VALUE]' if row[5] else '[EMPTY]'}")
                print(f"  alert_sound_repeat: {row[6]}")
            else:
                print("Template not found!")

    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_template())
