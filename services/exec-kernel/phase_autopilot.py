"""phase-autopilot —— C2.C/C3.R 自动开平仓(B机,10min timer,用户 2026-07-26 授权自动化)。

安全架构(平台惯例):
  - 两钥匙:env PHASE_AUTO_ARMED=1(unit)且 redis dcm:phase:auto:armed="1" 才动真钱;缺一=SHADOW 只打印。
  - policy fail-closed:can_open 不可读/拒 → 本轮不开。
  - 帽:单笔 ≤PA_C2C_MAX_ORDER(50U)/日累计 ≤PA_MAX_DAILY(100U,redis 日计数)/每轮最多 1 新仓。
  - C2.C 开=入 fastlane 队列(runner 深度复核+saga 执行+manager 收养,product=C2.C 归因自带);
    平=对 product=C2.C 的 manager pair 翻 target=close+mode=armed(manager 平仓机器代劳)。
    退出规则:分位≤0.5(已收敛)或 edge<0.3%/日 或 持有>14天。
  - C3.R 开=宇宙严格限『授权账 product=C3R 活跃行』∩ 榜单净差≥闸 ∩ 可借(§11.2 不破:
    新币要自动开须先人工入授权账);结构走 c4_exec C1 分支(现货多+perp空)。
    平(含 C1):funding 日化连续 2 轮 <0 → c4_exec close(退出纪律自动化)。
  - 全部动作 lpush dcm:phase:auto:log 留痕。
"""
import os
import json
import time
import asyncio
import datetime as dt
import subprocess

import asyncpg
import redis.asyncio as aioredis

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.95:6379/0")
PG_DSN = os.environ["DCM_PG_DSN"]
ARMED_ENV = os.environ.get("PHASE_AUTO_ARMED") == "1"
ARMED_KEY = "dcm:phase:auto:armed"
LOG_KEY = "dcm:phase:auto:log"

# ── R2-1 事实流 outbox:每条 logev 事件持久落 dcm_main.autopilot_cycle_fact
#     (附加审计,best-effort,永不影响主循环;C 侧时间线由 TEMP_OBSERVATION 升 AUDIT_TABLE)
_OUTBOX_PG = None
_CYCLE_ID = ""
_ARMED = None

PA_C2C_MAX_ORDER = float(os.environ.get("PA_C2C_MAX_ORDER", "50"))
PA_MAX_DAILY = float(os.environ.get("PA_MAX_DAILY", "100"))
PA_MAX_NEW_PER_CYCLE = int(os.environ.get("PA_MAX_NEW_PER_CYCLE", "1"))
C2C_EXIT_PCTILE = float(os.environ.get("PA_C2C_EXIT_PCTILE", "0.5"))
C2C_EXIT_EDGE = float(os.environ.get("PA_C2C_EXIT_EDGE_PCT", "0.3"))
C2C_MAX_HOLD_DAYS = float(os.environ.get("PA_C2C_MAX_HOLD_DAYS", "14"))
C3R_MIN_NET = float(os.environ.get("PA_C3R_MIN_NET_PCT", "1.0"))
FUND_FLIP_STRIKES = int(os.environ.get("PA_FUND_FLIP_STRIKES", "2"))

EXEC_DIR = "/home/ec2-user/dexcexmix"
PY = f"{EXEC_DIR}/venv/bin/python"


async def logev(r, kind, msg):
    print(f"[{kind}] {msg}")
    try:
        await r.lpush(LOG_KEY, json.dumps(
            {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "kind": kind, "msg": msg},
            ensure_ascii=False))
        await r.ltrim(LOG_KEY, 0, 499)
    except Exception:  # noqa: BLE001
        pass
    # R2-1:同一事件同步落 dcm_main 事实流(best-effort,永不影响主循环)
    if _OUTBOX_PG is not None:
        try:
            await _OUTBOX_PG.execute(
                "INSERT INTO autopilot_cycle_fact(cycle_id,loop_id,kind,msg,armed) "
                "VALUES($1,'phase-autopilot',$2,$3,$4)",
                _CYCLE_ID, kind, msg, _ARMED)
        except Exception:  # noqa: BLE001
            pass


