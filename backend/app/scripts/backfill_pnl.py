"""一次性全量回填 binance_income / mt5_deals + 写水位。
慢速带退避(账户间 sleep), 避免打爆币安 REST 限频。
用法:
  python -m app.scripts.backfill_pnl --user <username>   # 回填某用户(含其关联)的账户
  python -m app.scripts.backfill_pnl --all               # 回填全部活跃账户
开关无关(直接调 live 拉取+upsert), 回填后 flip PNL_PERSIST_ENABLED=on 即生效。
"""
import asyncio, sys, argparse, time as _time
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal
from app.models.account import Account
from app.services import pnl_persistence as _pp
from app.utils.time_utils import mt5_server_ts_to_utc

SCAN_FROM = "2026-01-01"
SLEEP_BETWEEN_ACCT = 30   # 账户间退避秒数(防限频, 慢速回填)

async def _accounts_for(user=None, all_=False):
    async with AsyncSessionLocal() as db:
        if all_:
            r = await db.execute(select(Account).where(Account.is_active == True))
            return r.scalars().all()
        # user: 该用户 + user_pnl_links 关联用户的账户
        urow = (await db.execute(text("SELECT user_id FROM users WHERE username=:u"), {"u": user})).first()
        if not urow:
            print(f"用户 {user} 不存在"); return []
        uid = str(urow[0])
        linked = [str(x[0]) for x in (await db.execute(text(
            "SELECT linked_user_id FROM user_pnl_links WHERE owner_user_id=CAST(:u AS UUID)"), {"u": uid})).fetchall()]
        uids = [uid] + linked
        r = await db.execute(select(Account).where(Account.user_id.in_(uids)))
        return r.scalars().all()

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user"); ap.add_argument("--all", action="store_true"); ap.add_argument("--account", help="单账户account_id")
    args = ap.parse_args()
    from app.api.v1.pnl import _pull_binance_income_live, _pull_mt5_deals_live
    bj = timezone(timedelta(hours=8))
    scan_ms = int(datetime.fromisoformat(SCAN_FROM).replace(tzinfo=bj).timestamp() * 1000)
    now_ms = int(_time.time() * 1000)

    if args.account:
        async with AsyncSessionLocal() as db:
            accs = (await db.execute(select(Account).where(Account.account_id == args.account))).scalars().all()
    else:
        accs = await _accounts_for(args.user, args.all)
    print(f"回填 {len(accs)} 个账户, scan_from={SCAN_FROM}")
    for a in accs:
        try:
            if a.platform_id == 1:  # binance
                rows = await _pull_binance_income_live(a, scan_ms, now_ms)
                async with AsyncSessionLocal() as db:
                    n = await _pp.upsert_binance_income(db, a.account_id, rows)
                    await _pp.advance_watermark(db, a.account_id, "binance_income", cov_from=scan_ms, cov_to=now_ms)
                    await db.commit()
                print(f"  [BIN] {a.account_name}: 拉{len(rows)}笔 upsert{n} ✓")
                await asyncio.sleep(SLEEP_BETWEEN_ACCT)
            if a.is_mt5_account:
                rows = await _pull_mt5_deals_live(a, scan_ms, now_ms)
                std = []
                for d in rows:
                    t_raw = int(d.get("time", 0)); t_utc = mt5_server_ts_to_utc(t_raw)
                    std.append({"ticket": d.get("ticket"), "order_id": d.get("order"), "symbol": d.get("symbol"),
                        "deal_type": d.get("type"), "entry": d.get("entry"), "volume": d.get("volume"),
                        "price": d.get("price"), "profit": d.get("profit"), "swap": d.get("swap"),
                        "commission": d.get("commission"), "comment": d.get("comment"),
                        "deal_time_raw": t_raw, "deal_time_utc": datetime.fromtimestamp(t_utc, tz=timezone.utc).isoformat(),
                        "bridge_port": d.get("_bridge_port"), "raw": d})
                async with AsyncSessionLocal() as db:
                    n = await _pp.upsert_mt5_deals(db, a.account_id, std)
                    await _pp.advance_watermark(db, a.account_id, "mt5_deals", cov_from=scan_ms, cov_to=now_ms)
                    await db.commit()
                print(f"  [MT5] {a.account_name}: 拉{len(rows)}笔 upsert{n} ✓")
        except Exception as e:
            print(f"  [ERR] {a.account_name}: {e}")
    print("backfill done")

if __name__ == "__main__":
    asyncio.run(main())
