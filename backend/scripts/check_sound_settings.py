#!/usr/bin/env python3
"""检查所有模板的声音设置"""
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


async def check_all_templates():
    """检查所有模板的声音设置"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(NotificationTemplate).order_by(NotificationTemplate.template_name)
        )
        templates = result.scalars().all()

        print(f"\n找到 {len(templates)} 个模板\n")
        print("=" * 80)

        for t in templates:
            print(f"\n模板: {t.template_name}")
            print(f"  - template_id: {t.template_id}")
            print(f"  - alert_sound: {t.alert_sound} (类型: {type(t.alert_sound).__name__})")
            print(f"  - repeat_count: {t.repeat_count}")
            print(f"  - is_active: {t.is_active}")
            print(f"  - updated_at: {t.updated_at}")

        print("\n" + "=" * 80)
        print("\n有声音设置的模板:")
        has_sound = [t for t in templates if t.alert_sound]
        if has_sound:
            for t in has_sound:
                print(f"  - {t.template_name}: {t.alert_sound} ({t.repeat_count}次)")
        else:
            print("  (无)")


if __name__ == "__main__":
    asyncio.run(check_all_templates())
