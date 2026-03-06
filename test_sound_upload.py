"""测试声音文件上传和同步功能"""
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
from app.services.feishu_service import FeishuService


async def main():
    # 连接数据库获取飞书配置
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
        from sqlalchemy import text
        result = await session.execute(
            text("SELECT config_data FROM notification_configs WHERE service_type = 'feishu' LIMIT 1")
        )
        row = result.fetchone()

        if not row:
            print("No Feishu config found")
            return

        config_data = row[0]
        app_id = config_data.get("app_id")
        app_secret = config_data.get("app_secret")

        if not app_id or not app_secret:
            print("Error: app_id or app_secret not found")
            return

        # 初始化飞书服务
        feishu = FeishuService(app_id=app_id, app_secret=app_secret)

        # 测试上传音频文件
        print("\n=== 测试音频文件上传 ===")

        # 创建一个测试音频文件（如果不存在）
        sounds_dir = "frontend/public/sounds"
        os.makedirs(sounds_dir, exist_ok=True)

        test_file = os.path.join(sounds_dir, "test_alert.txt")
        if not os.path.exists(test_file):
            with open(test_file, "w") as f:
                f.write("This is a test audio file placeholder")
            print(f"Created test file: {test_file}")

        # 列出所有声音文件
        print(f"\n声音文件目录: {sounds_dir}")
        if os.path.exists(sounds_dir):
            files = [f for f in os.listdir(sounds_dir) if f.endswith(('.mp3', '.wav', '.ogg', '.opus', '.txt'))]
            print(f"找到 {len(files)} 个文件:")
            for f in files:
                file_path = os.path.join(sounds_dir, f)
                file_size = os.path.getsize(file_path)
                print(f"  - {f} ({file_size} bytes)")
        else:
            print("目录不存在")

        print("\n提示: 请手动上传真实的音频文件到 frontend/public/sounds/ 目录")
        print("支持的格式: MP3, WAV, OGG, OPUS")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
