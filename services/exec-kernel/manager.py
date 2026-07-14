"""exec-kernel 常驻 manager 服务(V4.0 §5.2/§6)—— B 机,拥有仓位并强制目标态。
把执行器从一次性脚本变成常驻服务:每轮读配置(dcm:exec:manager:config)→逐 symbol/pair 对账实盘→
采纳所有权(exec_saga)→按 target 强制(hold=零下单持有 / close=平仓)。
配置两段:symbols={sym:{...}} 单所(C1 形态,永续+现货);pairs={pid:{symbol,legs:[{venue,side}],...}}
跨所双永续腿(C2 形态,close 经 exec_core.close_pair + MultiVenue,两腿 reduce-only 带回滚/隔离)。
安全:mode 逐 symbol/pair 门控(shadow=只记决策不下单;armed=真执行);target=hold 任何 mode 都零下单。
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
import exec_core as E  # noqa: E402
from real_venue import BinanceRealVenue, MultiVenue, venue_armed, venue_sym  # noqa: E402
from store import PgSagaStore  # noqa: E402

INTERVAL = int(os.environ.get("DCM_MGR_INTERVAL_SEC", "20"))
CONFIG_KEY = "dcm:exec:manager:config"


async def _signal_target(sym, cfg, r):
    """从决策面读有效目标态(主动生命周期管理)。
    signal_source: route(读dcm:route:assignments,off/draining→close) /
                   basis_funding(读funding,daily_pct≤阈值→close_recommend) / config(静态)。"""
    src = cfg.get("signal_source", "config")
    if src == "route":
        ra = await r.hget("dcm:route:assignments", sym)
        if ra:
            state = json.loads(ra).get("state")
            return ("hold" if state in ("active", "draining") else "close"), f"route={state}"
        return "close", "route=absent(路由撤=平)"
    if src == "basis_funding":
        # C1 basis:空腿收正资金费;funding 转负(空腿转付)且超阈值→建议平
        raw = await r.hget("dcm:feed:funding:binance", sym)
        thr = float(cfg.get("funding_close_pct", -0.02))
        if raw:
            dp = float(json.loads(raw).get("daily_pct", 0))
            if dp <= thr:
                return "close_recommend", f"funding={dp:.4f}%/d≤{thr}(空腿转付)"
            return "hold", f"funding={dp:.4f}%/d(空腿仍收)"
        return "hold", "funding缺(保守持有)"
    return cfg.get("target", "hold"), "config"


async def manage_symbol(sym, cfg, store, r):
    mode = cfg.get("mode", "shadow")
    target, signal_why = await _signal_target(sym, cfg, r)
    base = cfg.get("base_asset", sym[:-4])
    spot_src = cfg.get("spot_source", base)   # 理财腿用 LDXVG
    armed = mode == "armed"
    venue = BinanceRealVenue(armed=armed, arm_symbols=[sym] if armed else [])
    perp = await venue.get_position(sym)
    amt = perp.get("amt") or 0
    spot = await venue.get_spot_balance(spot_src)
    delta = amt + spot
    st = {"symbol": sym, "mode": mode, "target": target, "signal": signal_why, "perp_amt": amt,
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
    if target == "close_recommend":
        st["action"] = "CLOSE_RECOMMENDED(告警,不自动平——理财腿须人工协调赎回)"
        try:
            await r.set(f"dcm:exec:manager:alert:{sym}", json.dumps({"ts": int(time.time()),
                        "symbol": sym, "reason": signal_why, "perp_amt": amt, "spot": spot}), ex=3600)
        except Exception:  # noqa: BLE001
            pass
        return st
    if target == "close":
        if not armed:
            st["action"] = "would_close(shadow)"
            return st
        # 平永续(reduceOnly)
        if abs(amt) > 1e-9:
            side = "BUY" if amt < 0 else "SELL"
            res = await venue.place(f"mgr:{sym}:close:perp", {"symbol": sym, "side": side,
                                    "market": "perp", "qty": abs(amt), "reduce_only": True})
            st["perp_close"] = res.get("status")
        # 现货腿:普通现货可卖;理财(LDXVG)须先赎回→标注不擅自动
        if spot > 1e-9:
            if spot_src == base:
                res2 = await venue.place(f"mgr:{sym}:close:spot", {"symbol": sym, "side": "SELL",
                                         "market": "spot", "qty": spot})
                st["spot_close"] = res2.get("status")
            else:
                st["spot_close"] = "NEED_EARN_REDEEM(理财腿须先赎回,人工/后续)"
        st["action"] = "close_executed"
    return st


async def _pair_signal(pid, cfg, r):
    """C2 pair 有效目标态。signal_source:
    route(dcm:route:assignments 按 symbol,off/absent→close) /
    c2_funding_gap(净carry=fund(空腿所)-fund(多腿所),≤阈值→close_recommend) / config(静态)。"""
    src = cfg.get("signal_source", "config")
    sym = cfg.get("symbol", pid)
    if src == "route":
        ra = await r.hget("dcm:route:assignments", sym)
        if ra:
            state = json.loads(ra).get("state")
            return ("hold" if state in ("active", "draining") else "close"), f"route={state}"
        return "close", "route=absent(路由撤=平)"
    if src == "c2_funding_gap":
        vl = vs_ = None
        for lc in (cfg.get("legs") or []):
            if str(lc.get("side", "")).upper() == "BUY":
                vl = lc["venue"]
            else:
                vs_ = lc["venue"]
        if not vl or not vs_:
            return "hold", "legs缺BUY/SELL腿(保守持有)"
        try:
            fl = json.loads(await r.hget(f"dcm:feed:funding:{vl}", sym) or "{}").get("daily_pct")
            fs = json.loads(await r.hget(f"dcm:feed:funding:{vs_}", sym) or "{}").get("daily_pct")
        except Exception:  # noqa: BLE001
            fl = fs = None
        if fl is None or fs is None:
            return "hold", "funding缺(保守持有)"
        net = float(fs) - float(fl)   # 空腿收正费率,多腿付正费率
        thr = float(cfg.get("gap_close_pct", 0.0))
        if net <= thr:
            return "close_recommend", f"净carry={net:.4f}%/d≤{thr}(费差塌缩)"
        return "hold", f"净carry={net:.4f}%/d(仍为正)"
    return cfg.get("target", "hold"), "config"


async def manage_pair(pid, cfg, store, r):
    """C2 跨所双永续腿:逐腿读实盘→采纳所有权→单腿裸露告警→hold/close。
    close(armed)经 exec_core.close_pair + MultiVenue:两腿 reduce-only,平不掉=QUARANTINED 人工。
    saga id 带 generation(首见持仓时间戳,Redis 持久)——防跨生命周期 close cid 撞旧单误判已平。"""
    mode = cfg.get("mode", "shadow")
    armed = mode == "armed"
    sym = cfg.get("symbol", pid)
    target, signal_why = await _pair_signal(pid, cfg, r)
    st = {"pair": pid, "symbol": sym, "mode": mode, "target": target, "signal": signal_why,
          "legs": [], "action": "hold"}

    adapters, legs, amts = {}, [], []
    for lc in (cfg.get("legs") or []):
        v = lc["venue"]
        vsym = venue_sym(v, sym)
        if v not in adapters:
            try:
                adapters[v] = venue_armed(v, armed, [vsym] if armed else [])
            except Exception as e:  # noqa: BLE001
                st["action"] = f"NO_ADAPTER({v}: {repr(e)[:60]})"
                return st
        p = await adapters[v].get_position(vsym)
        if not p.get("ok"):
            st["action"] = f"VENUE_READ_FAIL({v}: {str(p.get('err'))[:80]},本轮跳过零下单)"
            return st
        amt = float(p.get("amt") or 0)
        st["legs"].append({"venue": v, "symbol": vsym, "amt": amt})
        # close 腿描述用实盘方向/数量(不是配置方向):close_pair 会反向 reduce-only
        legs.append({"venue": v, "symbol": vsym, "market": "perp", "qty": abs(amt),
                     "side": "BUY" if amt > 0 else "SELL"})
        amts.append(amt)

    if not amts:
        st["action"] = "no_legs(配置缺legs)"
        return st
    st["delta"] = round(sum(amts), 6)
    gen_key = f"dcm:exec:manager:gen:{pid}"
    if all(abs(a) < 1e-9 for a in amts):
        await r.delete(gen_key)
        st["action"] = "flat(nothing to manage)"
        return st
    gen = await r.get(gen_key)
    if not gen:
        gen = str(int(time.time()))
        await r.set(gen_key, gen)
    sid = f"mgr-{pid}-{gen}"
    st["saga"] = sid

    # 采纳所有权(owner-of-record)
    await store.set_state(sid, "OPEN")
    for i, a in enumerate(amts):
        await store.save_leg(sid, i, f"adopt-{pid}-{st['legs'][i]['venue']}", "FILLED", a)

    # 单腿裸露=最高风险:告警置顶,不自动动(armed 平残腿须人工确认方向)
    if any(abs(a) < 1e-9 for a in amts):
        st["action"] = "SINGLE_LEG(单腿裸露!告警,人工处置)"
        try:
            await r.set(f"dcm:exec:manager:alert:{pid}", json.dumps({"ts": int(time.time()),
                        "pair": pid, "type": "SINGLE_LEG", "legs": st["legs"]}, ensure_ascii=False), ex=3600)
        except Exception:  # noqa: BLE001
            pass
        return st

    if target == "hold":
        return st
    if target == "close_recommend":
        st["action"] = "CLOSE_RECOMMENDED(告警,不自动平)"
        try:
            await r.set(f"dcm:exec:manager:alert:{pid}", json.dumps({"ts": int(time.time()),
                        "pair": pid, "type": "CLOSE_RECOMMENDED", "reason": signal_why,
                        "legs": st["legs"]}, ensure_ascii=False), ex=3600)
        except Exception:  # noqa: BLE001
            pass
        return st
    if target == "close":
        if not armed:
            st["action"] = "would_close(shadow)"
            return st
        ex = E.SagaExecutor(MultiVenue(adapters), store)
        final = await ex.close_pair(sid, legs)
        st["action"] = f"close_{final}"
        if final == "CLOSED":
            await r.delete(gen_key)
        else:   # QUARANTINED=有腿平不掉,人工兜底,告警
            try:
                await r.set(f"dcm:exec:manager:alert:{pid}", json.dumps({"ts": int(time.time()),
                            "pair": pid, "type": "CLOSE_QUARANTINED", "legs": st["legs"]},
                            ensure_ascii=False), ex=3600)
            except Exception:  # noqa: BLE001
                pass
    return st


async def main():
    pool = await asyncpg.create_pool(os.environ["DCM_PG_DSN"], min_size=1, max_size=2)
    r = aioredis.from_url(os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0"), decode_responses=True)
    store = PgSagaStore(pool)
    once = "--once" in sys.argv
    while True:
        try:
            cfg = json.loads(await r.get(CONFIG_KEY) or "{}")
            states, pair_states = [], []
            for sym, scfg in (cfg.get("symbols") or {}).items():
                states.append(await manage_symbol(sym, scfg, store, r))
            for pid, pcfg in (cfg.get("pairs") or {}).items():
                pair_states.append(await manage_pair(pid, pcfg, store, r))
            await r.set("dcm:exec:manager", json.dumps({"ts": int(time.time()), "symbols": states,
                        "pairs": pair_states}, ensure_ascii=False), ex=300)
            await r.set("dcm:hb:exec-manager", json.dumps({"ts": int(time.time()), "pid": os.getpid(),
                        "service": "exec-manager", "managed": len(states) + len(pair_states)}), ex=300)
            print("manager:", [f"{s['symbol']}/{s['mode']} {s['action']} [{s.get('signal')}]" for s in states] +
                  [f"{s['pair']}(C2)/{s['mode']} {s['action']} [{s.get('signal')}]" for s in pair_states] or "no config")
        except Exception as e:  # noqa: BLE001
            print("manager err", repr(e)[:150])
        if once:
            break
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
