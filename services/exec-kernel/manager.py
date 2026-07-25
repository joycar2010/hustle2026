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
import hashlib
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
from policy_client import read_policy, set_pool as policy_set_pool  # noqa: E402  # G0 风险策略消费

# Intent 工厂集成(关4 Phase C)
sys.path.insert(0, "/home/ec2-user/dexcexmix/src/services/exec-kernel")
from intent import RebalanceIntent, ClosePairIntent  # noqa: E402
from planner import IntentPlanner  # noqa: E402
from intent_store import save_intent, link_saga_to_intent  # noqa: E402

_intent_planner = IntentPlanner(min_order_usdt=5.0)

try:
    from dcm_common.notify import Notifier, feishu_from_env
    _notifier = Notifier(os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0"),
                         "exec-manager", feishu=feishu_from_env(),
                         throttle_interval_sec=int(os.environ.get("DCM_MGR_ALERT_THROTTLE_SEC", "600")),
                         throttle_max_count=1)
except Exception:  # noqa: BLE001  # dcm_common 缺失时告警降级为仅 Redis key,不 fatal
    _notifier = None

INTERVAL = int(os.environ.get("DCM_MGR_INTERVAL_SEC", "20"))
CONFIG_KEY = "dcm:exec:manager:config"

_alert_pool = None   # main() 注入,alerts_log 落库(dcm_main,与 mix 告警历史页同源)


async def _alert(r, key, title, content, level="warn", extra=None):
    """manager 告警统一出口:Redis key(面板)+Notifier(飞书+跑马灯,经节流)+alerts_log(历史页)。
    绝不抛异常——告警失败不能影响持仓管理主循环。"""
    try:
        await r.set(f"dcm:exec:manager:alert:{key}",
                    json.dumps({"ts": int(time.time()), "key": key, "title": title,
                                "content": content, "level": level, **(extra or {})},
                               ensure_ascii=False), ex=3600)
    except Exception:  # noqa: BLE001
        pass
    throttled = False
    if _notifier is not None:
        try:
            res = await asyncio.to_thread(
                _notifier.fire, f"exec-mgr:{key}", title, content, level=level,
                marquee=True, color="#ef4444" if level == "fatal" else "#f59e0b",
                blink=level == "fatal")
            throttled = isinstance(res, dict) and res.get("throttled")
        except Exception:  # noqa: BLE001
            pass
    if _alert_pool is not None and not throttled:
        try:
            await _alert_pool.execute(
                "INSERT INTO alerts_log(service,akey,level,title,content) VALUES('exec-manager',$1,$2,$3,$4)",
                key, level, title, content[:500])
        except Exception:  # noqa: BLE001
            pass


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


async def _close_saga_if_open(pool, sid):
    """把仍 OPEN 的 saga 转 CLOSED——仅 UPDATE 已存在行(WHERE state!='CLOSED'),绝不 INSERT 幽灵行。
    manager 本轮已读实盘=flat 才调用,所以是 owner-of-record 的权威平仓收尾(闭合'外部平仓→saga 永远 OPEN'幽灵源)。
    返回是否真的收了一行(供日志)。"""
    if pool is None:
        return False
    try:
        res = await pool.execute(
            "UPDATE exec_saga SET state='CLOSED', saga_version=saga_version+1, updated_at=now() "
            "WHERE saga_id=$1 AND state <> 'CLOSED'", sid)
        return res.endswith(" 1")
    except Exception:  # noqa: BLE001
        return False


async def _close_sagas_by_prefix(pool, prefix):
    """按 saga_id 前缀把仍 OPEN 的 saga 转 CLOSED(C2 pair flat 时 gen 已删、拿不到完整 sid)。
    仅 UPDATE 已存在行,返回收了几行。"""
    if pool is None:
        return 0
    try:
        res = await pool.execute(
            "UPDATE exec_saga SET state='CLOSED', saga_version=saga_version+1, updated_at=now() "
            "WHERE saga_id LIKE $1 AND state <> 'CLOSED'", prefix + "%")
        try:
            return int(res.rsplit(" ", 1)[1])
        except Exception:  # noqa: BLE001
            return 0
    except Exception:  # noqa: BLE001
        return 0


