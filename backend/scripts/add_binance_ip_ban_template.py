"""Migration: insert binance_ip_ban_alert notification template"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://postgres:Lk106504@127.0.0.1:5432/postgres"


async def run():
    engine = create_async_engine(DB_URL)
    try:
        async with engine.begin() as conn:
            # Check if already exists
            result = await conn.execute(text(
                "SELECT COUNT(*) FROM notification_templates WHERE template_key = 'binance_ip_ban_alert'"
            ))
            if result.scalar() > 0:
                print("Template 'binance_ip_ban_alert' already exists — skipping.")
                return

            await conn.execute(text("""
                INSERT INTO notification_templates (
                    template_key,
                    template_name,
                    category,
                    title_template,
                    content_template,
                    popup_title_template,
                    popup_content_template,
                    alert_sound_file,
                    alert_sound_repeat,
                    priority,
                    cooldown_seconds,
                    is_active,
                    enable_feishu,
                    enable_email,
                    enable_sms
                ) VALUES (
                    'binance_ip_ban_alert',
                    'Binance IP封禁告警',
                    'risk',
                    '⛔ Binance IP被封禁',
                    '服务器IP {ip} 因请求频率过高已被Binance封禁\n解禁时间: {ban_until_time} (北京时间)\n剩余时间: {remaining_time}\n请检查API调用频率，优先使用WebSocket替代REST轮询',
                    '⛔ Binance IP封禁',
                    'IP {ip} 已被封禁\n解禁: {ban_until_time}\n剩余: {remaining_time}',
                    '/sounds/hello-moto.mp3',
                    5,
                    4,
                    600,
                    true,
                    true,
                    false,
                    false
                )
            """))
            print("Template 'binance_ip_ban_alert' inserted successfully.")
            print("  Priority:        4 (critical)")
            print("  Cooldown:        600s (10 minutes)")
            print("  Sound repeat:    5 times")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
