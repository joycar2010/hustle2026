"""清掉某子账户某资产的残余借币(买回币已结算时)。用法: repay_residual.py <sub_id> <ASSET>"""
import asyncio
import sys
from decimal import Decimal

sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")

SUB_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 9
ASSET = sys.argv[2] if len(sys.argv) > 2 else "CRV"


async def main():
    from app.db.session import SessionLocal
    from app.db.models import SubAccount
    from engine.trading.binance_trading import BinanceTradingClient

    db = SessionLocal()
    sub = db.query(SubAccount).get(SUB_ID)
    db.close()
    async with BinanceTradingClient(sub.api_key, sub.api_secret, sub_account_id=SUB_ID) as c:
        m = await c.get_margin_account()
        a = next((x for x in m["userAssets"] if x["asset"] == ASSET), None)
        if not a:
            print("no asset row"); return
        borrowed = Decimal(str(a["borrowed"])) + Decimal(str(a["interest"]))
        free = Decimal(str(a["free"]))
        print(f"{ASSET} borrowed={borrowed} free={free}")
        if borrowed <= 0:
            print("nothing to repay"); return
        amt = min(borrowed, free)
        if amt > 0:
            await c.margin_repay(ASSET, amt)
            print(f"repaid {amt}")
        m2 = await c.get_margin_account()
        b = next((x for x in m2["userAssets"] if x["asset"] == ASSET), None)
        bor2 = Decimal(str(b["borrowed"])) + Decimal(str(b["interest"]))
        print(f"after: borrowed={bor2} free={b['free']}")


asyncio.run(main())