async def manage_symbol(sym, cfg, store, r):
    mode = cfg.get("mode", "shadow")
    target, signal_why = await _signal_target(sym, cfg, r)
    base = cfg.get("base_asset", sym[:-4])
    spot_src = cfg.get("spot_source", base)   # 理财腿用 LDXVG
    armed = mode == "armed"
    venue = BinanceRealVenue(armed=armed, arm_symbols=[sym] if armed else [])
    venue._policy_r = r; venue._policy_venue = "binance"   # G1:C1 腿 place 也过策略最后一跳
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
        # 实盘 flat:若旧 saga 仍 OPEN(外部平仓/漂移致孤儿)→ owner-of-record 收尾转 CLOSED
        if await _close_saga_if_open(store.pool, sid):
            st["action"] = "flat(saga reaped→CLOSED)"
        else:
            st["action"] = "flat(nothing to manage)"
        return st

    if target == "hold":
        return st   # 持有:零下单
    if target == "close_recommend":
        st["action"] = "CLOSE_RECOMMENDED(告警,不自动平——理财腿须人工协调赎回)"
        await _alert(r, sym, f"{sym} 建议平仓(C1)",
                     f"{signal_why};永续{amt}/现货{spot:.2f}。理财腿(LDXVG)须先人工赎回再翻 close。",
                     level="warn", extra={"perp_amt": amt, "spot": spot})
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
    # G0 风险策略叠加:任一腿 venue 处于 REDUCE_ONLY/EXIT_ONLY → 强制 close_recommend(推该 venue 出清);
    # NO_NEW 不影响在管持有(只挡新增,由 opener/canary 拦)。策略超龄不下压(保守持有,不误平)。
    pol, fresh = await read_policy(r)
    if fresh and pol:
        for lc in (cfg.get("legs") or []):
            vmode = ((pol.get("venues") or {}).get(lc.get("venue")) or {}).get("mode", "NORMAL")
            if vmode in ("REDUCE_ONLY", "EXIT_ONLY", "FROZEN") and target == "hold":
                target = "close_recommend"
                signal_why = f"{lc.get('venue')}={vmode}(策略降级,推出清);{signal_why}"
                break
    st = {"pair": pid, "symbol": sym, "mode": mode, "target": target, "signal": signal_why,
          "legs": [], "action": "hold"}

    adapters, legs, amts = {}, [], []
    for lc in (cfg.get("legs") or []):
        v = lc["venue"]
        vsym = venue_sym(v, sym)
        if v not in adapters:
            try:
                # G1:注入 policy_r=r,place 最后一跳过风险策略(不可绕过;close 路径 reduce_only 不受影响)
                adapters[v] = venue_armed(v, armed, [vsym] if armed else [], policy_r=r)
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
        # 两腿都 flat:收尾该 pair 所有代际仍 OPEN 的 saga(mgr-{pid}-<gen>)转 CLOSED
        n = await _close_sagas_by_prefix(store.pool, f"mgr-{pid}-")
        st["action"] = f"flat(saga reaped {n}→CLOSED)" if n else "flat(nothing to manage)"
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
        legs_txt = " / ".join(f"{x['venue']} {x['amt']}" for x in st["legs"])
        await _alert(r, pid, f"{pid} 单腿裸露(C2)",
                     f"跨所对一腿已平一腿在场:{legs_txt}。方向性敞口,须人工确认后平残腿。",
                     level="fatal", extra={"type": "SINGLE_LEG", "legs": st["legs"]})
        return st

    if target == "hold":
        return st
    if target == "close_recommend":
        st["action"] = "CLOSE_RECOMMENDED(告警,不自动平)"
        await _alert(r, pid, f"{pid} 建议平仓(C2)",
                     f"{signal_why}。确认后把 pairs.{pid} 翻 mode=armed+target=close 由 manager 平仓。",
                     level="warn", extra={"type": "CLOSE_RECOMMENDED", "legs": st["legs"]})
        return st
    if target == "close":
        # Intent 工厂路径(关4 Phase C):ClosePairIntent → Plan → Saga
        intent = ClosePairIntent(
            intent_id="",
            intent_type=None,  # will be set by __post_init__
            created_at=0,
            reason=signal_why,
            pair_id=pid,
            symbol=sym,
            venue_long=legs[0]["venue"] if len(legs) > 0 else "",
            venue_short=legs[1]["venue"] if len(legs) > 1 else "",
        )
        plan = _intent_planner.plan(intent)
        # 用 plan.legs 更新实际持仓数量(plan.legs qty=0 占位,需填充)
        for i, pleg in enumerate(plan.legs):
            if i < len(legs):
                pleg["qty"] = legs[i]["qty"]  # 从实盘持仓填充
        legs = plan.legs  # 替换为 Intent 工厂生成的 legs
        st["intent_id"] = intent.intent_id
        st["saga_plan"] = plan.saga_id
        # 持久化 Intent(Phase D)
        try:
            await save_intent(store.pool, intent)
            await link_saga_to_intent(store.pool, sid, intent.intent_id)
        except Exception as e:  # noqa: BLE001
            pass  # 持久化失败不阻塞执行


        if not armed:
            st["action"] = "would_close(shadow)"
            return st
        ex = E.SagaExecutor(MultiVenue(adapters), store)
        final = await ex.close_pair(sid, legs)
        st["action"] = f"close_{final}"
        if final == "CLOSED":
            await r.delete(gen_key)
        else:   # QUARANTINED=有腿平不掉,人工兜底,告警
            await _alert(r, pid, f"{pid} 平仓被隔离(C2)",
                         f"close_pair 有腿平不掉进 QUARANTINED,可能残留敞口。"
                         f"手动兜底:canary_c2.py {sym} <notional> <多所> <空所> --arm --close",
                         level="fatal", extra={"type": "CLOSE_QUARANTINED", "legs": st["legs"]})
    return st


