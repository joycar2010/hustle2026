import json
import sys
import io
from sqlalchemy import create_engine, text
from app.core.config import settings

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

engine = create_engine(settings.DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute(text('''
        SELECT template_key, template_name, category, is_active, enable_feishu,
               title_template, content_template
        FROM notification_templates
        WHERE template_name LIKE '%点差%' OR category LIKE '%spread%' OR template_key LIKE '%spread%'
        ORDER BY template_key
    ''')).fetchall()

    print('=== Spread Alert Templates ===\n')
    for row in result:
        print(f'Key: {row[0]}')
        print(f'Name: {row[1]}')
        print(f'Category: {row[2]}')
        print(f'Active: {row[3]}')
        print(f'Feishu: {row[4]}')
        print(f'Title: {row[5]}')
        print(f'Content: {row[6][:200] if row[6] else ""}...')
        print('=' * 80)
        print()
