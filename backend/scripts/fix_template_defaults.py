#!/usr/bin/env python3
"""为所有模板添加默认的alert_sound、repeat_count、is_enabled值"""
import asyncio
import sys
import os
import io

# 设置UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import select, update
from app.core.database import AsyncSessionLocal
from app.models.notification_config import NotificationTemplate


async def fix_defaults():
    """为所有模板添加默认值"""
    async with AsyncSessionLocal() as db:
        # 查询所有模板
        result = await db.execute(select(NotificationTemplate))
        templates = result.scalars().all()

        print(f"\n找到 {len(templates)} 个模板\n")

        for t in templates:
            updated = False

            # 如果alert_sound为None，设置为空字符串
            if t.alert_sound is None:
                t.alert_sound = ""
                updated = True

            # 如果repeat_count为None，设置为3
            if t.repeat_count is None:
                t.repeat_count = 3
                updated = True

            # is_active字段已存在，不需要修改

            if updated:
                print(f"更新模板: {t.template_name}")
                print(f"  - alert_sound: {t.alert_sound}")
                print(f"  - repeat_count: {t.repeat_count}")
                print(f"  - is_active: {t.is_active}")

        await db.commit()
        print(f"\n所有模板已更新")


if __name__ == "__main__":
    asyncio.run(fix_defaults())
