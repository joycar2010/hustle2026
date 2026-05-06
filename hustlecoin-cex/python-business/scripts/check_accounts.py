"""Check all sub-account balances via master API."""
import asyncio
import sys
sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")

from app.db.session import SessionLocal
from app.db.models import SubAccount, MasterAccount
from engine.trading.binance_trading import BinanceTradingClient, SPOT_BASE


async def main():
    db = SessionLocal()
    master = db.query(MasterAccount).first()
    accounts = db.query(SubAccount).order_by(SubAccount.id).all()
    db.close()

    async with BinanceTradingClient(master.api_key, master.api_secret) as client:
        for acc in accounts:
            print(f"=== ID={acc.id} | {acc.note} | {acc.email} ===")

            # Spot
            try:
                resp = await client._request(
                    "GET", f"{SPOT_BASE}/sapi/v3/sub-account/assets",
                    params={"email": acc.email}, signed=True,
                )
                balances = resp.get("balances", [])
                found = False
                for b in balances:
                    free = float(b.get("free", 0))
                    locked = float(b.get("locked", 0))
                    if free > 0.0001 or locked > 0.0001:
                        asset = b["asset"]
                        print(f"  现货 {asset}: free={b['free']}, locked={b['locked']}")
                        found = True
                if not found:
                    print("  现货: (空)")
            except Exception as e:
                print(f"  现货查询错误: {e}")

            # Margin
            try:
                resp = await client._request(
                    "GET", f"{SPOT_BASE}/sapi/v1/sub-account/margin/account",
                    params={"email": acc.email}, signed=True,
                )
                margin_data = resp.get("marginAccountInfo", resp)
                level = margin_data.get("marginLevel", "N/A")
                print(f"  杠杆 marginLevel={level}")
                for ai in margin_data.get("userAssets", []):
                    net = float(ai.get("netAsset", 0))
                    borrowed = float(ai.get("borrowed", 0))
                    free = float(ai.get("free", 0))
                    if abs(net) > 0.0001 or borrowed > 0.0001 or free > 0.0001:
                        asset = ai["asset"]
                        print(f"    {asset}: free={ai['free']}, borrowed={ai['borrowed']}, interest={ai.get('interest','0')}, net={ai['netAsset']}")
            except Exception as e:
                print(f"  杠杆查询错误: {e}")

            # Futures
            try:
                resp = await client._request(
                    "GET", f"{SPOT_BASE}/sapi/v2/sub-account/futures/account",
                    params={"email": acc.email, "futuresType": 1}, signed=True,
                )
                fd = resp.get("futureAccountResp", resp)
                total = fd.get("totalWalletBalance", "0")
                avail = fd.get("availableBalance", "0")
                pnl = fd.get("totalUnrealizedProfit", "0")
                print(f"  合约 total={total}, available={avail}, unrealizedPnl={pnl}")
            except Exception as e:
                print(f"  合约查询错误: {e}")

            print()


asyncio.run(main())
