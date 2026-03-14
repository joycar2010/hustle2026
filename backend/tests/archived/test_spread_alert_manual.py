"""测试点差提醒功能"""
import asyncio
import sys
import io
from app.services.spread_alert_service import SpreadAlertService
from app.services.market_service import market_data_service
from app.models.risk_settings import RiskSettings
from app.core.database import AsyncSessionLocal
from sqlalchemy import select
import uuid

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def test_spread_alert():
    print("=" * 80)
    print("测试点差提醒功能")
    print("=" * 80)
    print()

    # Get current market data
    print("【1】获取当前市场数据")
    print("-" * 80)
    try:
        market_data = await market_data_service.get_current_spread()
        print(f"Forward Spread: {market_data.forward_spread:.4f}")
        print(f"Reverse Spread: {market_data.reverse_spread:.4f}")
        print()
    except Exception as e:
        print(f"❌ 获取市场数据失败: {e}")
        return

    # Get admin user risk settings
    print("【2】获取admin用户风险设置")
    print("-" * 80)
    admin_user_id = uuid.UUID('0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24')

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RiskSettings).filter(RiskSettings.user_id == admin_user_id)
        )
        risk_settings = result.scalar_one_or_none()

        if not risk_settings:
            print("❌ 未找到风险设置")
            return

        print(f"Forward Open: {risk_settings.forward_open_price}")
        print(f"Forward Close: {risk_settings.forward_close_price}")
        print(f"Reverse Open: {risk_settings.reverse_open_price}")
        print(f"Reverse Close: {risk_settings.reverse_close_price}")
        print()

        # Prepare alert settings
        alert_settings = {
            'forwardOpenPrice': risk_settings.forward_open_price,
            'forwardClosePrice': risk_settings.forward_close_price,
            'reverseOpenPrice': risk_settings.reverse_open_price,
            'reverseClosePrice': risk_settings.reverse_close_price,
        }

        # Prepare market data dict
        market_dict = {
            'forward_spread': market_data.forward_spread,
            'reverse_spread': market_data.reverse_spread,
        }

        # Check conditions
        print("【3】检查触发条件")
        print("-" * 80)
        forward_abs = abs(market_data.forward_spread)
        reverse_abs = abs(market_data.reverse_spread)

        print(f"正向开仓: {forward_abs:.4f} >= {alert_settings['forwardOpenPrice']} ? {forward_abs >= alert_settings['forwardOpenPrice']}")
        print(f"正向平仓: {forward_abs:.4f} <= {alert_settings['forwardClosePrice']} ? {forward_abs <= alert_settings['forwardClosePrice']}")
        print(f"反向开仓: {reverse_abs:.4f} >= {alert_settings['reverseOpenPrice']} ? {reverse_abs >= alert_settings['reverseOpenPrice']}")
        print(f"反向平仓: {reverse_abs:.4f} <= {alert_settings['reverseClosePrice']} ? {reverse_abs <= alert_settings['reverseClosePrice']}")
        print()

        # Test spread alert service
        print("【4】调用点差提醒服务")
        print("-" * 80)
        try:
            service = SpreadAlertService()
            await service.check_and_send_spread_alerts(
                db=db,
                user_id=str(admin_user_id),
                market_data=market_dict,
                alert_settings=alert_settings
            )
            print("✓ 点差提醒检查完成")
            print()
        except Exception as e:
            print(f"❌ 点差提醒检查失败: {e}")
            import traceback
            traceback.print_exc()
            print()

if __name__ == "__main__":
    asyncio.run(test_spread_alert())
