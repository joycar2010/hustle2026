import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# 连接到PostgreSQL服务器
try:
    # 使用admin用户和hustle_db数据库
    conn = psycopg2.connect(
        host='localhost',
        database='hustle_db',
        user='admin',
        password='password'
    )
    
    # 设置自动提交模式
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    
    # 创建游标
    cur = conn.cursor()
    
    # 添加默认用户
    print("添加默认用户...")
    cur.execute("""
    INSERT INTO users (user_id, username, password_hash, email, is_active)
    VALUES ('00000000-0000-0000-0000-000000000000', 'admin', 'password_hash', 'admin@example.com', true)
    ON CONFLICT (user_id) DO NOTHING
    """)
    print("默认用户添加成功！")
    
    # 添加平台数据
    print("添加平台数据...")
    platforms = [
        (1, 'Binance', 'https://fapi.binance.com', 'wss://fstream.binance.com/ws', 'REST', 'REST'),
        (2, 'Bybit', 'https://api.bybit.com', 'wss://stream.bybit.com/v5/public/linear', 'REST', 'REST'),
        (3, 'MT5', 'https://api. MetaTrader5.com', 'wss://api. MetaTrader5.com/ws', 'MT5', 'MT5')
    ]
    
    for platform in platforms:
        cur.execute("""
        INSERT INTO platforms (platform_id, platform_name, api_base_url, ws_base_url, account_api_type, market_api_type)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (platform_id) DO NOTHING
        """, platform)
    
    print("平台数据添加成功！")
    
    # 关闭游标和连接
    cur.close()
    conn.close()
    
    print("所有操作完成！")
    
except Exception as e:
    print(f"错误: {e}")
    
    # 如果连接已经打开，关闭它
    if 'conn' in locals() and conn:
        conn.close()