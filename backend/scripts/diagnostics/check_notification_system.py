import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check_notification_system():
    """Check notification templates and Feishu configuration"""
    engine = create_async_engine(
        'postgresql+asyncpg://postgres:postgres@localhost/postgres'
    )

    try:
        async with engine.begin() as conn:
            # Check Feishu configuration
            print("="*60)
            print("Feishu Service Configuration")
            print("="*60)
            result = await conn.execute(text("""
                SELECT service_type, is_enabled, config_data
                FROM notification_configs
                WHERE service_type = 'feishu'
            """))
            row = result.fetchone()
            if row:
                print(f"Service Type: {row[0]}")
                print(f"Enabled: {'YES' if row[1] else 'NO'}")
                print(f"Config: {row[2]}")
            else:
                print("[WARNING] Feishu service not configured")

            # Check all notification templates
            print("\n" + "="*60)
            print("Notification Templates")
            print("="*60)
            result = await conn.execute(text("""
                SELECT
                    template_key,
                    template_name,
                    category,
                    enable_feishu,
                    priority,
                    cooldown_seconds,
                    is_active
                FROM notification_templates
                ORDER BY category, priority DESC
            """))

            templates = result.fetchall()
            print(f"\nTotal {len(templates)} templates:\n")

            for t in templates:
                status = "ACTIVE" if t[6] else "INACTIVE"
                feishu = "YES" if t[3] else "NO"
                print(f"[{status:8}] [{t[2]:8}] Priority:{t[4]} Cooldown:{t[5]}s Feishu:{feishu}")
                print(f"  Key: {t[0]}")

            # Check risk settings
            print("\n" + "="*60)
            print("Risk Control Thresholds")
            print("="*60)
            result = await conn.execute(text("""
                SELECT
                    user_id,
                    binance_net_asset_threshold,
                    bybit_net_asset_threshold,
                    total_net_asset_threshold,
                    forward_open_threshold,
                    forward_close_threshold,
                    reverse_open_threshold,
                    reverse_close_threshold,
                    mt5_lag_threshold
                FROM risk_settings
            """))

            settings = result.fetchall()
            if settings:
                for s in settings:
                    print(f"\nUser ID: {s[0]}")
                    print(f"  Binance Net Asset Threshold: {s[1]} USDT")
                    print(f"  Bybit Net Asset Threshold: {s[2]} USDT")
                    print(f"  Total Net Asset Threshold: {s[3]} USDT")
                    print(f"  Forward Open Threshold: {s[4]} USDT")
                    print(f"  Forward Close Threshold: {s[5]} USDT")
                    print(f"  Reverse Open Threshold: {s[6]} USDT")
                    print(f"  Reverse Close Threshold: {s[7]} USDT")
                    print(f"  MT5 Lag Threshold: {s[8]} times")
            else:
                print("[WARNING] No risk settings found")

            # Check recent notification logs
            print("\n" + "="*60)
            print("Recent Notification Logs (Last 10)")
            print("="*60)
            result = await conn.execute(text("""
                SELECT
                    template_key,
                    service_type,
                    status,
                    created_at
                FROM notification_logs
                ORDER BY created_at DESC
                LIMIT 10
            """))

            logs = result.fetchall()
            if logs:
                for log in logs:
                    print(f"{log[3]} | {log[0]:30} | {log[1]:8} | {log[2]}")
            else:
                print("[INFO] No notification logs yet")

    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_notification_system())
