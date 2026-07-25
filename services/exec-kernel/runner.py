"""dcm-exec-runner —— 快线执行桥(用户 2026-07-19 授权:点击即真实下单)。

消费 dcm:exec:fastlane:req 队列(C 机 mix-backend 过完操作员额度/策略/深度/黑名单四闸后入队),
B 机侧再过一遍机器闸(纵深防御)后经统一执行内核 open_pair 双腿真开,开完:
①并入 manager pairs(shadow 监护) ②写结果键供 C 回读入账。
硬帽:DCM_FASTLANE_MAX(env,服务端天花板,与操作员自定义额度独立)。
复用 canary_c2 机件:qty 对齐(两所粗步长)/venue_armed(逐单逐币白名单)/PgSagaStore/policy 闸。
"""
import asyncio
import json
import os
import sys
import time

import asyncpg
import redis.asyncio as aioredis

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/ec2-user/dexcexmix/src/services/exec-kernel")
import exec_core as E                      # noqa: E402
from real_venue import venue_armed, venue_sym, MultiVenue   # noqa: E402
from store import PgSagaStore              # noqa: E402
from policy_client import can_open         # noqa: E402
from canary_c2 import _mark_price, _qty_step, _fl           # noqa: E402
from intent import OpenPairIntent          # noqa: E402  # Intent工厂:开仓审计链(阶段二接线)
from intent_store import save_intent, link_saga_to_intent  # noqa: E402

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN")
HARD_MAX = float(os.environ.get("DCM_FASTLANE_MAX", "200"))   # 服务端硬帽(U/腿)
Q_REQ = "dcm:exec:fastlane:req"


async def _handle_close_c1(r, pool, rid, res_key, fail, sym, req):
    """C1 一键平仓(binance 单所永续空腿+现货/理财多腿):
    ①永续 reduce-only 平 ②理财腿先赎回(Simple Earn FAST 即时到账) ③现货腿市价卖。
    减险方向:不过额度/深度闸。理财赎回可能有到账延迟→现货卖按赎回后实际余额。"""
    from real_venue import BinanceRealVenue
    base = req.get("base_asset") or (sym[:-4] if sym.endswith("USDT") else sym)
    spot_src = req.get("spot_source") or base   # 理财腿资产(如 XVG,币安内部记 LDXVG)
    v = BinanceRealVenue(armed=True, arm_symbols=[sym])
    v._policy_r = r
    v._policy_venue = "binance"
    steps = {}
    # ① 永续 reduce-only
    perp = await v.get_position(sym)
    if not perp.get("ok"):
        return await fail(f"永续读取失败:{perp.get('err')}")
    amt = float(perp.get("amt") or 0)
    if abs(amt) > 1e-9:
        side = "BUY" if amt < 0 else "SELL"
        res = await v.place(f"flc1:{sym}:perp:{int(time.time())}",
                            {"symbol": sym, "side": side, "market": "perp",
                             "qty": abs(amt), "reduce_only": True})
        steps["perp"] = res.get("status")
        if res.get("status") not in ("FILLED", "ACK", "PARTIAL"):
            return await fail(f"永续平仓失败:{res.get('status')} {res.get('err','')}")
    else:
        steps["perp"] = "flat"
    # ② 理财赎回(如现货源≠基础币=理财腿)
    if spot_src != base or req.get("has_earn"):
        rd = await v.redeem_flexible(base)
        steps["earn_redeem"] = rd.get("redeemed") if rd.get("ok") else f"FAIL:{rd.get('err')}"
        if not rd.get("ok"):
            # 赎回失败=永续已平但现货腿留存,单腿裸露风险→告警不静默
            print(f"runner: {rid} C1 EARN REDEEM FAIL {rd.get('err')}", flush=True)
        else:
            await asyncio.sleep(3)   # FAST 赎回到账窗
    # ③ 现货市价卖(按赎回后实际 free 余额)
    spot_free = await v.get_spot_balance(base)
    if spot_free > 1e-9:
        # LOT_SIZE 步长兜底:用 canary_c2 的 _qty_step(现货 symbol=base+USDT)
        try:
            step = await _qty_step("binance", sym)
            qty = _fl(spot_free, step)
        except Exception:  # noqa: BLE001
            qty = spot_free
        if qty > 1e-9:
            res2 = await v.place(f"flc1:{sym}:spot:{int(time.time())}",
                                 {"symbol": sym, "side": "SELL", "market": "spot", "qty": qty})
            steps["spot_sell"] = res2.get("status")
    else:
        steps["spot_sell"] = "flat"
    # 清 manager pairs(C1 用 symbols 段而非 pairs)
    try:
        cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
        changed = False
        for seg in ("symbols", "pairs"):
            if sym in (cfg.get(seg) or {}):
                del cfg[seg][sym]
                changed = True
        if changed:
            await r.set("dcm:exec:manager:config", json.dumps(cfg))
    except Exception:  # noqa: BLE001
        pass
    # C1收尾:basis_positions标CLOSED(recon从此表读C1期望腿;不清=平了实盘仍报ORPHAN_CLAIM孤儿)
    try:
        async with pool.acquire() as con:
            await con.execute("UPDATE basis_positions SET state='CLOSED' WHERE symbol= AND state NOT IN ('CLOSED','FAILED')", sym)
    except Exception as e:  # noqa: BLE001
        print(f"runner: {rid} C1 basis_positions收尾warn {e}", flush=True)
    perp_after = await v.get_position(sym)
    spot_after = await v.get_spot_balance(base)
    await r.set(res_key, json.dumps({
        "ok": True, "symbol": sym, "closed": True, "steps": steps,
        "perp_after": perp_after.get("amt"), "spot_after": round(spot_after, 6),
        "note": "C1平仓:永续+理财赎回+现货卖"}, ensure_ascii=False), ex=600)
    print(f"runner: {rid} CLOSE_C1 ok {sym} steps={steps} perp_after={perp_after.get('amt')} spot_after={spot_after}")


