"""平掉一个 OPEN 持仓(master 对冲腿)并核对净持平。用法: flatten_position.py <pos_id>"""
import asyncio
import sys
from decimal import Decimal

sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")

POS_ID = int(sys.argv[1])


async def main():
    from app.db.session import SessionLocal
    from app.db.models import SubAccount
    from engine.models import Position
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.master_client import get_master_futures_client, close_all
    from engine.trading.order_executor import execute_close
    from engine.notify.feishu_sender import FeishuSender
    from app.api.engine_api import _build_spread_snapshot

    db = SessionLocal()
    pos = db.query(Position).get(POS_ID)
    sub = db.query(SubAccount).get(pos.sub_account_id)
    print(f"[before] pos#{pos.id} {pos.status} hedge={pos.hedge_account} fut_qty={pos.futures_long_qty}")

    fc = await get_master_futures_client(1) if pos.hedge_account == "master" else None
    spread = _build_spread_snapshot(pos.symbol)
    async with BinanceTradingClient(sub.api_key, sub.api_secret, sub_account_id=pos.sub_account_id) as client:
        await execute_close(pos, spread, client, FeishuSender(), "hustle-011[flatten]", futures_client=fc)
        db.refresh(pos)
        print(f"[after] pos#{pos.id} {pos.status} repay_qty={pos.repay_qty} pnl={pos.realized_pnl} err={pos.error_message}")
        if fc:
            pr = await fc.futures_position_risk(pos.symbol)
            amt = (pr or {}).get("positionAmt")
            print(f"[final] master {pos.symbol} positionAmt={amt}")
        m = await client.get_margin_account()
        b = next((a for a in m["userAssets"] if a["asset"] == pos.base_asset), {})
        bor = b.get("borrowed", "0")
        free = b.get("free", "0")
        print(f"[final] {sub.note} {pos.base_asset} borrowed={bor} interest={b.get('interest')} free={free}")
    db.close()
    await close_all()


asyncio.run(main())
