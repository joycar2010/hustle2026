"""
测试模板更新功能
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
from datetime import datetime

async def test_update():
    """测试更新模板"""
    async with AsyncSessionLocal() as db:
        try:
            # 获取第一个模板
            result = await db.execute(
                select(NotificationTemplate).limit(1)
            )
            template = result.scalar_one_or_none()

            if not template:
                print("没有找到模板")
                return

            print(f"\n更新前:")
            print(f"模板: {template.template_name}")
            print(f"  - alert_sound: {template.alert_sound}")
            print(f"  - repeat_count: {template.repeat_count}")
            print(f"  - is_active: {template.is_active}")

            # 更新模板
            template.alert_sound = "test_sound.mp3"
            template.repeat_count = 5
            template.updated_at = datetime.utcnow()

            await db.commit()
            await db.refresh(template)

            print(f"\n更新后:")
            print(f"模板: {template.template_name}")
            print(f"  - alert_sound: {template.alert_sound}")
            print(f"  - repeat_count: {template.repeat_count}")
            print(f"  - is_active: {template.is_active}")

            # 恢复原值
            template.alert_sound = None
            template.repeat_count = 3
            await db.commit()

            print(f"\n已恢复原值")

        except Exception as e:
            print(f"错误: {e}")
            import traceback
            traceback.print_exc()
            await db.rollback()
            raise

if __name__ == "__main__":
    asyncio.run(test_update())
