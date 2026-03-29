"""
实时监控通知模板API调用
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

async def monitor_template(template_key="total_net_asset_alert"):
    """监控特定模板的变化"""
    async with AsyncSessionLocal() as db:
        try:
            print(f"\n=== 监控模板: {template_key} ===\n")

            # 查找模板
            result = await db.execute(
                select(NotificationTemplate).filter(
                    NotificationTemplate.template_key == template_key
                )
            )
            template = result.scalar_one_or_none()

            if not template:
                print(f"未找到模板: {template_key}")
                return

            print(f"模板名称: {template.template_name}")
            print(f"模板ID: {template.template_id}")
            print(f"\n当前设置:")
            print(f"  - alert_sound: {template.alert_sound}")
            print(f"  - repeat_count: {template.repeat_count}")
            print(f"  - is_active: {template.is_active}")
            print(f"  - updated_at: {template.updated_at}")

            print(f"\n请在浏览器中编辑此模板并保存...")
            print(f"按Ctrl+C停止监控\n")

            last_updated = template.updated_at

            while True:
                await asyncio.sleep(2)

                # 重新查询
                result = await db.execute(
                    select(NotificationTemplate).filter(
                        NotificationTemplate.template_key == template_key
                    )
                )
                template = result.scalar_one_or_none()

                if template.updated_at != last_updated:
                    print(f"\n[{template.updated_at}] 检测到更新!")
                    print(f"  - alert_sound: {template.alert_sound}")
                    print(f"  - repeat_count: {template.repeat_count}")
                    print(f"  - is_active: {template.is_active}")
                    last_updated = template.updated_at

        except KeyboardInterrupt:
            print("\n\n监控已停止")
        except Exception as e:
            print(f"错误: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(monitor_template())