async def _ensure_outbox(pg):
    try:
        await pg.execute(
            "CREATE TABLE IF NOT EXISTS autopilot_cycle_fact("
            "id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(), "
            "cycle_id TEXT NOT NULL DEFAULT '', loop_id TEXT NOT NULL DEFAULT 'phase-autopilot', "
            "kind TEXT NOT NULL, msg TEXT NOT NULL, armed BOOLEAN)")
        await pg.execute(
            "CREATE INDEX IF NOT EXISTS ix_apcf_ts ON autopilot_cycle_fact(ts DESC)")
        await pg.execute(
            "DELETE FROM autopilot_cycle_fact WHERE ts < now() - interval '30 days'")
        return True
    except Exception:  # noqa: BLE001
        return False


async def armed_on(r):
    rk = await r.get(ARMED_KEY)
    rk = (rk or b"").decode() if isinstance(rk, bytes) else (rk or "")
    return ARMED_ENV and rk == "1", f"env={'1' if ARMED_ENV else '0'} redis={rk or '0'}"


async def can_open_ok(r2, venue):
    try:
        import sys
        sys.path.insert(0, EXEC_DIR)
        from policy_client import can_open
        ok, why = await can_open(r2, venue)
        return ok, why
    except Exception as e:  # noqa: BLE001
        return False, f"policy不可读fail-closed:{repr(e)[:60]}"


async def daily_spent(r):
    k = f"dcm:phase:auto:spent:{dt.datetime.now(dt.timezone.utc):%Y%m%d}"
    v = await r.get(k)
    return float(v or 0), k


async def get_json(r, key):
    raw = await r.get(key)
    return json.loads(raw) if raw else None


