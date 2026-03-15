import psycopg2
import sys

conn = psycopg2.connect('postgresql://postgres:Lk106504@127.0.0.1:5432/postgres')
cur = conn.cursor()

# Get all tables
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name
""")
tables = cur.fetchall()

print('Database Tables:')
for table in tables:
    print(f'- {table[0]}')

print('\nTable Record Counts:')
for table in tables:
    table_name = table[0]
    cur.execute(f'SELECT COUNT(*) FROM {table_name}')
    count = cur.fetchone()[0]
    print(f'{table_name}: {count} records')

conn.close()
