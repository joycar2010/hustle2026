import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# 连接到PostgreSQL服务器
try:
    # 使用默认的postgres用户和数据库
    conn = psycopg2.connect(
        host='localhost',
        database='postgres',
        user='postgres',
        password='postgres'
    )
    
    # 设置自动提交模式
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    
    # 创建游标
    cur = conn.cursor()
    
    # 创建admin用户
    print("创建admin用户...")
    cur.execute("CREATE USER admin WITH PASSWORD 'password' SUPERUSER;")
    print("admin用户创建成功！")
    
    # 创建hustle_db数据库
    print("创建hustle_db数据库...")
    cur.execute("CREATE DATABASE hustle_db OWNER admin;")
    print("hustle_db数据库创建成功！")
    
    # 关闭游标和连接
    cur.close()
    conn.close()
    
    print("所有操作完成！")
    
except Exception as e:
    print(f"错误: {e}")
    
    # 如果连接已经打开，关闭它
    if 'conn' in locals() and conn:
        conn.close()