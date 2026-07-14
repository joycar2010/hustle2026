"""exec-kernel RiskRepair 修复意图服务(G2/V4 §20)—— B 机,**shadow 骨架,绝不下单**。

manager 对 REDUCE_ONLY+ venue 已有被动 close_recommend 告警;本服务把它升级为**持久化意图层**:
  每轮读 dcm:risk:policy → 受限 venue(REDUCE_ONLY/EXIT_ONLY/FROZEN)× 在管持仓(dcm:exec:manager)
  → 生成 EVACUATE_PAIR 修复意图(risk_repair_intent 表 + dcm:exec:repair 快照)。
意图三要素(骨架即落地):
  ①可行性预检:两腿 venue CAN_REDUCE 能力位 + 两腿 L1 新鲜(exposure 撤得动才叫可行;
    受限所本身 FROZEN 不可平 = infeasible → trapped capital,fatal 告警);
  ②TTL:PROPOSED 超 DCM_REPAIR_TTL_SEC 未采纳 → EXPIRED(条件仍在下轮重提,不静默悬挂);
  ③退出:venue 策略恢复(<REDUCE_ONLY)或仓位归零 → CANCELLED(意图不残留)。
执行路径(armed 后,人工采纳):plan.patch 并入 dcm:exec:manager:config →
  manager close_pair → exec_core.SagaExecutor → MultiVenue —— **复用六所 place,不造第二条下单路**。
shadow 铁律:本服务只写意图表/快照/告警,绝不碰 dcm:exec:manager:config,绝不武装。
发布 dcm:exec:repair + 心跳 dcm:hb:exec-repair。
"""
import asyncio
import json
import os
import sys
import time

import asyncpg
import redis.asyncio as aioredis

sys.path.insert(0, "/home/ec2-user/dexcexmix")
sys.path.insert(0, "/home/ec2-user/dexcexmix/src/packages/dcm-common")
from policy_client import read_policy, set_pool as policy_set_pool  # noqa: E402

try:
    from dcm_common.notify import Notifier, feishu_from_env
    _notifier = Notifier(os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0"),
                         "exec-repair", feishu=feishu_from_env(),
                         throttle_interval_sec=int(os.environ.get("DCM_REPAIR_ALERT_THROTTLE_SEC", "1800")),
                         throttle_max_count=1)
except Exception:  # noqa: BLE001
    _notifier = None

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
INTERVAL = int(os.environ.get("DCM_REPAIR_INTERVAL_SEC", "60"))
TTL_SEC = int(os.environ.get("DCM_REPAIR_TTL_SEC", "1800"))
FEED_FRESH_MS = int(os.environ.get("DCM_REPAIR_FEED_FRESH_MS", "120000"))
MGR_FRESH_SEC = int(os.environ.get("DCM_REPAIR_MGR_FRESH_SEC", "300"))
TRIGGER_MODES = ("REDUCE_ONLY", "EXIT_ONLY", "FROZEN")

SNAP_KEY = "dcm:exec:repair"


async def _alert(key, title, content, level="warn"):
    if _notifier is None:
        return
    try:
        await asyncio.to_thread(_notifier.fire, f"exec-repair:{key}", title, content,
                                level=level, marquee=True,
                                color="#ef4444" if level == "fatal" else "#f59e0b")
    except Exception:  # noqa: BLE001
        pass


async def _leg_check(r, pol, venue, symbol):
    """单腿可行性:venue CAN_REDUCE 能力位 + L1 新鲜。返回 (ok, checks, mid)。"""
    checks = {}
    vd = (pol.get("venues") or {}).get(venue) or {}
    caps = vd.get("capabilities") or {}
    checks["can_reduce"] = bool(caps.get("CAN_REDUCE"))
    mid = 0.0
    try:
        l1 = json.loads(await r.hget(f"dcm:feed:{venue}:perp", symbol) or "null")
    except Exception:  # noqa: BLE001
        l1 = None
    if l1:
        age_ms = int(time.time() * 1000) - int(l1.get("recv_ts") or 0)
        checks["feed_age_ms"] = age_ms
        checks["feed_fresh"] = age_ms <= FEED_FRESH_MS
        try:
            mid = (float(l1.get("bid") or 0) + float(l1.get("ask") or 0)) / 2
        except Exception:  # noqa: BLE001
            mid = 0.0
    else:
        checks["feed_fresh"] = False
        checks["feed_age_ms"] = None
    return checks["can_reduce"] and checks["feed_fresh"], checks, mid


