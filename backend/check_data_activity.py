import psycopg2
from datetime import datetime

conn = psycopg2.connect('postgresql://postgres:Lk106504@127.0.0.1:5432/postgres')
cur = conn.cursor()

# Check recent data in key tables
print('Recent Data Activity:')
print('-' * 60)

# spread_records
cur.execute("SELECT MAX(record_time), MIN(record_time), COUNT(*) FROM spread_records")
result = cur.fetchone()
print(f'spread_records: {result[2]} records')
print(f'  Latest: {result[0]}')
print(f'  Oldest: {result[1]}')

# notification_logs
cur.execute("SELECT MAX(created_at), MIN(created_at), COUNT(*) FROM notification_logs")
result = cur.fetchone()
print(f'\nnotification_logs: {result[2]} records')
print(f'  Latest: {result[0]}')
print(f'  Oldest: {result[1]}')

# arbitrage_tasks
cur.execute("SELECT MAX(open_time), MIN(open_time), COUNT(*) FROM arbitrage_tasks")
result = cur.fetchone()
print(f'\narbitrage_tasks: {result[2]} records')
print(f'  Latest: {result[0]}')
print(f'  Oldest: {result[1]}')

# order_records
cur.execute("SELECT MAX(create_time), MIN(create_time), COUNT(*) FROM order_records")
result = cur.fetchone()
print(f'\norder_records: {result[2]} records')
print(f'  Latest: {result[0]}')
print(f'  Oldest: {result[1]}')

# Check accounts
cur.execute("SELECT account_name, platform_id, is_active FROM accounts")
accounts = cur.fetchall()
print(f'\nAccounts ({len(accounts)} total):')
for acc in accounts:
    status = 'Active' if acc[2] else 'Inactive'
    print(f'  - {acc[0]} (Platform ID: {acc[1]}) - {status}')

conn.close()
