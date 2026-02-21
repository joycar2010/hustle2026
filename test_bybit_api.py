"""Test Bybit API integration"""
import asyncio
import sys
from datetime import datetime

# Add backend to path
sys.path.insert(0, 'backend')

from app.services.bybit_client import BybitV5Client

# Bybit API credentials
API_KEY = "KWL699v3EhZBVxzKOg"
API_SECRET = "EiOw3inPLTVFrTmi0s2zEtTztWmuKfqGvSUg"


def print_section(title):
    """Print a section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_result(label, value, unit="USDT"):
    """Print a result with formatting"""
    if isinstance(value, (int, float)):
        print(f"  {label:<30} {value:>15,.2f} {unit}")
    else:
        print(f"  {label:<30} {str(value):>15}")


async def test_bybit_api():
    """Test all Bybit V5 API endpoints with USDT parameters"""
    client = BybitV5Client(API_KEY, API_SECRET)

    try:
        # Get today's timestamps
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        start_time = int(today.timestamp() * 1000)
        end_time = int(datetime.utcnow().timestamp() * 1000)

        print_section("Bybit API 测试 (USDT计价)")
        print(f"\n测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"账户名称: hustle")
        print(f"API Key: {API_KEY[:10]}...")

        # 1. Test wallet balance with coin=USDT
        print_section("1. 钱包余额 (/v5/account/wallet-balance?coin=USDT)")
        try:
            wallet_data = await client.get_wallet_balance(account_type="UNIFIED", coin="USDT")
            print(f"\n✓ 成功获取钱包余额")

            if wallet_data.get("list"):
                account = wallet_data["list"][0]
                equity = float(account.get("totalEquity", 0))
                wallet_balance = float(account.get("totalWalletBalance", 0))
                available_balance = float(account.get("totalAvailableBalance", 0))
                frozen_assets = wallet_balance - available_balance

                print_result("账户总资产 (equity)", equity)
                print_result("净资产 (equity)", equity)
                print_result("可用总资产 (availableToTrade)", available_balance)
                print_result("冻结资产 (calculated)", frozen_assets)
            else:
                print("  ⚠ 未找到账户数据")

        except Exception as e:
            print(f"  ✗ 错误: {str(e)}")

        # 2. Test positions with settleCoin=USDT
        print_section("2. 持仓信息 (/v5/position/list?settleCoin=USDT)")
        try:
            positions_data = await client.get_positions(category="linear", settle_coin="USDT")
            print(f"\n✓ 成功获取持仓信息")

            if positions_data.get("list"):
                positions = positions_data["list"]
                total_position_value = 0
                total_unrealized_pnl = 0

                print(f"\n  持仓数量: {len(positions)}")

                for pos in positions:
                    symbol = pos.get("symbol", "")
                    size = float(pos.get("size", 0))
                    mark_price = float(pos.get("markPrice", 0))
                    unrealized_pnl = float(pos.get("unrealisedPnl", 0))

                    position_value = abs(size * mark_price)
                    total_position_value += position_value
                    total_unrealized_pnl += unrealized_pnl

                    if size != 0:
                        print(f"\n  {symbol}:")
                        print_result("    持仓大小", size, "")
                        print_result("    标记价格", mark_price, "USDT")
                        print_result("    持仓价值", position_value, "USDT")
                        print_result("    未实现盈亏", unrealized_pnl, "USDT")

                print(f"\n  总持仓价值: {total_position_value:,.2f} USDT")
                print(f"  总未实现盈亏: {total_unrealized_pnl:,.2f} USDT")
            else:
                print("  ⚠ 无持仓")
                total_unrealized_pnl = 0

        except Exception as e:
            print(f"  ✗ 错误: {str(e)}")
            total_unrealized_pnl = 0

        # 3. Test account info with coin=USDT
        print_section("3. 账户信息 (/v5/account/info?coin=USDT)")
        try:
            account_info = await client.get_account_info(coin="USDT")
            print(f"\n✓ 成功获取账户信息")

            margin_balance = float(account_info.get("marginBalance", 0))
            risk_ratio = float(account_info.get("riskRatio", 0))

            print_result("保证金余额 (marginBalance)", margin_balance)
            print_result("风险率 (riskRatio)", risk_ratio, "%")

        except Exception as e:
            print(f"  ✗ 错误: {str(e)}")

        # 4. Test profit/loss with settleCoin=USDT
        print_section("4. 盈亏记录 (/v5/position/closed-pnl?settleCoin=USDT)")
        try:
            pnl_data = await client.get_profit_loss(
                category="linear",
                start_time=start_time,
                end_time=end_time,
                settle_coin="USDT"
            )
            print(f"\n✓ 成功获取盈亏记录")

            if pnl_data.get("list"):
                pnl_list = pnl_data["list"]
                total_closed_pnl = sum(float(pnl.get("closedPnl", 0)) for pnl in pnl_list)

                print(f"\n  今日平仓记录数: {len(pnl_list)}")
                print_result("今日已实现盈亏 (closedPnl)", total_closed_pnl)
                print_result("今日未实现盈亏 (unrealizedPnl)", total_unrealized_pnl)

                daily_pnl = total_closed_pnl + total_unrealized_pnl
                print_result("当日总盈亏 (closedPnl + unrealizedPnl)", daily_pnl)
            else:
                print("  ⚠ 今日无平仓记录")
                print_result("当日总盈亏", total_unrealized_pnl)

        except Exception as e:
            print(f"  ✗ 错误: {str(e)}")

        # 5. Test funding fee with settleCoin=USDT
        print_section("5. 资金费 (/v5/account/funding-fee?settleCoin=USDT)")
        try:
            funding_data = await client.get_funding_fee(
                category="linear",
                start_time=start_time,
                end_time=end_time,
                settle_coin="USDT"
            )
            print(f"\n✓ 成功获取资金费记录")

            if funding_data.get("list"):
                funding_list = funding_data["list"]
                total_funding_fee = sum(float(fee.get("fundingFee", 0)) for fee in funding_list)

                print(f"\n  今日资金费记录数: {len(funding_list)}")
                print_result("今日资金费总额 (fundingFee)", total_funding_fee)
            else:
                print("  ⚠ 今日无资金费记录")
                print_result("今日资金费总额", 0)

        except Exception as e:
            print(f"  ✗ 错误: {str(e)}")

        print_section("测试完成")
        print("\n✓ 所有接口均使用 coin=USDT 或 settleCoin=USDT 参数")
        print("✓ 所有数据均以 USDT 计价\n")

    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_bybit_api())
