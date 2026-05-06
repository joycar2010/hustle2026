"""Sell BNB to USDT on each sub-account, then transfer all USDT back to master."""
import asyncio
import sys
import math
sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")

from app.db.session import SessionLocal
from app.db.models import SubAccount, MasterAccount
from engine.trading.binance_trading import BinanceTradingClient, SPOT_BASE

MASTER_EMAIL = "joycar2010@gmail.com"


async def sell_bnb(acc, client):
    """Sell all BNB for USDT via market order on sub-account."""
    # Get BNB balance
    resp = await client._request("GET", f"{SPOT_BASE}/api/v3/account", signed=True)
    bnb_free = 0.0
    for b in resp.get("balances", []):
        if b["asset"] == "BNB":
            bnb_free = float(b["free"])
            break

    if bnb_free < 0.001:
        print(f"  [BNB] 余额 {bnb_free} 太少，跳过")
        return

    # BNB lot size = 0.001 step
    qty = math.floor(bnb_free * 1000) / 1000
    if qty < 0.001:
        print(f"  [BNB] 可卖数量 {qty} 不足最小单位，跳过")
        return

    print(f"  [BNB] 市价卖出 {qty} BNB...")
    try:
        resp = await client._request("POST", f"{SPOT_BASE}/api/v3/order", params={
            "symbol": "BNBUSDT",
            "side": "SELL",
            "type": "MARKET",
            "quantity": str(qty),
        }, signed=True)
        fills = resp.get("fills", [])
        total_usdt = sum(float(f["price"]) * float(f["qty"]) for f in fills)
        print(f"  [BNB] 卖出成功！成交 {qty} BNB -> {total_usdt:.4f} USDT")
    except Exception as e:
        print(f"  [BNB] 卖出失败: {e}")


async def get_usdt_balance(client):
    """Get current USDT spot balance."""
    resp = await client._request("GET", f"{SPOT_BASE}/api/v3/account", signed=True)
    for b in resp.get("balances", []):
        if b["asset"] == "USDT":
            return float(b["free"])
    return 0.0


async def transfer_to_master(master_client, sub_email, amount):
    """Transfer USDT from sub-account to master spot via master API."""
    # Use sub-account transfer endpoint
    try:
        resp = await master_client._request("POST", f"{SPOT_BASE}/sapi/v1/sub-account/transfer/subToMaster", params={
            "email": sub_email,
            "asset": "USDT",
            "amount": f"{amount:.8f}",
        }, signed=True)
        print(f"  [划转] {amount:.4f} USDT -> 主号 成功 (txId={resp.get('txnId', 'N/A')})")
        return True
    except Exception as e:
        print(f"  [划转] 失败: {e}")
        return False


async def main():
    db = SessionLocal()
    master = db.query(MasterAccount).first()
    accounts = db.query(SubAccount).order_by(SubAccount.id).all()
    db.close()

    # Step 1: Sell BNB on each sub-account
    print("=" * 60)
    print("步骤 1: 卖出所有子账户的 BNB")
    print("=" * 60)
    for acc in accounts:
        print(f"\n--- {acc.note} ({acc.email}) ---")
        async with BinanceTradingClient(acc.api_key, acc.api_secret) as client:
            await sell_bnb(acc, client)

    # Wait a moment for orders to settle
    print("\n等待订单结算...")
    await asyncio.sleep(2)

    # Step 2: Check final balances and transfer
    print("\n" + "=" * 60)
    print("步骤 2: 划转 USDT 回主号")
    print("=" * 60)

    total_transferred = 0.0

    # Try using sub-account's own key for sub-to-master transfer
    # (subToMaster needs master key, so we'll try master first)
    async with BinanceTradingClient(master.api_key, master.api_secret) as master_client:
        for acc in accounts:
            print(f"\n--- {acc.note} ({acc.email}) ---")
            # Get balance using sub's own key
            async with BinanceTradingClient(acc.api_key, acc.api_secret) as sub_client:
                usdt = await get_usdt_balance(sub_client)
                print(f"  USDT余额: {usdt:.8f}")

            if usdt < 0.01:
                print(f"  余额太少，跳过")
                continue

            # Transfer: floor to 2 decimals to avoid precision issues
            transfer_amount = math.floor(usdt * 100) / 100
            if transfer_amount < 0.01:
                print(f"  可划转金额 {transfer_amount} 太少，跳过")
                continue

            ok = await transfer_to_master(master_client, acc.email, transfer_amount)
            if ok:
                total_transferred += transfer_amount

    print(f"\n{'=' * 60}")
    print(f"完成！总计划转 {total_transferred:.4f} USDT 回主号 {MASTER_EMAIL}")
    print(f"{'=' * 60}")


asyncio.run(main())
