"""测试获取飞书用户信息"""
import asyncio
import sys
import os
from dotenv import load_dotenv

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

# 加载 backend 目录下的环境变量
load_dotenv(os.path.join(os.path.dirname(__file__), 'backend', '.env'))

from app.services.feishu_service import FeishuService


async def main():
    # 从环境变量读取飞书配置
    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")

    if not app_id or not app_secret:
        print("Error: FEISHU_APP_ID or FEISHU_APP_SECRET not found")
        return

    # 初始化飞书服务
    feishu = FeishuService(app_id=app_id, app_secret=app_secret)

    # 查询手机号对应的用户信息
    mobile = "19906779799"
    print(f"Querying mobile: {mobile}")

    result = await feishu.get_user_by_mobile(mobile)

    if result.get("success"):
        user = result.get("user", {})
        print("\nUser Info:")
        print(f"  Open ID: {user.get('open_id')}")
        print(f"  User ID: {user.get('user_id')}")
        print(f"  Union ID: {user.get('union_id')}")
        print(f"  Name: {user.get('name')}")
        print(f"  EN Name: {user.get('en_name')}")
        print(f"  Email: {user.get('email')}")
        print(f"  Mobile: {user.get('mobile')}")
        print(f"  Department IDs: {user.get('department_ids')}")
        print(f"  Is Activated: {user.get('status', {}).get('is_activated')}")
        print("\nFull Data:")
        import json
        print(json.dumps(user, indent=2, ensure_ascii=False))
    else:
        print(f"Query failed: {result.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())