async def c2c_cycle(r, r2, pg, on):
    """C2.C:开(fastlane 队列)+ 平(manager target=close)。返回本轮新开名义。"""
    opened_notional = 0.0
    sig = await get_json(r, "dcm:c2c:signal") or {}
    cands = (await get_json(r, "dcm:c2c:candidates") or {}).get("rows") or []
    mcfg = await get_json(r, "dcm:exec:manager:config") or {}
    pairs = mcfg.get("pairs") or {}

    # ---- 平仓检查:product=C2.C 的 pair ----
    sig_by_sym = {x["symbol"]: x for x in (sig.get("rows") or [])}
    for sym, pc in list(pairs.items()):
        if (pc.get("product") or "C2.H") != "C2.C" or pc.get("target") == "close":
            continue
        srow = sig_by_sym.get(sym)
        opened_at = float(pc.get("opened_ts") or 0)
        held_days = (time.time() - opened_at) / 86400.0 if opened_at else None
        reason = None
        if srow and (srow.get("pctile") or 1) <= C2C_EXIT_PCTILE:
            reason = f"已收敛(分位{srow.get('pctile'):.2f}≤{C2C_EXIT_PCTILE})"
        elif held_days is not None and held_days > C2C_MAX_HOLD_DAYS:
            reason = f"持有{held_days:.1f}天>上限{C2C_MAX_HOLD_DAYS}"
        else:
            # edge 现值(候选行里才有;信号行退化用 gap)
            crow = next((c for c in cands if c.get("symbol") == sym), None)
            edge = (crow or {}).get("edge_daily_pct")
            if edge is not None and edge < C2C_EXIT_EDGE:
                reason = f"edge {edge:.2f}%/d < {C2C_EXIT_EDGE}"
        if not reason:
            continue
        if not on:
            await logev(r, "C2C-CLOSE-SHADOW", f"{sym} 应平:{reason}(shadow 不动)")
            continue
        pairs[sym]["target"] = "close"
        pairs[sym]["mode"] = "armed"
        await r.set("dcm:exec:manager:config", json.dumps(mcfg, ensure_ascii=False))
        await logev(r, "C2C-CLOSE", f"{sym} 翻 target=close({reason}),manager 代劳平仓")

    # ---- 开仓:候选过提案级闸 + 帽 ----
    spent, spent_key = await daily_spent(r)
    new_count = 0
    for c in cands:
        if new_count >= PA_MAX_NEW_PER_CYCLE:
            break
        prop = str(c.get("proposal") or "")
        # 沿用决策层闸:必须是"本可提案"的行(filed/skip:24h提案),排除 already_held/未过闸
        if not (prop.startswith("filed") or "24h内已有活跃" in prop):
            continue
        sym = c["symbol"]
        if sym in pairs:
            continue
        vl, vs = c.get("venue_long"), c.get("venue_short")
        if not vl or not vs:
            continue
        notional = min(PA_C2C_MAX_ORDER, PA_MAX_DAILY - spent)
        if notional < 20:
            await logev(r, "C2C-CAP", f"日帽已尽(spent={spent}),{sym} 不开")
            break
        ok_l, why_l = await can_open_ok(r2, vl)
        ok_s, why_s = await can_open_ok(r2, vs)
        if not (ok_l and ok_s):
            await logev(r, "C2C-POLICY", f"{sym} policy 拒:{vl}={why_l} {vs}={why_s}")
            continue
        if not on:
            await logev(r, "C2C-OPEN-SHADOW",
                        f"{sym} 应开 {vl}多/{vs}空 {notional}U(edge={c.get('edge_daily_pct')}%/d "
                        f"分位={c.get('pctile')})(shadow 不动)")
            continue
        rid = f"pa-{int(time.time()*1000)}"
        await r.rpush("dcm:exec:fastlane:req", json.dumps({
            "req_id": rid, "symbol": sym, "venue_long": vl, "venue_short": vs,
            "product": "C2.C", "notional_usdt": notional,
            "operator": "phase-autopilot"}, ensure_ascii=False))
        res = None
        for _ in range(26):
            raw = await r.get(f"dcm:exec:fastlane:res:{rid}")
            if raw:
                res = json.loads(raw)
                break
            await asyncio.sleep(1)
        if res and res.get("ok"):
            new_count += 1
            spent += notional
            await r.set(spent_key, str(spent), ex=90000)
            # 给 pair 补 opened_ts(退出用)
            mcfg2 = await get_json(r, "dcm:exec:manager:config") or {}
            if sym in (mcfg2.get("pairs") or {}):
                mcfg2["pairs"][sym]["opened_ts"] = int(time.time())
                await r.set("dcm:exec:manager:config", json.dumps(mcfg2, ensure_ascii=False))
            await logev(r, "C2C-OPEN", f"{sym} 已开 {vl}多/{vs}空 {notional}U saga={res.get('saga_id')}")
        else:
            await logev(r, "C2C-OPEN-FAIL", f"{sym} 开仓失败/超时: {str(res)[:150]}")
    return opened_notional


async def funding_daily(r, venue, ul):
    raw = await r.hget(f"dcm:feed:funding:{venue}", f"{ul}USDT")
    if not raw:
        return None
    try:
        j = json.loads(raw)
        ts = float(j.get("ts") or 0)
        if ts > 1e12:
            ts /= 1000.0
        if ts and time.time() - ts > 3600:
            return None
        return float(j["daily_pct"]) if j.get("daily_pct") is not None else None
    except (ValueError, TypeError):
        return None


async def run_c4exec(r, args, armed):
    """c4_exec 子进程:两钥匙第二把(redis dcm:c4:exec:armed)由 autopilot 瞬时代持,用完即收。"""
    env = dict(os.environ)
    if armed:
        env["DCM_C4_ARMED"] = "1"
        await r.set("dcm:c4:exec:armed", "1")
    try:
        p = subprocess.run([PY, f"{EXEC_DIR}/c4_exec.py"] + args,
                           cwd=EXEC_DIR, env=env, capture_output=True, text=True, timeout=180)
        return p.returncode, (p.stdout + p.stderr)[-800:]
    finally:
        if armed:
            await r.set("dcm:c4:exec:armed", "0")