async def _build_intent(r, pol, venue, vd, pid, pcfg, legs):
    """为 (受限venue, pair) 构造意图:预检两腿 → plan(manager patch)+ feasibility。"""
    sym = pcfg.get("symbol", pid)
    feas, est_notional, all_ok = {}, 0.0, True
    for lg in legs:
        ok, checks, mid = await _leg_check(r, pol, lg["venue"], sym)
        feas[lg["venue"]] = checks
        est_notional += abs(float(lg.get("amt") or 0)) * mid
        all_ok = all_ok and ok
    plan = {
        "apply": {"config_key": "dcm:exec:manager:config",
                  "patch": {"pairs": {pid: {"mode": "armed", "target": "close"}}}},
        "exec_path": "manager.close_pair→exec_core.SagaExecutor→MultiVenue(reduce-only)",
        "legs": legs,
    }
    return {
        "kind": "EVACUATE_PAIR", "venue": venue, "pair_id": pid, "symbol": sym,
        "feasible": all_ok, "plan": plan, "feasibility": feas,
        "reason": f"{venue}={vd.get('mode')}({str(vd.get('reason'))[:120]})",
        "est_notional_usdt": round(est_notional, 2),
    }


async def _persist(pool, it, pol, now):
    """PROPOSED 意图 upsert:同 (pair,venue) 现存 PROPOSED 未过期→刷新;过期→EXPIRED+重提;无→新建。
    返回 (intent_id, is_new)。pool=None(演练/降级)时只返回合成 id。"""
    if pool is None:
        return f"rep-{it['pair_id']}-{it['venue']}-shadow", False
    row = await pool.fetchrow(
        "SELECT intent_id, expires_at < now() AS expired FROM risk_repair_intent "
        "WHERE pair_id=$1 AND venue=$2 AND state='PROPOSED' ORDER BY id DESC LIMIT 1",
        it["pair_id"], it["venue"])
    if row and not row["expired"]:
        await pool.execute(
            "UPDATE risk_repair_intent SET feasible=$2, plan=$3, feasibility=$4, reason=$5, "
            "est_notional_usdt=$6, policy_epoch=$7, policy_version=$8, updated_at=now() "
            "WHERE intent_id=$1",
            row["intent_id"], it["feasible"], json.dumps(it["plan"]), json.dumps(it["feasibility"]),
            it["reason"], it["est_notional_usdt"],
            int(pol.get("policy_epoch") or 0), int(pol.get("policy_version") or 0))
        return row["intent_id"], False
    if row and row["expired"]:
        await pool.execute(
            "UPDATE risk_repair_intent SET state='EXPIRED', close_reason='ttl', updated_at=now() "
            "WHERE intent_id=$1", row["intent_id"])
    iid = f"rep-{it['pair_id']}-{it['venue']}-{int(now)}"
    await pool.execute(
        "INSERT INTO risk_repair_intent(intent_id, kind, venue, pair_id, symbol, state, mode, feasible, "
        "plan, feasibility, reason, policy_epoch, policy_version, est_notional_usdt, expires_at) "
        "VALUES($1,$2,$3,$4,$5,'PROPOSED','shadow',$6,$7,$8,$9,$10,$11,$12, now() + ($13||' seconds')::interval)",
        iid, it["kind"], it["venue"], it["pair_id"], it["symbol"], it["feasible"],
        json.dumps(it["plan"]), json.dumps(it["feasibility"]), it["reason"],
        int(pol.get("policy_epoch") or 0), int(pol.get("policy_version") or 0),
        it["est_notional_usdt"], str(TTL_SEC))
    return iid, True


