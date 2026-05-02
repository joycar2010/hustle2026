"""Transfer USDT from sub-accounts' funding wallet back to spot, then to master."""
import asyncio
import math
import sys
sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")

from app.db.session import SessionLocal
from app.db.models import SubAccount, MasterAccount
from engine.trading.binance_trading import BinanceTradingClient, SPOT_BASE

MASTER_EMAIL = "joycar2010@gmail.com"


async def main():
    db = SessionLocal()
    master = db.query(MasterAccount).first()
    accounts = db.query(SubAccount).order_by(SubAccount.id).all()
    db.close()

    total = 0.0

    for acc in accounts:
        print(f"\n--- {acc.note} ({acc.email}) ---")
        async with BinanceTradingClient(acc.api_key, acc.api_secret) as client:
            # Step 1: Check funding balance
            try:
                resp = await client._request("POST", f"{SPOT_BASE}/sapi/v1/asset/get-funding-asset",
                                             params={"asset": "USDT"}, signed=True)
                funding_usdt = float(resp[0]["free"]) if resp else 0
            except:
                funding_usdt = 0
            print(f"  Funding USDT: {funding_usdt:.4f}")

            # Step 2: Transfer Funding -> Spot
            if funding_usdt > 0.01:
                amount = math.floor(funding_usdt * 100) / 100
                try:
                    resp = await client._request("POST", f"{SPOT_BASE}/sapi/v1/asset/transfer", params={
                        "type": "FUNDING_MAIN",
                        "asset": "USDT",
                        "amount": f"{amount:.8f}",
                    }, signed=True)
                    print(f"  Funding->Spot: {amount:.4f} USDT 成功")
                except Exception as e:
                    print(f"  Funding->Spot 失败: {e}")
                    continue

            await asyncio.sleep(0.5)

            # Step 3: Check spot balance
            resp = await client._request("GET", f"{SPOT_BASE}/api/v3/account", signed=True)
            spot_usdt = 0
            for b in resp.get("balances", []):
                if b["asset"] == "USDT":
                    spot_usdt = float(b["free"])
            print(f"  Spot USDT: {spot_usdt:.4f}")

            if spot_usdt < 0.01:
                print(f"  余额太少，跳过")
                continue

            transfer_amount = math.floor(spot_usdt * 100) / 100

            # Step 4: Try sub-to-master transfer using sub's own key
            try:
                resp = await client._request("POST", f"{SPOT_BASE}/sapi/v1/sub-account/transfer/subToMaster", params={
                    "asset": "USDT",
                    "amount": f"{transfer_amount:.8f}",
                }, signed=True)
                print(f"  Sub->Master: {transfer_amount:.4f} USDT 成功！txnId={resp.get('txnId', 'N/A')}")
                total += transfer_amount
                continue
            except Exception as e:
                print(f"  Sub->Master(子key): {e}")

            # Step 5: Try with master key
            try:
                async with BinanceTradingClient(master.api_key, master.api_secret) as mc:
                    resp = await mc._request("POST", f"{SPOT_BASE}/sapi/v1/sub-account/transfer/subToMaster", params={
                        "email": acc.email,
                        "asset": "USDT",
                        "amount": f"{transfer_amount:.8f}",
                    }, signed=True)
                    print(f"  Sub->Master(主key): {transfer_amount:.4f} USDT 成功！txnId={resp.get('txnId', 'N/A')}")
                    total += transfer_amount
                    continue
            except Exception as e:
                print(f"  Sub->Master(主key): {e}")

            # Step 6: Try universal transfer with master key
            try:
                async with BinanceTradingClient(master.api_key, master.api_secret) as mc:
                    resp = await mc._request("POST", f"{SPOT_BASE}/sapi/v1/sub-account/universalTransfer", params={
                        "fromEmail": acc.email,
                        "toEmail": MASTER_EMAIL,
                        "fromAccountType": "SPOT",
                        "toAccountType": "SPOT",
                        "clientTranId": f"cex_{acc.id}_{int(asyncio.get_event_loop().time())}",
                        "asset": "USDT",
                        "amount": f"{transfer_amount:.8f}",
                    }, signed=True)
                    print(f"  Universal(主key): {transfer_amount:.4f} USDT 成功！{resp}")
                    total += transfer_amount
            except Exception as e:
                print(f"  Universal(主key): {e}")
                print(f"  !!! 所有方法都失败，请手动划转 !!!")

    print(f"\n{'=' * 60}")
    print(f"总计成功划转: {total:.4f} USDT 回主号")
    print(f"{'=' * 60}")


asyncio.run(main())
