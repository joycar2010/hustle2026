"""从数据库获取飞书配置并查询用户信息"""
import asyncio
import sys
import os
from dotenv import load_dotenv

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

# 加载 backend 目录下的环境变量
load_dotenv(os.path.join(os.path.dirname(__file__), 'backend', '.env'))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
from app.services.feishu_service import FeishuService


async def main():
    # 连接数据库
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL not found")
        return

    # 转换为异步 URL
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 查询飞书配置
        result = await session.execute(
            text("SELECT service_type, config_data FROM notification_configs WHERE service_type = 'feishu' LIMIT 1")
        )
        row = result.fetchone()

        if not row:
            print("No Feishu config found in database")
            return

        import json
        config_data = row[1]
        print(f"Feishu config from database: {json.dumps(config_data, indent=2, ensure_ascii=False)}")

        # 获取 app_id 和 app_secret
        app_id = config_data.get("app_id")
        app_secret = config_data.get("app_secret")

        if not app_id or not app_secret:
            print("Error: app_id or app_secret not found in config")
            return

        # 初始化飞书服务
        feishu = FeishuService(app_id=app_id, app_secret=app_secret)

        # 查询手机号对应的用户信息
        mobile = "19906779799"
        print(f"\nQuerying mobile: {mobile}")

        user_result = await feishu.get_user_by_mobile(mobile)

        if user_result.get("success"):
            user = user_result.get("user", {})
            print("\n=== User Info ===")
            print(f"Open ID: {user.get('open_id')}")
            print(f"User ID: {user.get('user_id')}")
            print(f"Union ID: {user.get('union_id')}")
            print(f"Name: {user.get('name')}")
            print(f"EN Name: {user.get('en_name')}")
            print(f"Email: {user.get('email')}")
            print(f"Mobile: {user.get('mobile')}")
            print(f"Department IDs: {user.get('department_ids')}")
            print(f"Is Activated: {user.get('status', {}).get('is_activated')}")
            print("\n=== Full Data ===")
            print(json.dumps(user, indent=2, ensure_ascii=False))
        else:
            print(f"Query failed: {user_result.get('error')}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
