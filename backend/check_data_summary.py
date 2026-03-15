import psycopg2

conn = psycopg2.connect('postgresql://postgres:Lk106504@127.0.0.1:5432/postgres')
cur = conn.cursor()

print('=== Key Tables Data Activity ===\n')

# spread_records
cur.execute("SELECT MAX(timestamp), MIN(timestamp), COUNT(*) FROM spread_records")
result = cur.fetchone()
print(f'1. spread_records (Price spread records):')
print(f'   Total: {result[2]} records')
if result[0]:
    print(f'   Latest: {result[0]}')
    print(f'   Oldest: {result[1]}')

# notification_logs
cur.execute("SELECT MAX(created_at), MIN(created_at), COUNT(*) FROM notification_logs")
result = cur.fetchone()
print(f'\n2. notification_logs (Notification logs):')
print(f'   Total: {result[2]} records')
if result[0]:
    print(f'   Latest: {result[0]}')
    print(f'   Oldest: {result[1]}')

# arbitrage_tasks
cur.execute("SELECT MAX(open_time), MIN(open_time), COUNT(*), COUNT(CASE WHEN status='open' THEN 1 END) FROM arbitrage_tasks")
result = cur.fetchone()
print(f'\n3. arbitrage_tasks (Arbitrage tasks):')
print(f'   Total: {result[2]} records')
print(f'   Open tasks: {result[3]}')
if result[0]:
    print(f'   Latest: {result[0]}')
    print(f'   Oldest: {result[1]}')

# order_records
cur.execute("SELECT MAX(create_time), MIN(create_time), COUNT(*) FROM order_records")
result = cur.fetchone()
print(f'\n4. order_records (Order records):')
print(f'   Total: {result[2]} records')
if result[0]:
    print(f'   Latest: {result[0]}')
    print(f'   Oldest: {result[1]}')

# accounts
cur.execute("SELECT account_name, is_active FROM accounts")
accounts = cur.fetchall()
print(f'\n5. accounts (Trading accounts):')
print(f'   Total: {len(accounts)} accounts')
for acc in accounts:
    status = 'Active' if acc[1] else 'Inactive'
    print(f'   - {acc[0]}: {status}')

# strategy_configs
cur.execute("SELECT strategy_type, is_enabled FROM strategy_configs")
strategies = cur.fetchall()
print(f'\n6. strategy_configs (Strategy configurations):')
print(f'   Total: {len(strategies)} strategies')
for strat in strategies:
    status = 'Enabled' if strat[1] else 'Disabled'
    print(f'   - {strat[0]}: {status}')

conn.close()