async def _cancel_stale(pool, trigger_venues, live_pairs):
    """退出:策略恢复的 venue / 已归零的 pair 的 PROPOSED 意图 → CANCELLED。返回取消数。"""
    if pool is None:
        return 0
    n = 0
    rows = await pool.fetch("SELECT intent_id, venue, pair_id FROM risk_repair_intent WHERE state='PROPOSED'")
    for row in rows:
        why = None
        if row["venue"] not in trigger_venues:
            why = "policy_recovered"
        elif (row["pair_id"], row["venue"]) not in live_pairs:
            why = "position_flat"
        if why:
            await pool.execute(
                "UPDATE risk_repair_intent SET state='CANCELLED', close_reason=$2, updated_at=now() "
                "WHERE intent_id=$1", row["intent_id"], why)
            n += 1
    return n


async def evaluate(r, pool, now):
    pol, fresh = await read_policy(r)
    if pol is None or not fresh:
        # 策略不可用:不生成也不取消(保守不动),如实上报
        return {"ts": int(now), "mode": "shadow", "note": "policy缺失/超龄,本轮不评估",
                "trigger_venues": [], "intents": [], "cancelled": 0}
    trigger = {v: d for v, d in (pol.get("venues") or {}).items() if d.get("mode") in TRIGGER_MODES}

    # 在管持仓 = manager 快照(owner-of-record 视角;超龄不采信)
    try:
        mgr = json.loads(await r.get("dcm:exec:manager") or "{}")
    except Exception:  # noqa: BLE001
        mgr = {}
    mgr_fresh = (now - float(mgr.get("ts") or 0)) <= MGR_FRESH_SEC
    try:
        cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
    except Exception:  # noqa: BLE001
        cfg = {}

    intents, live_pairs = [], set()
    if mgr_fresh:
        for ps in (mgr.get("pairs") or []):
            pid = ps.get("pair")
            legs = [lg for lg in (ps.get("legs") or []) if abs(float(lg.get("amt") or 0)) > 1e-9]
            if not pid or not legs:
                continue
            pcfg = ((cfg.get("pairs") or {}).get(pid)) or {"symbol": ps.get("symbol", pid)}
            for v, vd in trigger.items():
                if any(lg.get("venue") == v for lg in legs):
                    live_pairs.add((pid, v))
                    intents.append(await _build_intent(r, pol, v, vd, pid, pcfg, legs))
    cancelled = await _cancel_stale(pool, set(trigger), live_pairs)

    out = []
    for it in intents:
        iid, is_new = await _persist(pool, it, pol, now)
        out.append({"intent_id": iid, **{k: it[k] for k in
                    ("kind", "venue", "pair_id", "symbol", "feasible", "reason", "est_notional_usdt")}})
        if is_new:
            lvl = "warn" if it["feasible"] else "fatal"
            extra = "" if it["feasible"] else "——预检不可行=trapped capital,撤不出来,须人工介入!"
            await _alert(iid, f"修复意图:撤离 {it['symbol']} 出 {it['venue']}(shadow)",
                         f"{it['reason']};估名义 {it['est_notional_usdt']}U;"
                         f"采纳=把 plan.patch 并入 manager config(armed 人工确认){extra}", level=lvl)
    return {"ts": int(now), "mode": "shadow", "mgr_fresh": mgr_fresh,
            "trigger_venues": sorted(trigger), "intents": out, "cancelled": cancelled,
            "ttl_sec": TTL_SEC}


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2) if PG_DSN else None
    policy_set_pool(pool)
    once = "--once" in sys.argv
    while True:
        try:
            s = await evaluate(r, pool, time.time())
            await r.set(SNAP_KEY, json.dumps(s, ensure_ascii=False), ex=max(INTERVAL * 3, 300))
            await r.set("dcm:hb:exec-repair", json.dumps({"ts": int(time.time()), "pid": os.getpid(),
                        "service": "exec-repair", "intents": len(s.get("intents") or [])}), ex=300)
            print(f"repair: trigger={s.get('trigger_venues')} intents={len(s.get('intents') or [])} "
                  f"cancelled={s.get('cancelled')} {s.get('note', '')}")
        except Exception as e:  # noqa: BLE001
            print("repair err", repr(e)[:160])
        if once:
            break
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
