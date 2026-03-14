import asyncio
from sqlalchemy import create_engine, text

def check_notification_system_sync():
    """Check notification system configuration synchronously"""
    engine = create_engine('postgresql://postgres:postgres@localhost/postgres')

    with engine.connect() as conn:
        # Check Feishu configuration
        print("="*60)
        print("Feishu Service Configuration")
        print("="*60)
        result = conn.execute(text("""
            SELECT service_type, is_enabled, config_data
            FROM notification_configs
            WHERE service_type = 'feishu'
        """))
        row = result.fetchone()
        if row:
            print(f"Service Type: {row[0]}")
            print(f"Enabled: {'YES' if row[1] else 'NO'}")
            print(f"Has Config: YES")
        else:
            print("[WARNING] Feishu service not configured")

        # Check all notification templates
        print("\n" + "="*60)
        print("Notification Templates (Risk Category)")
        print("="*60)
        result = conn.execute(text("""
            SELECT
                template_key,
                category,
                enable_feishu,
                priority,
                cooldown_seconds,
                is_active
            FROM notification_templates
            WHERE category = 'risk'
            ORDER BY priority DESC, template_key
        """))

        templates = result.fetchall()
        print(f"\nTotal {len(templates)} risk templates:\n")

        for t in templates:
            status = "[ACTIVE]" if t[5] else "[INACTIVE]"
            feishu = "Feishu:YES" if t[2] else "Feishu:NO"
            print(f"{status} {t[0]:35} Priority:{t[3]} Cooldown:{t[4]}s {feishu}")

        # Check risk settings
        print("\n" + "="*60)
        print("Risk Control Thresholds")
        print("="*60)
        result = conn.execute(text("""
            SELECT
                user_id,
                binance_net_asset,
                bybit_mt5_net_asset,
                total_net_asset,
                forward_open_price,
                forward_close_price,
                reverse_open_price,
                reverse_close_price,
                mt5_lag_count,
                binance_liquidation_price,
                bybit_mt5_liquidation_price
            FROM risk_settings
        """))

        settings = result.fetchall()
        if settings:
            for s in settings:
                print(f"\nUser ID: {s[0]}")
                print(f"  Binance Net Asset Threshold: {s[1]} USDT")
                print(f"  Bybit MT5 Net Asset Threshold: {s[2]} USDT")
                print(f"  Total Net Asset Threshold: {s[3]} USDT")
                print(f"  Forward Open Threshold: {s[4]} USDT")
                print(f"  Forward Close Threshold: {s[5]} USDT")
                print(f"  Reverse Open Threshold: {s[6]} USDT")
                print(f"  Reverse Close Threshold: {s[7]} USDT")
                print(f"  MT5 Lag Threshold: {s[8]} times")
                print(f"  Binance Liquidation Distance: {s[9]}%")
                print(f"  Bybit MT5 Liquidation Distance: {s[10]}%")
        else:
            print("[WARNING] No risk settings found")

        # Check recent notification logs
        print("\n" + "="*60)
        print("Recent Notification Logs (Last 10)")
        print("="*60)
        result = conn.execute(text("""
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

        # Summary
        print("\n" + "="*60)
        print("Summary")
        print("="*60)
        print(f"Feishu Service: {'ENABLED' if row and row[1] else 'DISABLED'}")
        print(f"Active Risk Templates: {len([t for t in templates if t[5]])}")
        print(f"Templates with Feishu: {len([t for t in templates if t[2]])}")
        print(f"Risk Settings Configured: {'YES' if settings else 'NO'}")
        print(f"Recent Notifications: {len(logs)}")

if __name__ == "__main__":
    check_notification_system_sync()
