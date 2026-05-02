"""Check sub-account balances - handles both UTA and legacy modes."""
import asyncio
import sys
sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")

from app.db.session import SessionLocal
from app.db.models import SubAccount
from engine.trading.binance_trading import BinanceTradingClient, SPOT_BASE, FUTURES_BASE


async def check_one(acc):
    print(f"=== ID={acc.id} | {acc.note} | {acc.email} ===")
    async with BinanceTradingClient(acc.api_key, acc.api_secret) as client:
        # Spot
        try:
            resp = await client._request("GET", f"{SPOT_BASE}/api/v3/account", signed=True)
            for b in resp.get("balances", []):
                free = float(b["free"])
                locked = float(b["locked"])
                if free > 0.0001 or locked > 0.0001:
                    asset = b['asset']
                    print(f"  现货 {asset}: free={b['free']}, locked={b['locked']}")
        except Exception as e:
            print(f"  现货错误: {e}")

        # Margin (cross)
        try:
            resp = await client._request("GET", f"{SPOT_BASE}/sapi/v1/margin/account", signed=True)
            level = resp.get("marginLevel", "N/A")
            print(f"  杠杆 marginLevel={level}")
            for ai in resp.get("userAssets", []):
                net = float(ai.get("netAsset", 0))
                borrowed = float(ai.get("borrowed", 0))
                free_a = float(ai.get("free", 0))
                if abs(net) > 0.0001 or borrowed > 0.0001 or free_a > 0.0001:
                    asset = ai['asset']
                    print(f"    {asset}: free={ai['free']}, borrowed={ai['borrowed']}, net={ai['netAsset']}")
        except Exception as e:
            print(f"  杠杆错误: {e}")

        # Futures - try legacy first, then UTA
        try:
            resp = await client._request("GET", f"{FUTURES_BASE}/fapi/v2/account", signed=True)
            total = resp.get("totalWalletBalance", "0")
            avail = resp.get("availableBalance", "0")
            pnl = resp.get("totalUnrealizedProfit", "0")
            print(f"  合约(legacy) total={total}, available={avail}, unrealizedPnl={pnl}")
        except Exception as e:
            print(f"  合约(legacy): {e}")

        # UTA: /fapi/v3/account
        try:
            resp = await client._request("GET", f"{FUTURES_BASE}/fapi/v3/account", signed=True)
            total = resp.get("totalWalletBalance", "0")
            avail = resp.get("availableBalance", "0")
            pnl = resp.get("totalUnrealizedProfit", "0")
            print(f"  合约(UTA v3) total={total}, available={avail}, unrealizedPnl={pnl}")
        except Exception as e:
            print(f"  合约(UTA v3): {e}")

        # UTA: /fapi/v2/balance
        try:
            resp = await client._request("GET", f"{FUTURES_BASE}/fapi/v2/balance", signed=True)
            for b in resp:
                bal = float(b.get("balance", 0))
                avail_b = float(b.get("availableBalance", 0))
                if bal > 0.001 or avail_b > 0.001:
                    asset = b['asset']
                    print(f"  合约余额 {asset}: balance={b['balance']}, available={b['availableBalance']}")
        except Exception as e:
            print(f"  合约余额: {e}")

        # Account status / API trading status
        try:
            resp = await client._request("GET", f"{SPOT_BASE}/sapi/v1/account/apiTradingStatus", signed=True)
            data = resp.get("data", resp)
            locked = data.get("isLocked", False)
            print(f"  API交易状态: isLocked={locked}")
        except Exception as e:
            print(f"  API状态: {e}")

    print()


async def main():
    db = SessionLocal()
    accounts = db.query(SubAccount).order_by(SubAccount.id).all()
    db.close()
    for acc in accounts:
        await check_one(acc)


asyncio.run(main())
