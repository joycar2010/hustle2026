"""
测试通知模板API功能
"""
import asyncio
import sys
import os
import io

# 设置UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.notification_config import NotificationTemplate

async def test_templates():
    """测试模板数据"""
    async with AsyncSessionLocal() as db:
        try:
            # 获取所有模板
            result = await db.execute(
                select(NotificationTemplate).limit(5)
            )
            templates = result.scalars().all()

            print(f"\n找到 {len(templates)} 个模板（显示前5个）:\n")

            for t in templates:
                print(f"模板: {t.template_name}")
                print(f"  - template_key: {t.template_key}")
                print(f"  - is_active: {t.is_active}")
                print(f"  - alert_sound: {t.alert_sound}")
                print(f"  - repeat_count: {t.repeat_count}")
                print(f"  - enable_feishu: {t.enable_feishu}")
                print()

        except Exception as e:
            print(f"错误: {e}")
            raise

if __name__ == "__main__":
    asyncio.run(test_templates())
