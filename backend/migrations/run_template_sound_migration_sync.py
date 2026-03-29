from sqlalchemy import create_engine, text
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL)

with engine.connect() as conn:
    # Add alert_sound column
    conn.execute(text("""
        ALTER TABLE notification_templates
        ADD COLUMN IF NOT EXISTS alert_sound VARCHAR(500)
    """))

    # Add repeat_count column
    conn.execute(text("""
        ALTER TABLE notification_templates
        ADD COLUMN IF NOT EXISTS repeat_count INTEGER DEFAULT 3
    """))

    conn.commit()
    print("Migration completed successfully!")
