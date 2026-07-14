"""exec-kernel 常驻 manager 服务(V4.0 §5.2/§6)—— B 机,拥有仓位并强制目标态。
把执行器从一次性脚本变成常驻服务:每轮读配置(dcm:exec:manager:config)→逐 symbol 对账实盘→
采纳所有权(exec_saga)→按 target 强制(hold=零下单持有 / close=平仓)。
安全:mode 逐 symbol 门控(shadow=只记决策不下单;armed=真执行);target=hold 任何 mode 都零下单。
C1 现货腿在理财(LDXVG)→平仓须先赎回(标 NEED_EARN_REDEEM,不擅自动)。
发布 dcm:exec:manager + 心跳 dcm:hb:exec-manager。
"""
import asyncio
import json
import os
import sys
import time

import asyncpg
import redis.asyncio as aioredis

sys.path.insert(0, "/home/ec2-user/dexcexmix")
from real_venue import BinanceRealVenue  # noqa: E402
from store import PgSagaStore  # noqa: E402

INTERVAL = int(os.environ.get("DCM_MGR_INTERVAL_SEC", "20"))
CONFIG_KEY = "dcm:exec:manager:config"


async def manage_symbol(sym, cfg, store):
    mode = cfg.get("mode", "shadow")
    target = cfg.get("target", "hold")
    base = cfg.get("base_asset", sym[:-4])
    spot_src = cfg.get("spot_source", base)   # 理财腿用 LDXVG
    armed = mode == "armed"
    venue = BinanceRealVenue(armed=armed, arm_symbols=[sym] if armed else [])
    perp = await venue.get_position(sym)
    amt = perp.get("amt") or 0
    spot = await venue.get_spot_balance(spot_src)
    delta = amt + spot
    st = {"symbol": sym, "mode": mode, "target": target, "perp_amt": amt,
          "spot": round(spot, 4), "delta": round(delta, 4), "action": "hold"}

    # 采纳所有权:实盘有仓 → 记 exec_saga OPEN(owner-of-record)
    sid = f"mgr-{sym}"
    if abs(amt) > 1e-9 or spot > 1e-9:
        await store.set_state(sid, "OPEN")
        await store.save_leg(sid, 0, f"adopt-{sym}-perp", "FILLED", amt)
        await store.save_leg(sid, 1, f"adopt-{sym}-spot", "FILLED", spot)
    else:
        st["action"] = "flat(nothing to manage)"
        return st

    if target == "hold":
        return st   # 持有:零下单
    if target == "close":
        if not armed:
            st["action"] = "would_close(shadow)"
            return st
        # 平永续(reduceOnly)
        if abs(amt) > 1e-9:
            side = "BUY" if amt < 0 else "SELL"
            r = await venue.place(f"mgr:{sym}:close:perp", {"symbol": sym, "side": side,
                                  "market": "perp", "qty": abs(amt), "reduce_only": True})
            st["perp_close"] = r.get("status")
        # 现货腿:普通现货可卖;理财(LDXVG)须先赎回→标注不擅自动
        if spot > 1e-9:
            if spot_src == base:
                r2 = await venue.place(f"mgr:{sym}:close:spot", {"symbol": sym, "side": "SELL",
                                       "market": "spot", "qty": spot})
                st["spot_close"] = r2.get("status")
            else:
                st["spot_close"] = "NEED_EARN_REDEEM(理财腿须先赎回,人工/后续)"
        st["action"] = "close_executed"
    return st


async def main():
    pool = await asyncpg.create_pool(os.environ["DCM_PG_DSN"], min_size=1, max_size=2)
    r = aioredis.from_url(os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0"), decode_responses=True)
    store = PgSagaStore(pool)
    once = "--once" in sys.argv
    while True:
        try:
            cfg = json.loads(await r.get(CONFIG_KEY) or "{}")
            states = []
            for sym, scfg in (cfg.get("symbols") or {}).items():
                states.append(await manage_symbol(sym, scfg, store))
            await r.set("dcm:exec:manager", json.dumps({"ts": int(time.time()), "symbols": states}, ensure_ascii=False), ex=300)
            await r.set("dcm:hb:exec-manager", json.dumps({"ts": int(time.time()), "pid": os.getpid(),
                        "service": "exec-manager", "managed": len(states)}), ex=300)
            print("manager:", [f"{s['symbol']}/{s['mode']}/{s['action']} delta={s.get('delta')}" for s in states] or "no config")
        except Exception as e:  # noqa: BLE001
            print("manager err", repr(e)[:150])
        if once:
            break
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
