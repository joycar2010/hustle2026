#!/usr/bin/env python3
"""测试通知模板API响应"""
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


async def test_api_response():
    """测试API响应格式"""
    async with AsyncSessionLocal() as db:
        # 获取第一个模板
        result = await db.execute(
            select(NotificationTemplate).limit(1)
        )
        template = result.scalar_one_or_none()

        if not template:
            print("没有找到模板")
            return

        print(f"\n=== 模板: {template.template_name} ===\n")

        # 模拟API响应格式
        api_response = {
            "template_id": str(template.template_id),
            "template_key": template.template_key,
            "template_name": template.template_name,
            "category": template.category,
            "title_template": template.title_template,
            "content_template": template.content_template,
            "enable_email": template.enable_email,
            "enable_sms": template.enable_sms,
            "enable_feishu": template.enable_feishu,
            "priority": template.priority,
            "cooldown_seconds": template.cooldown_seconds,
            "alert_sound": template.alert_sound,
            "repeat_count": template.repeat_count,
            "is_enabled": template.is_active,
            "updated_at": template.updated_at.isoformat() if template.updated_at else None
        }

        print("API响应格式:")
        import json
        print(json.dumps(api_response, indent=2, ensure_ascii=False))

        print("\n关键字段:")
        print(f"  - alert_sound: {api_response['alert_sound']} (类型: {type(api_response['alert_sound']).__name__})")
        print(f"  - repeat_count: {api_response['repeat_count']} (类型: {type(api_response['repeat_count']).__name__})")
        print(f"  - is_enabled: {api_response['is_enabled']} (类型: {type(api_response['is_enabled']).__name__})")


if __name__ == "__main__":
    asyncio.run(test_api_response())
