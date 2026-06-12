"""Canary: hedge_via_master 全链路 — hustle-011(sub 9)借币+卖现货, 主账户合约对冲.

强制开仓(跳过点差闸门)→ 校验 OPEN/hedge_account=master/主账户净仓 → 强制平仓
→ 校验 CLOSED/还币/主账户净仓归零. 只动 CRVUSDT, 金额受 account_symbol_rules cap 限制.
"""
import asyncio
import sys
from decimal import Decimal

sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")

SYMBOL = "CRVUSDT"
SUB_ID = 9          # hustle-011
USER_ID = 1


async def main():
    from app.db.session import SessionLocal
    from app.db.models import SubAccount
    from engine.models import Position
    from engine.trading.binance_trading import BinanceTradingClient
    from engine.trading.master_client import get_master_futures_client
    from engine.trading.order_executor import execute_open, execute_close
    from engine.notify.feishu_sender import FeishuSender
    from app.api.engine_api import _load_global_rules_snapshot, _build_spread_snapshot

    db = SessionLocal()
    sub = db.query(SubAccount).get(SUB_ID)
    rules = _load_global_rules_snapshot(db, USER_ID)
    db.close()
    print(f"[rules] hedge_via_master={rules.hedge_via_master} borrow_via_otoco={rules.borrow_via_otoco} "
          f"otoco_legs={rules.otoco_legs} order_amount={rules.order_amount} follow_type={rules.follow_type}")
    assert rules.hedge_via_master, "hedge_via_master 未开启"
    assert rules.borrow_via_otoco, "borrow_via_otoco 未开启"

    spread = _build_spread_snapshot(SYMBOL)
    if not spread:
        print(f"FATAL: 无 {SYMBOL} 点差数据"); return
    print(f"[spread] spot_ask={spread.spot_ask} fut_ask={spread.fut_ask} short={spread.spread_short}%")

    master_fc = await get_master_futures_client(USER_ID)
    if master_fc is None:
        print("FATAL: master client 不可用(未配置/双向持仓/key 异常)"); return
    print("[master] client ready (one-way mode asserted)")

    notifier = FeishuSender()
    async with BinanceTradingClient(sub.api_key, sub.api_secret, sub_account_id=SUB_ID) as client:
        # ---- pre-state ----
        m = await client.get_margin_account()
        usdt_free = next((a["free"] for a in m["userAssets"] if a["asset"] == "USDT"), "0")
        crv_borrowed0 = next((a["borrowed"] for a in m["userAssets"] if a["asset"] == "CRV"), "0")
        maxb = await client.get_max_borrowable("CRV")
        pr0 = await master_fc.futures_position_risk(SYMBOL)
        acct = await master_fc.get_futures_account()
        print(f"[pre] 011 margin USDT free={usdt_free} CRV borrowed={crv_borrowed0} maxBorrowable={maxb}")
        print(f"[pre] master {SYMBOL} positionAmt={(pr0 or {}).get('positionAmt')} "
              f"leverage={(pr0 or {}).get('leverage')} avail={acct.get('availableBalance')}")

        # ---- forced open: borrow(OTOCO) + spot sell(batched) + MASTER futures long ----
        print("=== execute_open (forced) ===")
        await execute_open(SUB_ID, SYMBOL, spread, rules, client, notifier, "hustle-011[canary]",
                           spread_feed=None, futures_client=master_fc, user_id=USER_ID)

        db = SessionLocal()
        pos = db.query(Position).filter(
            Position.sub_account_id == SUB_ID, Position.symbol == SYMBOL,
        ).order_by(Position.id.desc()).first()
        db.close()
        if not pos:
            print("FATAL: 无持仓记录"); return
        print(f"[pos#{pos.id}] status={pos.status} hedge_account={pos.hedge_account} user_id={pos.user_id}")
        print(f"  borrow_qty={pos.borrow_qty} spot_sell qty={pos.spot_sell_qty}@{pos.spot_sell_price}")
        print(f"  futures_long qty={pos.futures_long_qty}@{pos.futures_long_price} err={pos.error_message}")

        pr1 = await master_fc.futures_position_risk(SYMBOL)
        print(f"[after-open] master {SYMBOL} positionAmt={(pr1 or {}).get('positionAmt')}")

        if pos.status != "OPEN":
            print("OPEN 未达成,终止(已自动回滚则无残留)"); return

        await asyncio.sleep(3)

        # ---- forced close: MASTER futures close + spot buy back + repay ----
        print("=== execute_close (forced) ===")
        await execute_close(pos, spread, client, notifier, "hustle-011[canary]",
                            futures_client=master_fc)

        db = SessionLocal()
        pos2 = db.query(Position).get(pos.id)
        db.close()
        print(f"[pos#{pos2.id}] status={pos2.status} repay_qty={pos2.repay_qty} "
              f"futures_close@{pos2.futures_close_price} spot_buy={pos2.spot_buy_qty}@{pos2.spot_buy_price}")
        print(f"  realized_pnl={pos2.realized_pnl} fee_total={pos2.fee_total} err={pos2.error_message}")

        pr2 = await master_fc.futures_position_risk(SYMBOL)
        m2 = await client.get_margin_account()
        crv_b2 = next((a["borrowed"] for a in m2["userAssets"] if a["asset"] == "CRV"), "0")
        crv_free2 = next((a["free"] for a in m2["userAssets"] if a["asset"] == "CRV"), "0")
        usdt2 = next((a["free"] for a in m2["userAssets"] if a["asset"] == "USDT"), "0")
        print(f"[final] master {SYMBOL} positionAmt={(pr2 or {}).get('positionAmt')} (expect 0)")
        print(f"[final] 011 CRV borrowed={crv_b2} (expect ~0) free={crv_free2} USDT free={usdt2}")

    from engine.trading.master_client import close_all
    await close_all()
    print("CANARY DONE")


asyncio.run(main())
