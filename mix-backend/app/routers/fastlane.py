"""快线直通(用户 2026-07-19 授权):额度内点击即真实下单,免冷却/免逐笔二次认证。
四道机器闸(C侧)→ dcm:exec:fastlane:req 队列 → B机 runner(B侧纵深再闸)真开 → 回执入 intents 账。
额度权威=mix_main.operator_fastlane_limit(逐操作员自定义,今日工作页可改);服务端硬帽在B机env。
登录TOTP(strong session)后会话内不再逐笔输码——快线速度的前提是登录时已强认证。
"""
import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_operator
from .. import datasources as ds
from .. import proxy

router = APIRouter()


async def _await_result(r, rid, res_key, timeout=25.0):
    """等 runner 回执:紧轮询本地 Redis(0.25s 粒度);真金下单执行(下单→成交→查询确认)才是主延迟,
    非轮询瓶颈。Redis 在同 VPC 本地,GET 亚毫秒。"""
    import asyncio as _a
    for _ in range(int(timeout / 0.25)):
        raw = await r.get(res_key)
        if raw:
            return json.loads(raw)
        await _a.sleep(0.25)
    return None

_DDL = """
CREATE TABLE IF NOT EXISTS operator_fastlane_limit (
    operator TEXT PRIMARY KEY,
    max_notional_usdt DOUBLE PRECISION NOT NULL DEFAULT 50,
    enabled BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
"""
DEFAULT_LIMIT = 50.0


async def _limit_of(operator: str):
    pool = await ds.pg_main()
    if pool is None:
        return DEFAULT_LIMIT, True
    await pool.execute(_DDL)
    row = await pool.fetchrow(
        "SELECT max_notional_usdt, enabled FROM operator_fastlane_limit WHERE operator=$1", operator)
    if row is None:
        return DEFAULT_LIMIT, True
    return float(row["max_notional_usdt"]), bool(row["enabled"])


@router.get("/fastlane/limit")
async def fastlane_limit_get(op=Depends(require_operator)):
    lim, en = await _limit_of(op["operator"])
    return {"operator": op["operator"], "max_notional_usdt": lim, "enabled": en,
            "note": "额度内快线直通(免冷却/免逐笔认证);超额走DRY_RUN预演。服务端硬帽另在B机。"}


@router.put("/fastlane/limit")
async def fastlane_limit_put(body: dict, op=Depends(require_operator)):
    try:
        lim = float(body.get("max_notional_usdt"))
    except (TypeError, ValueError):
        raise HTTPException(400, "max_notional_usdt 必填数字")
    if lim < 0 or lim > 5000:
        raise HTTPException(400, "额度范围 0-5000U")
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 不可达")
    await pool.execute(_DDL)
    await pool.execute(
        "INSERT INTO operator_fastlane_limit(operator, max_notional_usdt, enabled, updated_at) "
        "VALUES($1,$2,$3,now()) ON CONFLICT (operator) DO UPDATE SET "
        "max_notional_usdt=$2, enabled=$3, updated_at=now()",
        op["operator"], lim, bool(body.get("enabled", True)))
    await proxy.audit(op["operator"], op["role"], "fastlane.limit", op["operator"], body, "saved")
    return {"saved": True, "max_notional_usdt": lim}


