"""Canary: 主账户万向划转 1 USDT 往返 master↔sub9(验证 universalTransfer + 主账户权限)。"""
import asyncio
import sys
from decimal import Decimal

sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")


async def main():
    from app.db.session import SessionLocal
    from app.db.models import SubAccount, MasterAccount
    from engine.trading.binance_trading import BinanceTradingClient, BinanceAPIError

    db = SessionLocal()
    master = (db.query(MasterAccount).filter(MasterAccount.user_id == 1).first()
              or db.query(MasterAccount).first())
    sub = db.query(SubAccount).get(9)
    db.close()
    print(f"master={master.account_name} sub9={sub.note} email={sub.email}")

    async with BinanceTradingClient(master.api_key, master.api_secret) as c:
        # 1) master spot -> sub9 spot, 1 USDT  (主→子,新能力)
        try:
            r = await c.universal_transfer("USDT", Decimal("1"),
                                           from_account_type="SPOT", to_account_type="SPOT",
                                           from_email=None, to_email=sub.email)
            print(f"[master→sub9] OK tranId={r.get('tranId')}")
        except BinanceAPIError as e:
            print(f"[master→sub9] ERR code={e.api_code} msg={e.message}")
            return
        await asyncio.sleep(3)
        # 2) sub9 spot -> master spot, 1 USDT  (子→主)
        try:
            r = await c.universal_transfer("USDT", Decimal("1"),
                                           from_account_type="SPOT", to_account_type="SPOT",
                                           from_email=sub.email, to_email=None)
            print(f"[sub9→master] OK tranId={r.get('tranId')}")
        except BinanceAPIError as e:
            print(f"[sub9→master] ERR code={e.api_code} msg={e.message}")
    print("CROSS TRANSFER CANARY DONE")


asyncio.run(main())
