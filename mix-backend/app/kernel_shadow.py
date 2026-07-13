"""武装执行器 shadow 先行(V4.0 §6 门控第一步)——影随采纳器。
读现有引擎的真实在管仓位(dcm_main basis/dualperp + coin panel),构造成统一
owner_key / position_intent / pair_saga 的 **shadow** 记录,验证新数据模型能忠实
表达真实持仓,并逐仓对账(orphan/duplicate/miss)。**只读源 + 只写 shadow,零下单**。
契约稳定 + 混沌测试通过后,才把武装执行器接到同一套 owner/saga 上真下单。
"""
import json
import logging
import time

from . import datasources as ds
from . import contracts

log = logging.getLogger("mix.kernel_shadow")

# 引擎 state → saga state(§6.4)
_DP_STATE = {"OPEN": "OPEN", "OPENING": "OPENING", "CLOSING": "CLOSING",
             "ROLLBACK": "LEG_IMBALANCE", "FAILED": "QUARANTINED"}
_BS_STATE = {"OPEN": "OPEN", "OPENING": "OPENING", "CLOSING": "CLOSING", "FAILED": "QUARANTINED"}


def _canon(symbol: str) -> str:
    for suf in ("USDT", "USDC", "USD"):
        if symbol.endswith(suf):
            return symbol[: -len(suf)]
    return symbol


async def _live_owners() -> dict:
    """从真实引擎读非终态持仓 → {owner_key: {product, template, legs, saga_state, source}}。"""
    live = {}
    src = await ds.pg()   # dcm_main 只读
    if src is not None:
        # C2 双合约
        try:
            for r in await src.fetch(
                "SELECT symbol,venue_long,market_long,venue_short,market_short,account_long,"
                "account_short,notional_usdt,state FROM dualperp_positions "
                "WHERE state NOT IN ('CLOSED','FAILED')"):
                u = _canon(r["symbol"])
                ok = contracts.owner_key("CORE_POOL", "CORE_POOL", u, "perp")
                live[ok] = {"product": "C2", "template": "DERIVATIVE_LONG_DERIVATIVE_SHORT",
                            "legs": [
                                {"venue": r["venue_long"], "instrument_id": r["symbol"], "side": "perp_long",
                                 "target_notional_usdt": float(r["notional_usdt"] or 0)},
                                {"venue": r["venue_short"], "instrument_id": r["symbol"], "side": "perp_short",
                                 "target_notional_usdt": float(r["notional_usdt"] or 0)}],
                            "leg_locks": [
                                contracts.leg_lock(r["venue_long"], r["account_long"] or "main", r["symbol"]),
                                contracts.leg_lock(r["venue_short"], r["account_short"] or "main", r["symbol"])],
                            "saga_state": _DP_STATE.get(r["state"], "QUARANTINED"),
                            "source": f"dualperp:{r['symbol']}"}
        except Exception as e:  # noqa: BLE001
            log.warning("dualperp read: %s", e)
        # C1 期现
        try:
            for r in await src.fetch(
                "SELECT symbol,base_asset,notional_usdt,state FROM basis_positions "
                "WHERE state NOT IN ('CLOSED','FAILED')"):
                u = r["base_asset"] or _canon(r["symbol"])
                ok = contracts.owner_key("CORE_POOL", "CORE_POOL", u, "perp")
                live[ok] = {"product": "C1", "template": "SPOT_LONG_DERIVATIVE_SHORT",
                            "legs": [
                                {"venue": "binance", "instrument_id": r["symbol"], "side": "spot_long",
                                 "target_notional_usdt": float(r["notional_usdt"] or 0)},
                                {"venue": "binance", "instrument_id": r["symbol"], "side": "perp_short",
                                 "target_notional_usdt": float(r["notional_usdt"] or 0)}],
                            "leg_locks": [
                                contracts.leg_lock("binance", "main", r["symbol"] + ":spot"),
                                contracts.leg_lock("binance", "main", r["symbol"] + ":perp")],
                            "saga_state": _BS_STATE.get(r["state"], "QUARANTINED"),
                            "source": f"basis:{r['symbol']}"}
        except Exception as e:  # noqa: BLE001
            log.warning("basis read: %s", e)
    # C3 coin(Redis 快照,非终态)
    try:
        snap = await ds.get_json("dcm:engine:coin:positions") or {}
        for p in (snap.get("positions") or []):
            st = str(p.get("status") or "")
            if st in ("CLOSED", "FAILED", "SETTLED"):
                continue
            sym = str(p.get("symbol") or "?")
            u = _canon(sym)
            ok = contracts.owner_key("CORE_POOL", "CORE_POOL", u, "perp")
            if ok in live:  # 一币一引擎:coin 与 dcm 同币冲突→标注,不覆盖
                live[ok]["conflict"] = f"coin:{sym}"
                continue
            live[ok] = {"product": "C3", "template": "BORROW_SPOT_SHORT_DERIVATIVE_LONG",
                        "legs": [{"venue": "binance", "instrument_id": sym, "side": "borrow",
                                  "target_notional_usdt": float(p.get("open_usdt_amount") or 0)}],
                        "leg_locks": [contracts.leg_lock("binance", str(p.get("sub_account_id") or "sub"), sym)],
                        "saga_state": "OPEN", "source": f"coin:{sym}"}
    except Exception as e:  # noqa: BLE001
        log.warning("coin read: %s", e)
    return live


