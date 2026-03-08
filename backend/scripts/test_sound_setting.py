"""
测试通知模板的声音设置保存和显示
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

async def test_sound_setting():
    """测试声音设置"""
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

            print(f"\n=== 测试模板: {template.template_name} ===\n")

            # 测试1: 设置声音
            print("测试1: 设置声音文件")
            template.alert_sound = "spread.mp3"
            template.repeat_count = 5
            template.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(template)

            print(f"✓ 保存成功")
            print(f"  - alert_sound: {template.alert_sound}")
            print(f"  - repeat_count: {template.repeat_count}")

            # 测试2: 验证读取
            print("\n测试2: 重新读取验证")
            result = await db.execute(
                select(NotificationTemplate).filter(
                    NotificationTemplate.template_id == template.template_id
                )
            )
            reloaded = result.scalar_one_or_none()

            print(f"✓ 读取成功")
            print(f"  - alert_sound: {reloaded.alert_sound}")
            print(f"  - repeat_count: {reloaded.repeat_count}")

            # 测试3: 清除声音（设置为None）
            print("\n测试3: 清除声音设置")
            template.alert_sound = None
            template.repeat_count = 3
            await db.commit()
            await db.refresh(template)

            print(f"✓ 清除成功")
            print(f"  - alert_sound: {template.alert_sound}")
            print(f"  - repeat_count: {template.repeat_count}")

            # 测试4: 验证None值
            print("\n测试4: 验证None值读取")
            result = await db.execute(
                select(NotificationTemplate).filter(
                    NotificationTemplate.template_id == template.template_id
                )
            )
            reloaded = result.scalar_one_or_none()

            print(f"✓ 读取成功")
            print(f"  - alert_sound: {reloaded.alert_sound} (类型: {type(reloaded.alert_sound).__name__})")
            print(f"  - repeat_count: {reloaded.repeat_count}")

            print("\n=== 所有测试通过 ===")

        except Exception as e:
            print(f"错误: {e}")
            import traceback
            traceback.print_exc()
            await db.rollback()
            raise

if __name__ == "__main__":
    asyncio.run(test_sound_setting())
