"""Check all sub-account spot + margin balances using their own keys."""
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
                    print(f"  现货 {b['asset']}: free={b['free']}, locked={b['locked']}")
        except Exception as e:
            print(f"  现货错误: {e}")

        # Margin
        try:
            resp = await client._request("GET", f"{SPOT_BASE}/sapi/v1/margin/account", signed=True)
            level = resp.get("marginLevel", "N/A")
            total_net = float(resp.get("totalNetAssetOfBtc", 0))
            print(f"  杠杆 marginLevel={level}, totalNetBTC={total_net:.6f}")
            for ai in resp.get("userAssets", []):
                net = float(ai.get("netAsset", 0))
                borrowed = float(ai.get("borrowed", 0))
                free = float(ai.get("free", 0))
                interest = float(ai.get("interest", 0))
                if abs(net) > 0.0001 or borrowed > 0.0001 or free > 0.0001:
                    print(f"    {ai['asset']}: free={ai['free']}, borrowed={ai['borrowed']}, interest={ai['interest']}, net={ai['netAsset']}")
        except Exception as e:
            print(f"  杠杆错误: {e}")

        # Futures
        try:
            resp = await client._request("GET", f"{FUTURES_BASE}/fapi/v2/account", signed=True)
            total = resp.get("totalWalletBalance", "0")
            avail = resp.get("availableBalance", "0")
            pnl = resp.get("totalUnrealizedProfit", "0")
            print(f"  合约 total={total}, available={avail}, unrealizedPnl={pnl}")
        except Exception as e:
            print(f"  合约: 无权限或未开通")
    print()


async def main():
    db = SessionLocal()
    accounts = db.query(SubAccount).order_by(SubAccount.id).all()
    db.close()

    for acc in accounts:
        await check_one(acc)


asyncio.run(main())
