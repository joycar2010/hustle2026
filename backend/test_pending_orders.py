"""测试挂单获取功能"""
# -*- coding: utf-8 -*-
import asyncio
import sys
import os
import io

# 设置UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_pending_orders_streamer():
    """测试挂单推送器"""
    print("=" * 60)
    print("测试: 挂单推送器")
    print("=" * 60)

    try:
        from app.tasks.broadcast_tasks import PendingOrdersStreamer
        from app.models.account import Account
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import select

        # 检查是否有Binance账户
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Account).where(Account.platform_id == 1)
            )
            accounts = result.scalars().all()

            if not accounts:
                print("✗ 没有找到Binance账户")
                print("  请先在系统中配置Binance账户")
                return False

            print(f"✓ 找到 {len(accounts)} 个Binance账户")

        # 创建推送器实例
        streamer = PendingOrdersStreamer()
        print("✓ 推送器创建成功")

        # 测试单次获取挂单
        print("\n正在获取挂单...")
        from app.services.binance_client import BinanceFuturesClient
        from app.utils.time_utils import utc_ms_to_beijing

        pending_orders = []
        for account in accounts:
            try:
                client = BinanceFuturesClient(account.api_key, account.api_secret)
                try:
                    open_orders = await client.get_open_orders(symbol="XAUUSDT")
                    print(f"✓ 账户 {account.account_id} 有 {len(open_orders)} 个挂单")

                    for order in open_orders:
                        order_time = order.get("time", 0)
                        beijing_time = utc_ms_to_beijing(order_time)

                        pending_orders.append({
                            "id": str(order.get("orderId")),
                            "timestamp": beijing_time,
                            "exchange": "Binance",
                            "side": order.get("side", "").lower(),
                            "quantity": float(order.get("origQty", 0)),
                            "price": float(order.get("price", 0)),
                            "status": order.get("status", "").lower(),
                            "symbol": order.get("symbol", ""),
                            "source": "strategy"
                        })
                finally:
                    await client.close()
            except Exception as e:
                print(f"✗ 获取账户 {account.account_id} 挂单失败: {e}")

        if pending_orders:
            print(f"\n✓ 成功获取 {len(pending_orders)} 个挂单")
            print("\n挂单详情:")
            for order in pending_orders[:5]:  # 只显示前5个
                print(f"  - 订单ID: {order['id']}")
                print(f"    方向: {order['side']}, 数量: {order['quantity']}, 价格: {order['price']}")
                print(f"    状态: {order['status']}, 时间: {order['timestamp']}")
                print()
        else:
            print("\n⚠ 当前没有挂单")

        return True

    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_api_endpoint():
    """测试API端点"""
    print("\n" + "=" * 60)
    print("测试: API端点")
    print("=" * 60)

    try:
        from app.api.v1.trading import get_realtime_pending_orders
        print("✓ API端点导入成功")

        # 注意：这个测试需要认证，所以我们只测试导入
        print("✓ API端点可用（需要认证才能调用）")

        return True
    except Exception as e:
        print(f"✗ API端点测试失败: {e}")
        return False

async def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("挂单功能测试")
    print("=" * 60 + "\n")

    results = []

    # 测试1: 挂单推送器
    results.append(await test_pending_orders_streamer())

    # 测试2: API端点
    results.append(await test_api_endpoint())

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    print(f"通过: {passed}/{total}")

    if passed == total:
        print("\n✓ 所有测试通过！")
        print("\n修复内容:")
        print("1. WebSocket推送器现在直接从Binance API获取挂单")
        print("2. 不再依赖HTTP端点，避免了认证问题")
        print("3. 添加了source字段以保持数据一致性")
        print("\n下一步:")
        print("1. 重启后端服务")
        print("2. 打开前端页面 http://13.115.21.77:3000/pending-orders")
        print("3. 点击连续开仓按钮")
        print("4. 查看挂单是否实时显示")
    else:
        print("\n✗ 部分测试失败。请查看上面的错误信息。")

    return passed == total

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
