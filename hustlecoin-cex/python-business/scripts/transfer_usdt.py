"""Transfer USDT from sub-accounts back to master using sub-account's own keys.
Try multiple transfer methods."""
import asyncio
import math
import sys
sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")

from app.db.session import SessionLocal
from app.db.models import SubAccount, MasterAccount
from engine.trading.binance_trading import BinanceTradingClient, SPOT_BASE

MASTER_EMAIL = "joycar2010@gmail.com"


async def get_usdt_balance(client):
    resp = await client._request("GET", f"{SPOT_BASE}/api/v3/account", signed=True)
    for b in resp.get("balances", []):
        if b["asset"] == "USDT":
            return float(b["free"])
    return 0.0


async def try_transfer(client, acc, amount):
    """Try different transfer methods."""

    # Method 1: Universal transfer (sub-account internal)
    try:
        resp = await client._request("POST", f"{SPOT_BASE}/sapi/v1/asset/transfer", params={
            "type": "MAIN_FUNDING",
            "asset": "USDT",
            "amount": f"{amount:.8f}",
        }, signed=True)
        print(f"  [方法1-universal] 成功: {resp}")
        return True
    except Exception as e:
        print(f"  [方法1-universal] 失败: {e}")

    # Method 2: Sub to master via sub's own key
    try:
        resp = await client._request("POST", f"{SPOT_BASE}/sapi/v1/sub-account/transfer/subToMaster", params={
            "asset": "USDT",
            "amount": f"{amount:.8f}",
        }, signed=True)
        print(f"  [方法2-subToMaster] 成功: {resp}")
        return True
    except Exception as e:
        print(f"  [方法2-subToMaster] 失败: {e}")

    # Method 3: Sub account universal transfer
    try:
        resp = await client._request("POST", f"{SPOT_BASE}/sapi/v1/sub-account/universalTransfer", params={
            "fromEmail": acc.email,
            "toEmail": MASTER_EMAIL,
            "fromAccountType": "SPOT",
            "toAccountType": "SPOT",
            "asset": "USDT",
            "amount": f"{amount:.8f}",
        }, signed=True)
        print(f"  [方法3-universalTransfer] 成功: {resp}")
        return True
    except Exception as e:
        print(f"  [方法3-universalTransfer] 失败: {e}")

    return False


async def main():
    db = SessionLocal()
    accounts = db.query(SubAccount).order_by(SubAccount.id).all()
    db.close()

    total = 0.0
    for acc in accounts:
        print(f"\n--- {acc.note} ({acc.email}) ---")
        async with BinanceTradingClient(acc.api_key, acc.api_secret) as client:
            usdt = await get_usdt_balance(client)
            print(f"  USDT余额: {usdt:.8f}")

            if usdt < 0.01:
                print(f"  余额太少，跳过")
                continue

            amount = math.floor(usdt * 100) / 100
            ok = await try_transfer(client, acc, amount)
            if ok:
                total += amount

    print(f"\n{'=' * 60}")
    print(f"总计成功划转: {total:.4f} USDT")
    print(f"{'=' * 60}")


asyncio.run(main())