async def c3r_cycle(r, r2, pg, on):
    """C3.R:开(授权账∩榜单∩可借,c4_exec C1结构)+ 平(C1/C3R funding 连续转负)。"""
    # ---- 平:C1/C3R OPEN 仓 funding 翻转 ----
    rows = await pg.fetch(
        "SELECT id, route_id, venue, symbol_fut, coalesce(product,'C4') product "
        "FROM c4_position WHERE status='OPEN' AND coalesce(product,'C4') IN ('C1','C3R')")
    for x in rows:
        ul = str(x["symbol_fut"]).replace("USDT", "")
        fd = await funding_daily(r, x["venue"], ul)
        strike_key = f"dcm:phase:auto:fundflip:{x['id']}"
        if fd is not None and fd < 0:
            strikes = int(await r.incr(strike_key))
            await r.expire(strike_key, 7200)
            if strikes >= FUND_FLIP_STRIKES:
                if not on:
                    await logev(r, "C1-CLOSE-SHADOW", f"pos#{x['id']} funding 连续{strikes}轮转负({fd}%/d),应平(shadow)")
                    continue
                rc, out = await run_c4exec(r, ["close", "--pos", str(x["id"])], armed=True)
                await r.delete(strike_key)
                await logev(r, "C1-CLOSE", f"pos#{x['id']} funding翻转自动平 rc={rc} {out[-200:]}")
        else:
            await r.delete(strike_key)

    # ---- 开:授权账 product=C3R ∩ 榜单净差 ∩ 可借 ----
    auth = await pg.fetch(
        "SELECT route_id, underlying, venue FROM c4_route_authorization "
        "WHERE active AND product='C3R'")
    if not auth:
        await logev(r, "C3R-UNIVERSE", "授权账无 C3R 活跃路由(§11.2:新币自动开须先人工授权);本轮无可开宇宙")
        return
    cands = (await get_json(r, "dcm:c3r:candidates") or {}).get("rows") or []
    by_coin = {c["coin"]: c for c in cands}
    opened = await pg.fetch("SELECT route_id FROM c4_position WHERE status='OPEN'")
    open_routes = {x["route_id"] for x in opened}
    spent, spent_key = await daily_spent(r)
    for a in auth:
        if a["route_id"] in open_routes:
            continue
        c = by_coin.get(a["underlying"])
        if not c or float(c.get("net_daily_pct") or 0) < C3R_MIN_NET or not c.get("borrowable"):
            continue
        notional = min(PA_C2C_MAX_ORDER, PA_MAX_DAILY - spent)
        if notional < 20:
            break
        if not on:
            await logev(r, "C3R-OPEN-SHADOW", f"{a['route_id']} 具备条件(净{c['net_daily_pct']}%/d 可借),应开(shadow)")
            continue
        rc, out = await run_c4exec(r, ["open", "--route", a["route_id"], "--qty", "0.001"], armed=True)
        spent += notional
        await r.set(spent_key, str(spent), ex=90000)
        await logev(r, "C3R-OPEN", f"{a['route_id']} 自动开 rc={rc} {out[-200:]}")


async def main():
    global _OUTBOX_PG, _CYCLE_ID, _ARMED
    r = aioredis.from_url(REDIS_URL)
    r2 = aioredis.from_url(REDIS_URL, decode_responses=True)
    pg = await asyncpg.connect(PG_DSN)
    _CYCLE_ID = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    if await _ensure_outbox(pg):
        _OUTBOX_PG = pg
    on, detail = await armed_on(r)
    _ARMED = on
    await logev(r, "CYCLE", f"phase-autopilot {'ARMED' if on else 'SHADOW'}({detail})")
    try:
        await c2c_cycle(r, r2, pg, on)
        await c3r_cycle(r, r2, pg, on)
    finally:
        await pg.close()
        await r.aclose()
        await r2.aclose()


if __name__ == "__main__":
    asyncio.run(main())
