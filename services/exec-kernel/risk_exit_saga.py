"""MIX-V6.2-PATCH-02 §8.6 RiskExitSaga —— 点差扩大退出编排(B 机,shadow 先行)。

读 C 机 risk_guard 发布的 dcm:risk:exit(逐币保护态),对 REDUCE_REQUIRED/EXIT_REQUIRED 的
在管组合生成**退出计划**并发布 dcm:risk:exit:saga;编排七阶段(§8.6):
  锁定工作项(禁新增) → 撤加仓挂单 → 直拉交易所持仓真相 → 生成退出预演
  → 按匹配名义分片减两腿(exec_core.reduce_pair) → 单腿失败救援/隔离
  → C3 买回还币 → 持仓/负债/订单 RECON → 账本确认

铁律(批准前置④):**默认 shadow——只规划+读实盘,绝不下单**。
  DCM_RISK_EXIT_ARMED != true → plan-only(execute 全部诚实标注 would_*,零 place)。
  即便 armed,也只对 DCM_RISK_EXIT_ARM_SYMBOLS 白名单币执行,且减仓/平仓走
  exec_core.reduce_pair/close_pair(reduce-only,永放行)——armed 须用户显式放行+盯盘。
  硬生存线(EXIT_REQUIRED)可先做硬阻断(policy blocked_symbols 已挡新增),
  自动双腿退出的真金执行是独立门控项。
"""
import json
import os
import time

EXIT_KEY = "dcm:risk:exit"
SAGA_KEY = "dcm:risk:exit:saga"
ARMED = os.environ.get("DCM_RISK_EXIT_ARMED", "false").lower() == "true"
ARM_SYMBOLS = frozenset(s.strip() for s in os.environ.get("DCM_RISK_EXIT_ARM_SYMBOLS", "").split(",") if s.strip())
# REDUCE_REQUIRED 分片比例;EXIT_REQUIRED 全平(fraction=1.0 走 close_pair)
REDUCE_FRACTION = float(os.environ.get("DCM_RISK_EXIT_REDUCE_FRACTION", "0.34"))


async def _exit_items(r) -> dict:
    try:
        raw = await r.get(EXIT_KEY)
        items = (json.loads(raw) if raw else {}).get("items") or {}
        return {s: v for s, v in items.items()
                if v.get("state") in ("REDUCE_REQUIRED", "EXIT_REQUIRED")}
    except Exception:  # noqa: BLE001
        return {}


def _plan_for(sym: str, ex: dict, mgr_pairs: list) -> dict:
    """构造退出计划(七阶段,shadow)。从 exec-manager config 找该币在管腿。"""
    state = ex.get("state")
    full_exit = state == "EXIT_REQUIRED"
    pair_cfg = next((p for p in mgr_pairs
                     if (p.get("symbol") or p.get("pair")) == sym), None)
    legs = [{"venue": lc.get("venue"), "symbol": lc.get("symbol") or sym}
            for lc in ((pair_cfg or {}).get("legs") or [])]
    fraction = 1.0 if full_exit else REDUCE_FRACTION
    armed_this = ARMED and sym in ARM_SYMBOLS
    return {
        "symbol": sym, "state": state,
        "intent": "FULL_EXIT" if full_exit else "PARTIAL_REDUCE",
        "fraction": fraction,
        "reasons": ex.get("reasons") or [],
        "l_now": ex.get("l_now"),
        "closeout_pnl_net": ex.get("closeout_pnl_net"),
        "legs": legs,
        "mode": "armed" if armed_this else "shadow",
        "stages": [
            {"stage": "LOCK", "done": "policy.blocked_symbols 已挡新增(硬线)", "detail": "工作项禁新增(减险放行)"},
            {"stage": "CANCEL_ADDS", "action": ("would_cancel" if not armed_this else "cancel"),
             "detail": "撤该币加仓类挂单(reduce-only 不撤)"},
            {"stage": "PULL_TRUTH", "action": "read_positions", "detail": "直拉各腿实盘持仓(只读,不缓存陈旧)"},
            {"stage": "PREVIEW", "action": "closeout_quote", "detail": "两腿对手侧盘口退出预演(费/滑点/放弃funding)"},
            {"stage": "SHARD_REDUCE", "action": ("would_reduce_pair" if not armed_this else "reduce_pair"),
             "detail": f"两腿同比 reduce-only {int(fraction*100)}%(exec_core.reduce_pair;单腿败→隔离)"},
            {"stage": "RESCUE", "action": "on_single_leg_fail", "detail": "单腿失衡→补救或第三腿临时对冲(armed 专场)"},
            {"stage": "RECON", "action": "reconcile", "detail": "持仓/负债/订单与实盘对账一致才结案"},
            {"stage": "SETTLE", "action": "ledger_confirm", "detail": "账本确认 + Incident 结案"},
        ],
    }


async def plan_and_publish(r):
    """常驻调用(manager loop 每轮或独立):生成退出计划并发布。shadow=零下单。
    返回 (n_plans, n_armed) 供心跳。"""
    items = await _exit_items(r)
    mgr_pairs = []
    try:
        cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
        mgr_pairs = cfg.get("pairs") or []
    except Exception:  # noqa: BLE001
        pass
    plans, n_armed = {}, 0
    for sym, ex in items.items():
        p = _plan_for(sym, ex, mgr_pairs)
        if p["mode"] == "armed":
            n_armed += 1
        plans[sym] = p
    await r.set(SAGA_KEY, json.dumps({
        "plans": plans, "count": len(plans), "armed_count": n_armed,
        "global_armed": ARMED, "arm_symbols": sorted(ARM_SYMBOLS),
        "note": ("shadow:退出计划只规划不下单" if not ARMED else
                 f"armed:仅 {sorted(ARM_SYMBOLS)} 执行,须盯盘"),
        "ts": time.time()}, ensure_ascii=False, default=str), ex=600)
    return len(plans), n_armed


async def execute_plan(sym: str, plan: dict, executor, adapters, store, r):
    """armed 执行(独立放行项;shadow 下本函数不被调用)。
    分片=exec_core.reduce_pair;全平=close_pair。两腿 reduce-only 永放行,单腿败→QUARANTINED。
    ⚠真金:仅当 plan['mode']=='armed' 且 DCM_RISK_EXIT_ARMED=true 才走到这里。"""
    if plan.get("mode") != "armed":
        return {"skipped": "shadow", "symbol": sym}
    legs = []
    for lc in plan.get("legs") or []:
        v, vsym = lc["venue"], lc["symbol"]
        p = await adapters[v].get_position(vsym)
        if not p.get("ok"):
            return {"symbol": sym, "action": f"VENUE_READ_FAIL({v}),零下单", "reconcile": "abort"}
        amt = float(p.get("amt") or 0)
        legs.append({"venue": v, "symbol": vsym, "market": "perp", "qty": abs(amt),
                     "side": "BUY" if amt > 0 else "SELL"})
    saga_id = f"rex-{sym}-{int(time.time())}"
    if plan["intent"] == "FULL_EXIT":
        res = await executor.close_pair(saga_id, legs)
    else:
        res = await executor.reduce_pair(saga_id, legs, plan["fraction"], step_ns="rex")
    return {"symbol": sym, "saga_id": saga_id, "result": res, "intent": plan["intent"]}
