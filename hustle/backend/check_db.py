import psycopg2

# 连接到PostgreSQL服务器
try:
    # 使用admin用户和hustle_db数据库
    conn = psycopg2.connect(
        host='localhost',
        database='hustle_db',
        user='admin',
        password='password'
    )
    
    # 创建游标
    cur = conn.cursor()
    
    # 检查是否存在users表
    print("检查users表...")
    cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users');")
    users_exists = cur.fetchone()[0]
    print(f"users表存在: {users_exists}")
    
    # 检查是否存在platforms表
    print("检查platforms表...")
    cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'platforms');")
    platforms_exists = cur.fetchone()[0]
    print(f"platforms表存在: {platforms_exists}")
    
    # 检查是否存在accounts表
    print("检查accounts表...")
    cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'accounts');")
    accounts_exists = cur.fetchone()[0]
    print(f"accounts表存在: {accounts_exists}")
    
    # 检查是否存在默认用户
    if users_exists:
        print("检查默认用户...")
        cur.execute("SELECT COUNT(*) FROM users WHERE user_id = '00000000-0000-0000-0000-000000000000';")
        default_user_count = cur.fetchone()[0]
        print(f"默认用户存在: {default_user_count > 0}")
    
    # 检查是否存在平台数据
    if platforms_exists:
        print("检查平台数据...")
        cur.execute("SELECT COUNT(*) FROM platforms;")
        platform_count = cur.fetchone()[0]
        print(f"平台数据数量: {platform_count}")
        
        # 显示平台数据
        if platform_count > 0:
            cur.execute("SELECT platform_id, platform_name FROM platforms;")
            platforms = cur.fetchall()
            print("平台数据:")
            for platform in platforms:
                print(f"  ID: {platform[0]}, 名称: {platform[1]}")
    
    # 检查是否存在账户数据
    if accounts_exists:
        print("检查账户数据...")
        cur.execute("SELECT COUNT(*) FROM accounts;")
        account_count = cur.fetchone()[0]
        print(f"账户数据数量: {account_count}")
    
    # 关闭游标和连接
    cur.close()
    conn.close()
    
    print("所有操作完成！")
    
except Exception as e:
    print(f"错误: {e}")
    
    # 如果连接已经打开，关闭它
    if 'conn' in locals() and conn:
        conn.close()