async def _handle_close(r, pool, rid, res_key, fail, sym, vl, vs, req):
    """快线直接平仓:读实盘两腿真仓→反向 reduce-only 经 close_pair 平掉→清 manager pairs。
    减险方向:不过深度闸/额度闸(平仓永远放行,与 real_venue reduce_only 同纪律)。"""
    if not sym or not vl or not vs:
        return await fail("平仓参数缺失(symbol/venue_long/venue_short)")
    sym_l, sym_s = venue_sym(vl, sym), venue_sym(vs, sym)
    adapters = {vl: venue_armed(vl, True, [sym_l], policy_r=r),
                vs: venue_armed(vs, True, [sym_s], policy_r=r)}
    # 读实盘真仓(平掉的是实盘持仓,不信配置方向)
    legs = []
    live = {}
    for v, vsym in ((vl, sym_l), (vs, sym_s)):
        p = await adapters[v].get_position(vsym)
        if not p.get("ok"):
            return await fail(f"{v} 实盘读取失败:{str(p.get('err'))[:80]},不盲目平仓")
        amt = float(p.get("amt") or 0)
        live[v] = amt
        if abs(amt) > 1e-12:
            legs.append({"venue": v, "symbol": vsym, "market": "perp", "qty": abs(amt),
                         "side": "BUY" if amt > 0 else "SELL", "reduce_only": True})
    if not legs:
        # 已是 flat:清 manager pairs 后成功返回(幂等)
        try:
            cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
            if sym in (cfg.get("pairs") or {}):
                del cfg["pairs"][sym]
                await r.set("dcm:exec:manager:config", json.dumps(cfg))
        except Exception:  # noqa: BLE001
            pass
        await r.set(res_key, json.dumps({"ok": True, "symbol": sym, "already_flat": True,
                    "note": "两腿已平,无需操作"}, ensure_ascii=False), ex=600)
        print(f"runner: {rid} CLOSE already-flat {sym}")
        return
    ex = E.SagaExecutor(MultiVenue(adapters), PgSagaStore(pool, mode="armed"))
    sid = f"flc-{sym}-{int(time.time())}"
    print(f"runner: {rid} CLOSE {sym} legs={[(x['venue'],x['side'],x['qty']) for x in legs]} op={req.get('operator')}")
    try:
        final = await ex.close_pair(sid, legs)
    except Exception as e:  # noqa: BLE001
        return await fail(f"平仓异常:{e}")
    if str(final) not in ("CLOSED", "SagaState.CLOSED"):
        return await fail(f"未达CLOSED终态:{final}(有腿平不掉已隔离,须人工兜底)")
    # 平后确认实盘 flat + 清 manager pairs
    pos_l = await adapters[vl].get_position(sym_l)
    pos_s = await adapters[vs].get_position(sym_s)
    try:
        cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
        if sym in (cfg.get("pairs") or {}):
            del cfg["pairs"][sym]
            await r.set("dcm:exec:manager:config", json.dumps(cfg))
    except Exception:  # noqa: BLE001
        pass
    await r.set(res_key, json.dumps({
        "ok": True, "saga_id": sid, "symbol": sym, "closed": True,
        "pos_long_after": pos_l.get("amt"), "pos_short_after": pos_s.get("amt"),
        "venue_long": vl, "venue_short": vs}, ensure_ascii=False), ex=600)
    print(f"runner: {rid} CLOSE ok {vl}={pos_l.get('amt')} {vs}={pos_s.get('amt')}")


