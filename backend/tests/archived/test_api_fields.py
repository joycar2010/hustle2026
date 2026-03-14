"""
Test if the API would return the correct fields
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.models.notification_config import NotificationTemplate

async def test_api_response():
    """Simulate API response"""
    engine = create_async_engine(
        'postgresql+asyncpg://postgres:postgres@localhost/postgres'
    )

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as db:
        result = await db.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.is_active == True
            ).order_by(NotificationTemplate.category, NotificationTemplate.priority.desc())
        )
        templates = result.scalars().all()

        print(f"Total templates: {len(templates)}\n")

        # Simulate API response format
        response_templates = []
        for t in templates:
            template_dict = {
                "template_id": str(t.template_id),
                "template_key": t.template_key,
                "template_name": t.template_name,
                "category": t.category,
                "title_template": t.title_template,
                "content_template": t.content_template,
                "enable_email": t.enable_email,
                "enable_sms": t.enable_sms,
                "enable_feishu": t.enable_feishu,
                "priority": t.priority,
                "cooldown_seconds": t.cooldown_seconds,
                # Old fields
                "alert_sound": t.alert_sound,
                "repeat_count": t.repeat_count,
                # New fields
                "alert_sound_file": t.alert_sound_file,
                "alert_sound_repeat": t.alert_sound_repeat,
                "popup_title_template": t.popup_title_template,
                "popup_content_template": t.popup_content_template,
                "is_enabled": t.is_active,
            }
            response_templates.append(template_dict)

        # Check single_leg_alert
        single_leg = next((t for t in response_templates if t['template_key'] == 'single_leg_alert'), None)
        if single_leg:
            print("single_leg_alert template:")
            print(f"  popup_title_template: {'[HAS VALUE]' if single_leg['popup_title_template'] else '[EMPTY]'}")
            print(f"  popup_content_template: {'[HAS VALUE]' if single_leg['popup_content_template'] else '[EMPTY]'}")
            print(f"  alert_sound_file: {'[HAS VALUE]' if single_leg['alert_sound_file'] else '[EMPTY]'}")
            print(f"  alert_sound_repeat: {single_leg['alert_sound_repeat']}")
            print()

        # Check binance_net_asset_alert
        binance_asset = next((t for t in response_templates if t['template_key'] == 'binance_net_asset_alert'), None)
        if binance_asset:
            print("binance_net_asset_alert template:")
            print(f"  popup_title_template: {'[HAS VALUE]' if binance_asset['popup_title_template'] else '[EMPTY]'}")
            print(f"  popup_content_template: {'[HAS VALUE]' if binance_asset['popup_content_template'] else '[EMPTY]'}")
            print(f"  alert_sound_file: {'[HAS VALUE]' if binance_asset['alert_sound_file'] else '[EMPTY]'}")
            print(f"  alert_sound_repeat: {binance_asset['alert_sound_repeat']}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test_api_response())
