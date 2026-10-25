"""修复 canary 卡仓: 按主账户订单终态回填 futures_long_qty/price → 置回 OPEN → 重新平仓."""
import asyncio
import sys
from decimal import Decimal

sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")

POS_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1009538
SUB_ID = 9
USER_ID = 1


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
    sub = db.query(SubAccount).get(SUB_ID)
    print(f"[pos#{pos.id}] status={pos.status} futures_long_qty={pos.futures_long_qty} "
          f"order_id={pos.futures_long_order_id}")

    master_fc = await get_master_futures_client(USER_ID)
    if master_fc is None:
        print("FATAL: master client 不可用"); return

    # 1) 按订单终态回填
    o = await master_fc.futures_get_order(pos.symbol, pos.futures_long_order_id)
    eq = Decimal(str(o.get("executedQty", "0")))
    ap = Decimal(str(o.get("avgPrice", "0")))
    print(f"[order] status={o.get('status')} executedQty={eq} avgPrice={ap}")
    if eq <= 0:
        print("FATAL: 订单无成交,不应回填"); return
    pos.futures_long_qty = eq
    pos.futures_long_price = ap
    pos.status = "OPEN"
    pos.error_message = None
    db.commit()
    print(f"[repair] futures_long backfilled {eq}@{ap}, status=OPEN")

    # 2) 重新平仓(修复后的代码: RESULT 应答 + 终态确认)
    spread = _build_spread_snapshot(pos.symbol)
    notifier = FeishuSender()
    async with BinanceTradingClient(sub.api_key, sub.api_secret, sub_account_id=SUB_ID) as client:
        await execute_close(pos, spread, client, notifier, "hustle-011[canary-repair]",
                            futures_client=master_fc)

        db.refresh(pos)
        print(f"[pos#{pos.id}] status={pos.status} repay_qty={pos.repay_qty} "
              f"futures_close@{pos.futures_close_price} spot_buy={pos.spot_buy_qty}@{pos.spot_buy_price}")
        print(f"  realized_pnl={pos.realized_pnl} fee_total={pos.fee_total} err={pos.error_message}")

        pr = await master_fc.futures_position_risk(pos.symbol)
        m2 = await client.get_margin_account()
        b2 = next((a["borrowed"] for a in m2["userAssets"] if a["asset"] == pos.base_asset), "0")
        f2 = next((a["free"] for a in m2["userAssets"] if a["asset"] == pos.base_asset), "0")
        u2 = next((a["free"] for a in m2["userAssets"] if a["asset"] == "USDT"), "0")
        print(f"[final] master {pos.symbol} positionAmt={(pr or {}).get('positionAmt')} (expect 0)")
        print(f"[final] 011 {pos.base_asset} borrowed={b2} free={f2} USDT free={u2}")
    db.close()
    await close_all()
    print("REPAIR DONE")


asyncio.run(main())
