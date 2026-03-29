"""
Database table cleanup analysis and script
检查空表并确定哪些可以安全删除
"""
import psycopg2

# 连接数据库
conn = psycopg2.connect('postgresql://postgres:Lk106504@127.0.0.1:5432/postgres')
cur = conn.cursor()

print("=== Empty Tables Analysis ===\n")

# 获取所有空表
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name
""")
tables = [t[0] for t in cur.fetchall()]

empty_tables = []
for table in tables:
    cur.execute(f'SELECT COUNT(*) FROM {table}')
    count = cur.fetchone()[0]
    if count == 0:
        empty_tables.append(table)

print(f"Found {len(empty_tables)} empty tables:\n")

# 分类分析
print("1. KEEP - Currently used by system (positions, trades, etc.):")
keep_tables = [
    'positions',  # 持仓表 - 代码中大量使用
    'trades',  # 交易记录 - 代码中使用
    'market_data',  # 市场数据 - 代码中大量使用
    'account_snapshots',  # 账户快照 - 代码中使用
    'pending_orders',  # 待处理订单 - 代码中使用
    'risk_alerts',  # 风险警报 - 代码中使用
    'system_alerts',  # 系统警报 - 代码中使用
    'system_logs',  # 系统日志 - 代码中使用
    'notifications',  # 通知 - 代码中使用
    'user_notification_settings',  # 用户通知设置 - 代码中使用
    'strategies',  # 策略表 - automation API使用
    'strategy_performance',  # 策略性能 - 代码中使用
]

for table in empty_tables:
    if table in keep_tables:
        print(f"  - {table}")

print("\n2. CONSIDER REMOVING - May be deprecated or unused:")
remove_candidates = [
    'ssl_certificates',  # SSL证书 - 可能不再使用
    'ssl_certificate_logs',  # SSL证书日志 - 可能不再使用
    'version_backups',  # 版本备份 - 可能不再使用
]

for table in empty_tables:
    if table in remove_candidates:
        print(f"  - {table}")

print("\n3. Analysis complete.")
print("\nRecommendation:")
print("- Keep all tables that are referenced in code")
print("- Only remove tables that are confirmed unused")
print("- ssl_certificates, ssl_certificate_logs may be safe to remove if SSL management is not used")

conn.close()