async def shadow_sync() -> dict:
    """采纳真实持仓为 shadow owner/intent/saga + 逐仓对账。返回摘要。"""
    pool = await ds.pg_main()
    if pool is None:
        return {"ok": False, "error": "mix_main 未配置"}
    live = await _live_owners()
    adopted, conflicts = 0, []
    import datetime as dt
    ttl = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    for ok, info in live.items():
        if info.get("conflict"):
            conflicts.append({"owner_key": ok, "with": info["conflict"], "held": info["source"]})
        # 采纳 owner
        await pool.execute(
            "INSERT INTO resource_ownership(owner_key,portfolio,book,canonical_underlying,settlement_bucket,"
            "product_id,leg_locks,status,updated_at) VALUES($1,'CORE_POOL','CORE_POOL',$2,'perp',$3,$4,'active',now()) "
            "ON CONFLICT (owner_key) DO UPDATE SET product_id=$3, leg_locks=$4, status='active', updated_at=now()",
            ok, ok.split(":")[2], info["product"], json.dumps(info["leg_locks"]))
        # 一 owner 一 shadow 采纳 intent(存在则复用,满足 saga FK)
        row = await pool.fetchrow(
            "SELECT intent_id FROM position_intent WHERE owner_key=$1 AND mode='shadow' AND status='proposed' "
            "ORDER BY intent_id DESC LIMIT 1", ok)
        if row:
            intent_id = row["intent_id"]
            await pool.execute("UPDATE position_intent SET legs=$2, ttl_at=$3 WHERE intent_id=$1",
                               intent_id, json.dumps(info["legs"]), ttl)
        else:
            intent_id = (await pool.fetchrow(
                "INSERT INTO position_intent(owner_key,product_id,template,legs,target_state,mode,ttl_at,"
                "status,created_by) VALUES($1,$2,$3,$4,'hold','shadow',$5,'proposed','kernel-shadow-adopt') "
                "RETURNING intent_id", ok, info["product"], info["template"], json.dumps(info["legs"]), ttl))["intent_id"]
        # 一 owner 一非终态 shadow saga
        sg = await pool.fetchrow(
            "SELECT saga_id FROM pair_saga WHERE owner_key=$1 AND mode='shadow' "
            "AND state NOT IN ('CLOSED') ORDER BY saga_id DESC LIMIT 1", ok)
        legst = json.dumps({str(i): ("FILLED" if info["saga_state"] == "OPEN" else "UNKNOWN")
                            for i in range(len(info["legs"]))})
        if sg:
            await pool.execute("UPDATE pair_saga SET state=$2, leg_states=$3, updated_at=now() WHERE saga_id=$1",
                               sg["saga_id"], info["saga_state"], legst)
        else:
            await pool.execute(
                "INSERT INTO pair_saga(intent_id,owner_key,state,leg_states,mode) VALUES($1,$2,$3,$4,'shadow')",
                intent_id, ok, info["saga_state"], legst)
        adopted += 1
    # 对账:live 里没有的非终态 shadow saga = 已平/orphan → 置 CLOSED
    reconciled = 0
    live_keys = set(live.keys())
    for r in await pool.fetch("SELECT saga_id,owner_key FROM pair_saga WHERE mode='shadow' AND state NOT IN ('CLOSED')"):
        if r["owner_key"] not in live_keys:
            await pool.execute("UPDATE pair_saga SET state='CLOSED', updated_at=now() WHERE saga_id=$1", r["saga_id"])
            await pool.execute("UPDATE resource_ownership SET status='released', updated_at=now() WHERE owner_key=$1", r["owner_key"])
            reconciled += 1
    summary = {"ok": True, "ts": int(time.time()), "live_positions": len(live), "adopted": adopted,
               "reconciled_closed": reconciled, "conflicts": conflicts}
    try:
        await ds.rds().set("mix:kernel:shadow_recon", json.dumps(summary), ex=600)
    except Exception:  # noqa: BLE001
        pass
    return summary


async def kernel_shadow_loop():
    """周期影随(120s)。异常不致命,下轮重试。"""
    import asyncio
    await asyncio.sleep(20)
    while True:
        try:
            s = await shadow_sync()
            log.info("kernel shadow: live=%s adopted=%s closed=%s conflicts=%s",
                     s.get("live_positions"), s.get("adopted"), s.get("reconciled_closed"), len(s.get("conflicts") or []))
        except Exception as e:  # noqa: BLE001
            log.warning("kernel_shadow_loop: %s", e)
        await asyncio.sleep(120)