@router.post("/fastlane/open")
async def fastlane_open(body: dict, op=Depends(require_operator)):
    """快线开仓:C侧四闸(操作员额度/风险权威/深度/黑名单)→入队→等B机runner回执(≤25s)→入intents账。"""
    sym = str(body.get("symbol") or "").upper()
    vl = str(body.get("venue_long") or "").lower()
    vs = str(body.get("venue_short") or "").lower()
    try:
        notional = float(body.get("notional_usdt"))
    except (TypeError, ValueError):
        raise HTTPException(400, "notional_usdt 必填")
    if not sym or not vl or not vs or vl == vs:
        raise HTTPException(400, "symbol/venue_long/venue_short 必填且两腿不同所")
    # 闸1 操作员额度
    lim, en = await _limit_of(op["operator"])
    if not en:
        raise HTTPException(403, "快线已停用(今日工作页可开启)")
    if notional > lim:
        raise HTTPException(403, f"超出你的快线额度 {lim}U(今日工作页可调);大额请走 DRY_RUN 预演链")
    # 闸2 风险权威(venue+symbol,超龄fail-closed)
    pol = await ds.get_json("dcm:risk:policy") or {}
    age = time.time() - float(pol.get("ts") or 0)
    if not pol or age > 90:
        raise HTTPException(403, "风险策略快照缺失/超龄,fail-closed 拒绝新增")
    for v in (vl, vs):
        vd = (pol.get("venues") or {}).get(v) or {}
        if not (vd.get("capabilities") or {}).get("CAN_OPEN"):
            raise HTTPException(403, f"{v} 当前不允许新增({vd.get('mode')})")
    blocked = (pol.get("blocked_symbols") or {})
    if sym in blocked:
        raise HTTPException(403, f"{sym} 点差保护阻断({(blocked.get(sym) or {}).get('state')})")
    # 闸3 深度(l1lite,一档额<名义=会吃穿;NO_DATA放行由B侧复核)
    r = ds.rds()
    canon = sym[:-4] if sym.endswith("USDT") else sym
    await r.setex(f"dcm:l1lite:want:{canon}", 900, "1")
    for v, side_key, px_key, label in ((vl, "aq", "ask", "卖1"), (vs, "bq", "bid", "买1")):
        raw = await r.get(f"dcm:l1lite:{v}:perp:{canon}")
        if raw:
            d = json.loads(raw)
            top = (d.get(side_key) or 0) * (d.get(px_key) or 0)
            if top and top < notional:
                raise HTTPException(403, f"{v} {label}仅{top:.0f}U<{notional}U,会吃穿盘口(THIN)")
    # 闸4 C3黑名单(coin侧币种隔离)
    try:
        bl = await ds.get_json("dcm:coin:blacklist") or []
        syms = bl if isinstance(bl, list) else bl.get("symbols") or []
        if canon in [str(x).upper().replace("USDT", "") for x in syms]:
            raise HTTPException(403, f"{canon} 在C3黑名单")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        pass
    # 入队+等回执
    rid = f"fl-{int(time.time()*1000)}"
    _prod = str(body.get("product") or "C2.H")
    if _prod not in ("C2.H", "C2.P", "C2.C"):
        _prod = "C2.H"   # 归因白名单:未知产品码回退 harvest(M9)
    await r.rpush("dcm:exec:fastlane:req", json.dumps({
        "req_id": rid, "symbol": sym, "venue_long": vl, "venue_short": vs,
        "product": _prod,
        "notional_usdt": notional, "operator": op["operator"]}, ensure_ascii=False))
    await proxy.audit(op["operator"], op["role"], "fastlane.open", sym,
                      {"vl": vl, "vs": vs, "notional": notional}, "queued")
    res_key = f"dcm:exec:fastlane:res:{rid}"
    res = await _await_result(r, rid, res_key)
    if res is None:
        raise HTTPException(504, "执行桥超时(B机runner未回执);请到风险事件页核对是否已成交,勿盲目重试")
    if not res.get("ok"):
        raise HTTPException(409, f"执行拒绝:{res.get('reason')}")
    # 入 intents 账(与手动流程同一账本)
    wid = f"wi-{int(time.time())}-fastlane-{sym.lower()}"
    wi = {"work_item_id": wid, "product_code": "C2_PERP_PAIR", "symbol": sym,
          "workflow_stage": "HOLDING", "origin": "FASTLANE",
          "side_a": {"venue": vl, "side": "long", "target_notional": res.get("notional_per_leg")},
          "side_b": {"venue": vs, "side": "short", "target_notional": res.get("notional_per_leg")},
          "leg_a_execution": {"order_id": res.get("saga_id"), "filled_price": res.get("ref_price"),
                              "filled_qty": res.get("qty"), "filled_notional": res.get("notional_per_leg"),
                              "recorded_by": op["operator"], "recorded_at": time.time(),
                              "note": "fastlane执行器成交(参考价=开仓时mark,精确均价以账单RECON为准)"},
          "leg_b_execution": {"order_id": res.get("saga_id"), "filled_price": res.get("ref_price"),
                              "filled_qty": res.get("qty"), "filled_notional": res.get("notional_per_leg"),
                              "recorded_by": op["operator"], "recorded_at": time.time(),
                              "note": "fastlane执行器成交"},
          "holding_started_at": time.time(), "created_by": op["operator"], "created_at": time.time(),
          "saga_id": res.get("saga_id")}
    await r.setex(f"dcm:workitem:{wid}", 30 * 86400, json.dumps(wi, ensure_ascii=False))
    await proxy.audit(op["operator"], op["role"], "fastlane.open", sym, res, "OPEN")
    return {"ok": True, "work_item_id": wid, **res,
            "note": "已真实开仓并入manager监护;持有期今日工作可见,平仓走平仓预演/record_close"}


