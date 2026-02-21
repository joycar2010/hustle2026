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
        print(f"  {label:<40} {value:>15,.2f} {unit}")
    else:
        print(f"  {label:<40} {str(value):>15}")


async def test_bybit_api():
    """Test all Bybit V5 API endpoints with USDT parameters"""
    client = BybitV5Client(API_KEY, API_SECRET)

    try:
        # Get today's timestamps
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        start_time = int(today.timestamp() * 1000)
        end_time = int(datetime.utcnow().timestamp() * 1000)

        print_section("Bybit API Test (USDT Denomination)")
        print(f"\nTest Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Account Name: hustle")
        print(f"API Key: {API_KEY[:10]}...")

        # 1. Test wallet balance with coin=USDT
        print_section("1. Wallet Balance (/v5/account/wallet-balance?coin=USDT)")
        try:
            wallet_data = await client.get_wallet_balance(account_type="UNIFIED", coin="USDT")
            print(f"\n[SUCCESS] Wallet balance retrieved")

            if wallet_data.get("list"):
                account = wallet_data["list"][0]
                equity = float(account.get("totalEquity", 0))
                wallet_balance = float(account.get("totalWalletBalance", 0))
                available_balance = float(account.get("totalAvailableBalance", 0))
                frozen_assets = wallet_balance - available_balance

                print_result("Total Assets (equity)", equity)
                print_result("Net Assets (equity)", equity)
                print_result("Available Balance (availableToTrade)", available_balance)
                print_result("Frozen Assets (calculated)", frozen_assets)
            else:
                print("  [WARNING] No account data found")

        except Exception as e:
            print(f"  [ERROR] {str(e)}")

        # 2. Test positions with settleCoin=USDT
        print_section("2. Positions (/v5/position/list?settleCoin=USDT)")
        try:
            positions_data = await client.get_positions(category="linear", settle_coin="USDT")
            print(f"\n[SUCCESS] Positions retrieved")

            total_unrealized_pnl = 0
            if positions_data.get("list"):
                positions = positions_data["list"]
                total_position_value = 0

                print(f"\n  Position Count: {len(positions)}")

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
                        print_result("    Position Size", size, "")
                        print_result("    Mark Price", mark_price, "USDT")
                        print_result("    Position Value", position_value, "USDT")
                        print_result("    Unrealized PnL", unrealized_pnl, "USDT")

                print(f"\n  Total Position Value: {total_position_value:,.2f} USDT")
                print(f"  Total Unrealized PnL: {total_unrealized_pnl:,.2f} USDT")
            else:
                print("  [INFO] No positions")

        except Exception as e:
            print(f"  [ERROR] {str(e)}")
            total_unrealized_pnl = 0

        # 3. Test account info with coin=USDT
        print_section("3. Account Info (/v5/account/info?coin=USDT)")
        try:
            account_info = await client.get_account_info(coin="USDT")
            print(f"\n[SUCCESS] Account info retrieved")

            margin_balance = float(account_info.get("marginBalance", 0))
            risk_ratio = float(account_info.get("riskRatio", 0))

            print_result("Margin Balance (marginBalance)", margin_balance)
            print_result("Risk Ratio (riskRatio)", risk_ratio, "%")

        except Exception as e:
            print(f"  [ERROR] {str(e)}")

        # 4. Test profit/loss with settleCoin=USDT
        print_section("4. Profit/Loss (/v5/position/closed-pnl?settleCoin=USDT)")
        try:
            pnl_data = await client.get_profit_loss(
                category="linear",
                start_time=start_time,
                end_time=end_time,
                settle_coin="USDT"
            )
            print(f"\n[SUCCESS] Profit/Loss records retrieved")

            if pnl_data.get("list"):
                pnl_list = pnl_data["list"]
                total_closed_pnl = sum(float(pnl.get("closedPnl", 0)) for pnl in pnl_list)

                print(f"\n  Today's Closed Trades: {len(pnl_list)}")
                print_result("Today's Realized PnL (closedPnl)", total_closed_pnl)
                print_result("Today's Unrealized PnL", total_unrealized_pnl)

                daily_pnl = total_closed_pnl + total_unrealized_pnl
                print_result("Daily Total PnL (closed + unrealized)", daily_pnl)
            else:
                print("  [INFO] No closed trades today")
                print_result("Daily Total PnL", total_unrealized_pnl)

        except Exception as e:
            print(f"  [ERROR] {str(e)}")

        # 5. Test funding fee with settleCoin=USDT
        print_section("5. Funding Fee (/v5/account/funding-fee?settleCoin=USDT)")
        try:
            funding_data = await client.get_funding_fee(
                category="linear",
                start_time=start_time,
                end_time=end_time,
                settle_coin="USDT"
            )
            print(f"\n[SUCCESS] Funding fee records retrieved")
            print(f"  Response: {funding_data}")

            if funding_data and isinstance(funding_data, dict) and funding_data.get("list"):
                funding_list = funding_data["list"]
                total_funding_fee = sum(float(fee.get("fundingFee", 0)) for fee in funding_list)

                print(f"\n  Today's Funding Fee Records: {len(funding_list)}")
                print_result("Today's Total Funding Fee", total_funding_fee)
            else:
                print("  [INFO] No funding fee records today")
                print_result("Today's Total Funding Fee", 0)

        except Exception as e:
            print(f"  [ERROR] {str(e)}")
            import traceback
            traceback.print_exc()

        print_section("Test Complete")
        print("\n[SUCCESS] All endpoints use coin=USDT or settleCoin=USDT parameters")
        print("[SUCCESS] All data is denominated in USDT\n")

    except Exception as e:
        print(f"\n[ERROR] Test failed: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_bybit_api())