_last_cfg_hash = None


async def _mirror_config_to_pg(pool, cfg):
    """把当前非空 config 镜像到 PG(单行快照,write-through 备份)。"""
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO exec_manager_config(id, config, updated_at) VALUES(1, $1::jsonb, now()) "
            "ON CONFLICT (id) DO UPDATE SET config=EXCLUDED.config, updated_at=now()",
            json.dumps(cfg, ensure_ascii=False))


async def _restore_config_from_pg(pool):
    """Redis config 键缺失(疑 Redis 重置)时从 PG 快照恢复。
    仅在快照非空 **且** 确有 OPEN saga(真有仓要管)时才恢复,防 flat 后复活陈旧 config。"""
    async with pool.acquire() as c:
        row = await c.fetchrow("SELECT config FROM exec_manager_config WHERE id=1")
        if not row or not row["config"]:
            return None
        cfg = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"])
        if not (cfg.get("symbols") or cfg.get("pairs")):
            return None
        open_cnt = await c.fetchval("SELECT count(*) FROM exec_saga WHERE state='OPEN'")
        if not open_cnt:
            return None
        return cfg


async def _load_config(r, pool):
    """读 Redis 权威 config。键**缺失**(GET=None,疑 Redis wipe)且 PG 有快照+活 saga → 自愈恢复;
    键**存在但空**(操作员主动清空)→ 尊重不恢复,并把空镜像到 PG。非空 → 镜像 PG 作备份。"""
    global _last_cfg_hash
    raw = await r.get(CONFIG_KEY)
    if raw is None:
        snap = await _restore_config_from_pg(pool)
        if snap is not None:
            await r.set(CONFIG_KEY, json.dumps(snap, ensure_ascii=False))
            await _alert(r, "config-selfheal", "manager配置PG自愈恢复",
                         "Redis config 键缺失(疑 Redis 重置),已从 PG 快照恢复 watch-list 并重新纳管在管仓",
                         level="warn")
            _last_cfg_hash = None
            return snap
        return {}
    cfg = json.loads(raw or "{}")
    try:
        h = hashlib.md5(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if h != _last_cfg_hash:
            await _mirror_config_to_pg(pool, cfg)   # 空 config 也镜像=尊重主动清空
            _last_cfg_hash = h
    except Exception as e:  # noqa: BLE001  # 镜像失败不能挡主循环
        print("mgr config mirror err", repr(e)[:100])
    return cfg


async def main():
    global _alert_pool
    pool = await asyncpg.create_pool(os.environ["DCM_PG_DSN"], min_size=1, max_size=2)
    _alert_pool = pool
    policy_set_pool(pool)   # 批次2:Redis 失效时策略从 PG effective_risk_policy 回退读
    r = aioredis.from_url(os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0"), decode_responses=True)
    store = PgSagaStore(pool)
    once = "--once" in sys.argv
    while True:
        try:
            cfg = await _load_config(r, pool)
            states, pair_states = [], []
            for sym, scfg in (cfg.get("symbols") or {}).items():
                states.append(await manage_symbol(sym, scfg, store, r))
            for pid, pcfg in (cfg.get("pairs") or {}).items():
                pair_states.append(await manage_pair(pid, pcfg, store, r))
            await r.set("dcm:exec:manager", json.dumps({"ts": int(time.time()), "symbols": states,
                        "pairs": pair_states}, ensure_ascii=False), ex=300)
            # PATCH-02 §8.6 RiskExitSaga(shadow):读 dcm:risk:exit → 发退出计划 dcm:risk:exit:saga(零下单)
            n_plan, n_armed = 0, 0
            try:
                from risk_exit_saga import plan_and_publish
                n_plan, n_armed = await plan_and_publish(r)
            except Exception as e:  # noqa: BLE001
                print("risk-exit-saga err", repr(e)[:120])
            await r.set("dcm:hb:exec-manager", json.dumps({"ts": int(time.time()), "pid": os.getpid(),
                        "service": "exec-manager", "managed": len(states) + len(pair_states),
                        "exit_plans": n_plan, "exit_armed": n_armed}), ex=300)
            print("manager:", [f"{s['symbol']}/{s['mode']} {s['action']} [{s.get('signal')}]" for s in states] +
                  [f"{s['pair']}(C2)/{s['mode']} {s['action']} [{s.get('signal')}]" for s in pair_states] or "no config")
        except Exception as e:  # noqa: BLE001
            print("manager err", repr(e)[:150])
        if once:
            break
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