@router.post("/fastlane/close")
async def fastlane_close(body: dict, op=Depends(require_operator)):
    """快线直接平仓(与开仓对称):减险方向,不过额度/深度闸(平仓永远放行,同 reduce_only 纪律)。
    读实盘真仓→反向 reduce-only close_pair→平后自动 record_close 入既有 intent 账。"""
    sym = str(body.get("symbol") or "").upper()
    wid_in = str(body.get("work_item_id") or "")
    r = ds.rds()
    vl = str(body.get("venue_long") or "").lower()
    vs = str(body.get("venue_short") or "").lower()
    # 若给了 work_item_id,从账本补齐两腿 venue(前端只需传 symbol/wid)
    if (not vl or not vs) and wid_in:
        raw = await r.get(f"dcm:workitem:{wid_in}")
        if raw:
            wi0 = json.loads(raw)
            vl = vl or str((wi0.get("side_a") or {}).get("venue") or "").lower()
            vs = vs or str((wi0.get("side_b") or {}).get("venue") or "").lower()
    _is_c1 = str(body.get("product") or "").upper().startswith("C1")
    if not sym or (not _is_c1 and (not vl or not vs)):
        raise HTTPException(400, "symbol 必填;C2须venue_long/venue_short或有效work_item_id;C1须product=C1")
    # 唯一闸:操作员权限(已过 require_operator)+ 维护全停(减险类仍允许,不拦)。平仓不查额度/深度。
    # C1 判定:同所双腿(vl==vs)或前端标 product=C1 → 走 C1 专门平仓(永续+理财赎回+现货卖)
    is_c1 = (vl == vs) or str(body.get("product") or "").upper().startswith("C1")
    rid = f"flc-{int(time.time()*1000)}"
    if is_c1:
        await r.rpush("dcm:exec:fastlane:req", json.dumps({
            "req_id": rid, "action": "close_c1", "symbol": sym,
            "base_asset": body.get("base_asset"), "spot_source": body.get("spot_source"),
            "has_earn": True, "operator": op["operator"]}, ensure_ascii=False))
    else:
        await r.rpush("dcm:exec:fastlane:req", json.dumps({
            "req_id": rid, "action": "close", "symbol": sym,
            "venue_long": vl, "venue_short": vs, "operator": op["operator"]}, ensure_ascii=False))
    await proxy.audit(op["operator"], op["role"], "fastlane.close", sym, {"vl": vl, "vs": vs}, "queued")
    res_key = f"dcm:exec:fastlane:res:{rid}"
    res = await _await_result(r, rid, res_key)
    if res is None:
        raise HTTPException(504, "执行桥超时(B机runner未回执);到风险事件页核对是否已平,勿盲目重试")
    if not res.get("ok"):
        raise HTTPException(409, f"平仓拒绝:{res.get('reason')}")
    # 平后入账:更新既有 intent 为 CLOSED + record_close(与手动平仓同账本)
    if wid_in:
        raw = await r.get(f"dcm:workitem:{wid_in}")
        if raw:
            wi = json.loads(raw)
            now = time.time()
            for leg in ("leg_a", "leg_b"):
                wi[f"{leg}_close"] = {"order_id": res.get("saga_id"),
                                      "recorded_by": op["operator"], "recorded_at": now,
                                      "note": "fastlane直接平仓(reduce-only);净PnL以账单RECON为准"}
            wi["workflow_stage"] = "CLOSED"
            wi["closed_at"] = now
            await r.setex(f"dcm:workitem:{wid_in}", 30 * 86400, json.dumps(wi, ensure_ascii=False))
    await proxy.audit(op["operator"], op["role"], "fastlane.close", sym, res, "CLOSED")
    return {"ok": True, **res,
            "note": "已真实平仓(两腿reduce-only);manager监护已解除,净PnL待交易所账单RECON"}