async def handle(r, pool, raw):
    try:
        req = json.loads(raw)
    except Exception:  # noqa: BLE001
        return
    rid = req.get("req_id") or f"fl-{int(time.time())}"
    res_key = f"dcm:exec:fastlane:res:{rid}"

    async def fail(reason):
        await r.set(res_key, json.dumps({"ok": False, "reason": reason},
                                        ensure_ascii=False), ex=600)
        print(f"runner: {rid} REJECT {reason}")

    sym = str(req.get("symbol") or "").upper()
    vl, vs = req.get("venue_long"), req.get("venue_short")
    # ── 平仓分支 ──
    if str(req.get("action")) == "close":
        return await _handle_close(r, pool, rid, res_key, fail, sym, vl, vs, req)
    if str(req.get("action")) == "close_c1":
        return await _handle_close_c1(r, pool, rid, res_key, fail, sym, req)
    notional = float(req.get("notional_usdt") or 0)
    if not sym or not vl or not vs:
        return await fail("参数缺失")
    if notional <= 0 or notional > HARD_MAX:
        return await fail(f"名义{notional}U 超服务端硬帽{HARD_MAX}U")
    # B侧机器闸(纵深):风险权威 per-venue+symbol
    for v in (vl, vs):
        ok, why = await can_open(r, v, symbol=sym)
        if not ok:
            return await fail(f"风险策略拒绝 {v}: {why}")
    # 深度复核(l1lite):多腿吃卖1/空腿吃买1,一档额<名义→拒(与opener THIN同口径,K=1只挡吃穿)
    canon = sym[:-4] if sym.endswith("USDT") else sym
    try:
        dl = json.loads(await r.get(f"dcm:l1lite:{vl}:perp:{canon}") or "null")
        ds_ = json.loads(await r.get(f"dcm:l1lite:{vs}:perp:{canon}") or "null")
        top_l = (dl.get("aq") or 0) * (dl.get("ask") or 0) if dl else None
        top_s = (ds_.get("bq") or 0) * (ds_.get("bid") or 0) if ds_ else None
        if top_l is not None and top_l < notional:
            return await fail(f"{vl} 卖1仅{top_l:.0f}U<{notional}U,会吃穿盘口")
        if top_s is not None and top_s < notional:
            return await fail(f"{vs} 买1仅{top_s:.0f}U<{notional}U,会吃穿盘口")
    except Exception:  # noqa: BLE001
        pass   # 深度数据缺失不拦(C侧已闸),B侧只拦确定的吃穿
    # 数量对齐(canary_c2 同口径:两所较粗步长)
    sym_l, sym_s = venue_sym(vl, sym), venue_sym(vs, sym)
    px = await _mark_price(sym)
    step = max(await _qty_step(vl, sym_l), await _qty_step(vs, sym_s))
    qty = _fl(notional / px, step)
    if qty <= 0:
        return await fail(f"名义{notional}U 不足一个最小步长({step})")
    # 武装范围=本单本币(逐单白名单,不留全局武装态)
    adapters = {vl: venue_armed(vl, True, [sym_l], policy_r=r),
                vs: venue_armed(vs, True, [sym_s], policy_r=r)}
    ex = E.SagaExecutor(MultiVenue(adapters), PgSagaStore(pool, mode="armed"))
    sid = f"fl-{sym}-{int(time.time())}"
    legs = [{"venue": vl, "symbol": sym_l, "side": "BUY", "market": "perp", "qty": qty},
            {"venue": vs, "symbol": sym_s, "side": "SELL", "market": "perp", "qty": qty}]
    # Intent 工厂审计链(阶段二):OpenPairIntent 落 exec_intent + saga 关联——
    # 与 manager close 路径对称;持久化失败不阻塞执行(Intent 工厂铁律)。
    # legs/qty 仍由本函数对齐(runner 已做两所步长对齐,不经 planner 重算)。
    intent = OpenPairIntent(
        intent_id="", intent_type=None, created_at=0,
        reason=f"fastlane:{rid} op={req.get('operator')}",
        pair_id=sym, symbol=sym, venue_long=vl, venue_short=vs,
        target_notional_usdt=notional)
    try:
        await save_intent(pool, intent)
    except Exception as _ie:  # noqa: BLE001
        print(f"runner: {rid} intent persist warn {_ie}")
    print(f"runner: {rid} EXEC {sym} {vl}(BUY)x{vs}(SELL) qty={qty}(~{qty*px:.2f}U/腿) op={req.get('operator')} intent={intent.intent_id}")
    try:
        state = await ex.open_pair(sid, legs)
    except Exception as e:  # noqa: BLE001
        return await fail(f"执行异常:{e}")
    if str(state) not in ("OPEN", "SagaState.OPEN"):
        return await fail(f"未达OPEN终态:{state}(已按内核回滚纪律处理)")
    try:
        await link_saga_to_intent(pool, sid, intent.intent_id)
    except Exception as _ie:  # noqa: BLE001
        print(f"runner: {rid} intent link warn {_ie}")
    # 实盘确认+入 manager pairs(shadow 监护)
    pos_l = await adapters[vl].get_position(sym_l)
    pos_s = await adapters[vs].get_position(sym_s)
    try:
        cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
        cfg.setdefault("pairs", {})[sym] = {
            "mode": "shadow", "target": "hold", "signal_source": "route", "symbol": sym,
            "legs": [{"venue": vl, "side": "BUY"}, {"venue": vs, "side": "SELL"}]}
        await r.set("dcm:exec:manager:config", json.dumps(cfg))
    except Exception as e:  # noqa: BLE001
        print(f"runner: {rid} manager adopt warn {e}")
    await r.set(res_key, json.dumps({
        "ok": True, "saga_id": sid, "intent_id": intent.intent_id,
        "symbol": sym, "qty": qty, "ref_price": px,
        "notional_per_leg": round(qty * px, 2),
        "pos_long": pos_l.get("amt"), "pos_short": pos_s.get("amt"),
        "venue_long": vl, "venue_short": vs}, ensure_ascii=False), ex=600)
    print(f"runner: {rid} OPEN ok {vl}={pos_l.get('amt')} {vs}={pos_s.get('amt')}")


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True,
                          socket_timeout=10, socket_connect_timeout=10, health_check_interval=30)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    print(f"runner: up hard_max={HARD_MAX}U queue={Q_REQ}")
    while True:
        try:
            item = await r.blpop(Q_REQ, timeout=3)
            if item:
                await handle(r, pool, item[1])
            await r.set("dcm:hb:exec-runner", json.dumps(
                {"ts": int(time.time()), "service": "exec-runner", "hard_max": HARD_MAX}), ex=60)
        except Exception as e:  # noqa: BLE001
            print(f"runner loop err: {e}")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
