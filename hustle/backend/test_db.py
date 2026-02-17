from sqlalchemy.orm import Session
from app.core.database import engine, Base, get_db
from app.models import Account

# 创建所有表
print("创建所有表...")
Base.metadata.create_all(bind=engine)
print("表创建成功！")

# 测试添加账户
print("\n测试添加账户...")
db = next(get_db())
try:
    # 创建一个新账户
    new_account = Account(
        user_id="00000000-0000-0000-0000-000000000000",
        platform_id=1,
        account_name="test_account",
        api_key="test_api_key",
        api_secret="test_api_secret",
        is_active=True
    )
    
    # 添加到数据库
    db.add(new_account)
    db.commit()
    db.refresh(new_account)
    
    print(f"账户添加成功！账户ID: {new_account.account_id}")
    
    # 测试获取账户列表
    print("\n测试获取账户列表...")
    accounts = db.query(Account).all()
    print(f"账户数量: {len(accounts)}")
    for account in accounts:
        print(f"  账户ID: {account.account_id}, 账户名称: {account.account_name}")
    
    print("\n所有测试完成！")
    
except Exception as e:
    print(f"错误: {e}")
    db.rollback()
finally:
    db.close()