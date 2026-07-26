"""规则中心 —— 读：dcm engine_config 真值；写(P2)：代理 gateway engine_config API
（令牌透传保留操作者身份，RBAC/武装联锁/confirm=ARM/审计全在 gateway），绝不直写引擎库。"""
import json
from fastapi import APIRouter, Query, Depends, Header, HTTPException
from ..schemas import RulesResponse, RuleField
from ..deps import require_operator, require_viewer, not_wired
from .. import datasources as ds
from .. import proxy

router = APIRouter(prefix="/rules", tags=["rules"])


async def _engine_config_fields(engine: str) -> list[RuleField]:
    rows = await ds.fetch(
        "SELECT ckey, cval, version, updated_by, updated_at FROM engine_config "
        "WHERE engine = $1 ORDER BY ckey", engine)
    return [RuleField(key=r["ckey"], label=r["ckey"], value=str(r["cval"]),
                      unit=f"v{r['version']}·{r['updated_by']}", inherited=False)
            for r in rows]


@router.get("", response_model=RulesResponse)
async def get_rules(scope: str = Query(...), _who=Depends(require_viewer)):
    """P0 真读范围：strategy:S2 = dcm engine_config 全量键（armed/Kill 等热配置的事实值）。
    其余作用域引擎侧尚无对应读点 —— 返回空集而非假模板（防『UI 写了引擎不读』病）。"""
    engine_of_scope = {"strategy:S2": "dualperp", "strategy:S1": "basis",
                       "strategy:S4": "lending", "global": "global"}
    eng = engine_of_scope.get(scope)
    if eng:
        fields = await _engine_config_fields(eng)
        # S1/S4 引擎 env 控制无 engine_config 行时,回落总线快照展示当前生效值（只读参考,不空手）
        if not fields and scope in ("strategy:S1", "strategy:S4"):
            snap_key = {"strategy:S1": "dcm:engine:basis:positions",
                        "strategy:S4": "dcm:engine:lending:positions"}[scope]
            snap = await ds.get_json(snap_key) or {}
            ref = {"模式": snap.get("mode"), "武装名单": ",".join(snap.get("arm") or []) or "—",
                   "在场": snap.get("slots") or snap.get("armed_holdings")}
            fields = [RuleField(key=k, label=k, value=str(v), unit="只读·引擎env", inherited=True)
                      for k, v in ref.items() if v is not None]
        return RulesResponse(scope=scope, fields=fields)
    if scope == "strategy:S3":
        # coin 全局规则真源（桥 60s 快照;字段=coin GlobalRulesResponse 全集,coin schema 权威）
        panel = await ds.get_json("dcm:coin:panel") or {}
        cr = panel.get("rules")
        if isinstance(cr, dict):
            skip = {"id", "user_id", "created_at", "updated_at"}
            fields = [RuleField(key=k, label=k, value=str(v), inherited=False)
                      for k, v in cr.items() if k not in skip]
            return RulesResponse(scope=scope, fields=fields)
    return RulesResponse(scope=scope, fields=[])


@router.put("/{scope_key}")
async def put_rules(scope_key: str, body: dict, op=Depends(require_operator),
                    x_op_token: str | None = Header(default=None)):
    """写代理（差分写，防全量重写刷审计）：
    S2 → gateway engine_config（联锁/confirm=ARM 原地生效）；
    S3 → coin 命令队列 rules_update（coin schema 校验+审计+30s 热重载权威）。"""
    if scope_key == "strategy:S3":
        panel = await ds.get_json("dcm:coin:panel") or {}
        current = panel.get("rules") or {}
        changed = {}
        for f in (body.get("fields") or []):
            k, v = str(f.get("key", "")), f.get("value")
            if k and k in current and str(current.get(k)) != str(v):
                changed[k] = v
        if not changed:
            return {"saved": False, "applied": [], "rejected": [], "note": "无变更"}
        res = await proxy.coin_cmd("rules_update", changed, op["operator"], timeout_sec=10)
        await proxy.audit(op["operator"], op["role"], "rules.s3.update", "coin.global_rules",
                          changed, "ok" if res.get("ok") else str(res)[:120])
        if not res.get("ok"):
            raise HTTPException(502, f"coin 侧拒绝：{res.get('err') or res.get('body')}")
        after = res.get("body") or {}
        verified = {k: (str(after.get(k)) == str(v)) for k, v in changed.items()}
        return {"saved": True, "applied": list(changed), "verified": verified,
                "rejected": [], "hotReloadSec": 30, "uniqueRow": True,
                "note": "coin 引擎 30s 轮询回读生效"}
    if scope_key != "strategy:S2":
        not_wired(f"规则保存 {scope_key}（该作用域引擎侧尚无权威写点）")
    fields = body.get("fields") or []
    current = {f.key: f.value for f in await _engine_config_fields("dualperp")}
    applied, rejected = [], []
    for f in fields:
        key, val = str(f.get("key", "")), str(f.get("value", ""))
        if not key or current.get(key) == val:
            continue
        status, data = await proxy.gateway_engine_config(x_op_token, key, val, f.get("confirm"))
        if status < 400:
            applied.append(key)
        else:
            rejected.append({"key": key, "status": status,
                             "error": data.get("error") or str(data)[:120]})
    # 断言式生效验证（QH timing_configs 教训）：回读 DB 确认值真的落了
    verified = {}
    if applied:
        ds._cache.clear()
        after = {f.key: f.value for f in await _engine_config_fields("dualperp")}
        verified = {k: (after.get(k) == next((str(f.get("value")) for f in fields
                                              if f.get("key") == k), None))
                    for k in applied}
    return {"saved": bool(applied), "applied": applied, "verified": verified,
            "rejected": rejected, "hotReloadSec": 3, "uniqueRow": True}


# 单一规则字段按策略自适应——S3=coin SymbolRule 9 列(可写权威);
# S2/S1=该策略引擎参数(引擎全局,单币覆盖引擎未接→只读展示,如实标 writable=false 引导走通用规则);
# S4/S5/S6=策略未建/无单币覆盖。绝不给假可写。
S3_SYMBOL_FIELDS = [
    ("borrow_spread", "挂单差"), ("open_spread", "开点差"), ("close_spread", "平点差"),
    ("remove_spread", "移除差"), ("order_amount", "单笔挂单"), ("max_borrow_amount", "金额限制"),
    ("close_funding_ratio", "平资息"), ("repay_spread", "还币开"), ("repay_funding_ratio", "还资息"),
]
# 其它策略的"单币参数"概念字段(只读参考,取自引擎全局 engine_config)
S2_SYMBOL_REF = [("mode", "运行模式"), ("arm_mode", "武装方式"),
                 ("max_notional_hard", "单币硬顶U"), ("max_portfolio_notional", "组合上限U")]
S1_SYMBOL_REF = []


@router.get("/symbol/{symbol}")
async def get_symbol_rule(symbol: str, strategy: str = Query(default="S3"), op=Depends(require_operator)):
    """读某币单一规则,字段按策略自适应。"""
    if strategy == "S3":
        res = await proxy.coin_cmd("symbol_rule_get", {"symbol": symbol}, op["operator"], timeout_sec=12)
        cur = res.get("body") if res.get("ok") and isinstance(res.get("body"), dict) else {}
        panel = await ds.get_json("dcm:coin:panel") or {}
        base = panel.get("rules") or {}
        return {"symbol": symbol, "strategy": "S3", "writable": True,
                "note": "coin SymbolRule 权威·留空=回落批量/全局基线",
                "fields": [{"key": k, "label": lb, "value": cur.get(k), "baseline": base.get(k)}
                           for k, lb in S3_SYMBOL_FIELDS]}
    if strategy in ("S2", "S1"):
        ref = S2_SYMBOL_REF if strategy == "S2" else S1_SYMBOL_REF
        eng = {"S2": "dualperp", "S1": "basis"}[strategy]
        rows = await ds.fetch("SELECT ckey, cval FROM engine_config WHERE engine=$1", eng)
        cfg = {r["ckey"]: r["cval"] for r in rows}
        return {"symbol": symbol, "strategy": strategy, "writable": False,
                "note": f"{strategy} 为引擎全局参数(非单币覆盖)——改参数请用「通用规则」；此处仅展示当前生效值。",
                "fields": [{"key": k, "label": lb, "value": cfg.get(k), "baseline": None} for k, lb in ref]}
    return {"symbol": symbol, "strategy": strategy, "writable": False,
            "note": f"{strategy} 策略未建 / 无单币规则。", "fields": []}


@router.put("/symbol/{symbol}")
async def put_symbol_rule(symbol: str, body: dict, op=Depends(require_operator)):
    """写某币单一规则——仅 S3 可写（coin SymbolRule 权威）。其余策略引擎全局,拒绝并引导。"""
    strategy = str(body.get("strategy") or "S3")
    if strategy != "S3":
        raise HTTPException(422, f"{strategy} 无单币覆盖（引擎全局参数），请用「通用规则」修改")
    changed = {f["key"]: f.get("value") for f in (body.get("fields") or [])
               if f.get("key") in {k for k, _ in S3_SYMBOL_FIELDS}}
    res = await proxy.coin_cmd("symbol_rule_put", {"symbol": symbol, **changed}, op["operator"], timeout_sec=12)
    await proxy.audit(op["operator"], op["role"], "rules.symbol", symbol, changed,
                      "ok" if res.get("ok") else str(res)[:120])
    if not res.get("ok"):
        raise HTTPException(502, f"coin 拒绝：{res.get('err') or res.get('body')}")
    return {"saved": True, "applied": list(changed), "hotReloadSec": 30,
            "note": "coin 引擎 30s 轮询回读生效"}


# ==== 单一规则矩阵（coin SymbolRuleDialog 1:1：批量行=SymbolRule 基线 + 各子账户行=AccountSymbolRule 覆盖） ====

@router.get("/symbol/{symbol}/matrix")
async def get_symbol_rule_matrix(symbol: str, op=Depends(require_operator)):
    """S3 单一规则矩阵读：批量基线 + 逐子账户覆盖 + 持币（panel symbol_margin 实时快照）。"""
    import asyncio as _aio
    sym = symbol.upper()
    panel = await ds.get_json("dcm:coin:panel") or {}
    grules = panel.get("rules") or {}
    accts = (panel.get("balances") or {}).get("balances") or []
    results = await _aio.gather(
        proxy.coin_cmd("symbol_rule_get", {"symbol": sym}, op["operator"], timeout_sec=12),
        *[proxy.coin_cmd("account_symbol_rule_get", {"sub": a["account_id"], "symbol": sym},
                         op["operator"], timeout_sec=12) for a in accts])
    common_res, acct_res = results[0], results[1:]
    common = common_res.get("body") if common_res.get("ok") and isinstance(common_res.get("body"), dict) else {}
    keys = [k for k, _ in S3_SYMBOL_FIELDS]
    rows = []
    for a, res in zip(accts, acct_res):
        r = res.get("body") if res.get("ok") and isinstance(res.get("body"), dict) else {}
        sm = (a.get("symbol_margin") or {}).get(sym) or {}
        rows.append({"sub": a["account_id"], "note": str(a.get("note") or f"sub:{a['account_id']}"),
                     "held": {"borrowed": float(sm.get("borrowed") or 0),
                              "interest": float(sm.get("interest") or 0)},
                     "rules": {k: r.get(k) for k in keys}})
    return {"symbol": sym, "writable": True,
            "cols": [{"key": k, "label": lb} for k, lb in S3_SYMBOL_FIELDS],
            "globalBaseline": {k: grules.get(k) for k in keys},
            "common": {**{k: common.get(k) for k in keys},
                       "allow_remove": common.get("allow_remove"),
                       "allow_repay": common.get("allow_repay")},
            "accounts": rows}


@router.put("/symbol/{symbol}/matrix")
async def put_symbol_rule_matrix(symbol: str, body: dict, op=Depends(require_operator)):
    """S3 单一规则矩阵写：common→symbol_rule_put(批量基线)；accounts→account_symbol_rule_batch。
    值语义对齐 coin：空串→null=清覆盖回落跟随；coin schema/审计/0 秒热重载权威。"""
    sym = symbol.upper()
    allowed = {k for k, _ in S3_SYMBOL_FIELDS}

    def _san(fields: dict) -> dict:
        out = {}
        for k, v in (fields or {}).items():
            if k not in allowed:
                continue
            out[k] = None if v in ("", None) else v
        return out

    applied = []
    common = body.get("common")
    if isinstance(common, dict):
        payload = _san(common)
        payload["is_temporary"] = True
        for bk in ("allow_remove", "allow_repay"):
            if common.get(bk) is not None:
                payload[bk] = bool(common[bk])
        res = await proxy.coin_cmd("symbol_rule_put", {"symbol": sym, **payload},
                                   op["operator"], timeout_sec=12)
        if not res.get("ok"):
            raise HTTPException(502, f"coin 批量行拒绝：{res.get('err') or res.get('body')}")
        applied.append("common")
    items = []
    for a in (body.get("accounts") or []):
        try:
            sub = int(a.get("sub"))
        except (TypeError, ValueError):
            continue
        items.append({"sub_account_id": sub, "symbol": sym, "data": _san(a.get("fields") or {})})
    if items:
        res = await proxy.coin_cmd("account_symbol_rule_batch", {"items": items},
                                   op["operator"], timeout_sec=12)
        if not res.get("ok"):
            raise HTTPException(502, f"coin 账户行拒绝：{res.get('err') or res.get('body')}")
        applied += [f"sub:{i['sub_account_id']}" for i in items]
    await proxy.audit(op["operator"], op["role"], "rules.symbol.matrix", sym,
                      {"common": bool(common), "accounts": len(items)}, "ok")
    return {"saved": bool(applied), "applied": applied, "hotReloadSec": 0,
            "note": "coin 规则热重载事件驱动(0 秒),持币/挂单按新值立即生效"}


# ==== 通用规则·自动划转 + 子账户资金参数表（coin RulesPage 红框区 1:1） ====

@router.get("/fund/s3")
async def get_fund_rules_s3(op=Depends(require_operator)):
    """自动划转(fund-rules) + 主账户可转余额 + 子账户资金参数&实时余额。"""
    import asyncio as _aio
    fr_res, mb_res, sa_res = await _aio.gather(
        proxy.coin_cmd("fund_rules_get", {}, op["operator"], timeout_sec=12),
        proxy.coin_cmd("master_balance", {}, op["operator"], timeout_sec=12),
        proxy.coin_cmd("sub_accounts_get", {}, op["operator"], timeout_sec=12))
    panel = await ds.get_json("dcm:coin:panel") or {}
    bal_by_id = {a.get("account_id"): a
                 for a in (panel.get("balances") or {}).get("balances") or []}
    accounts = []
    sa = sa_res.get("body") if sa_res.get("ok") and isinstance(sa_res.get("body"), list) else []
    for a in sa:
        bal = bal_by_id.get(a.get("id")) or {}
        accounts.append({
            "sub": a.get("id"), "note": a.get("note"), "enabled": a.get("is_enabled"),
            "balance": {k: bal.get(k) for k in
                        ("bnb_free", "bnb_interest", "margin_usdt_borrowed", "futures_total",
                         "futures_available", "margin_usdt_free", "margin_level")},
            "params": {k: a.get(k) for k in
                       ("risk_threshold", "single_transfer_amount", "min_balance",
                        "single_order_amount", "max_borrow_amount")},
        })
    return {"fundRules": fr_res.get("body") if fr_res.get("ok") else None,
            "masterBalance": mb_res.get("body") if mb_res.get("ok") else None,
            "accounts": accounts}


@router.put("/fund/s3")
async def put_fund_rules_s3(body: dict, op=Depends(require_operator)):
    """写：fundRules 差分→fund_rules_put；accounts[].params→fund_params_patch(逐账户)。"""
    applied = []
    fr = body.get("fundRules")
    if isinstance(fr, dict) and fr:
        res = await proxy.coin_cmd("fund_rules_put", fr, op["operator"], timeout_sec=12)
        if not res.get("ok"):
            raise HTTPException(502, f"coin fund-rules 拒绝：{res.get('err') or res.get('body')}")
        applied.append("fund_rules")
    for a in (body.get("accounts") or []):
        try:
            sub = int(a.get("sub"))
        except (TypeError, ValueError):
            continue
        params = {k: (None if v == "" else v) for k, v in (a.get("params") or {}).items()
                  if k in ("risk_threshold", "single_transfer_amount", "min_balance",
                           "single_order_amount", "max_borrow_amount", "order_amount",
                           "base_margin_amount")}
        if not params:
            continue
        res = await proxy.coin_cmd("fund_params_patch", {"sub": sub, **params},
                                   op["operator"], timeout_sec=12)
        if not res.get("ok"):
            raise HTTPException(502, f"coin 资金参数拒绝(sub {sub})：{res.get('err') or res.get('body')}")
        applied.append(f"sub:{sub}")
    await proxy.audit(op["operator"], op["role"], "rules.fund.s3", "coin.fund",
                      {"applied": applied}, "ok")
    return {"saved": bool(applied), "applied": applied}


@router.get("/{scope_key}/audit")
async def rules_audit(scope_key: str, _who=Depends(require_viewer)):
    rows = await ds.fetch(
        "SELECT ts, operator, action, target, result FROM admin_audit ORDER BY ts DESC LIMIT 30")
    return [{"at": r["ts"].strftime("%m-%d %H:%M"), "user": r["operator"], "scope": scope_key,
             "field": f"{r['action']} {r['target']}".strip(), "change": str(r["result"])[:120]}
            for r in rows]


# ==== opener 护栏配置(C2 自动开仓守卫:额度上限/深度硬闸/单币频率限制) ====

@router.get("/opener")
async def get_opener_guards(_who=Depends(require_viewer)):
    """读 opener 护栏配置 + 当前快照(候选/在管名义/gate 状态)。
    权威=dcm:exec:opener:guards(Redis JSON,operator 写);opener 每轮读并 overlay env 默认。"""
    r = ds.rds()
    if r is None:
        raise HTTPException(503, "redis 未配置")
    guards_raw = await r.get("dcm:exec:opener:guards")
    guards = {}
    if guards_raw:
        try:
            guards = json.loads(guards_raw)
        except Exception:  # noqa: BLE001
            pass
    # opener 快照(含 gate 实时状态)
    snap = await ds.get_json("dcm:exec:opener") or {}
    gate = snap.get("gate") or {}
    return {"guards": guards, "snapshot": {"ts": snap.get("ts"), "candidate_count": snap.get("candidate_count"),
            "gate": gate}, "fields_meta": {
        "depth_enforce": {"label": "深度硬闸", "type": "bool", "tip": "THIN 直接跳过(默认 ON)"},
        "depth_k": {"label": "深度系数", "tip": "一档额须≥目标名义×K", "suffix": "x"},
        "hold_hours": {"label": "持有窗口", "suffix": "小时", "tip": "funding 收益按持有窗折算"},
        "fee_bps_per_fill": {"label": "单次成交费", "suffix": "bps"},
        "est_roundtrip_cost_bps": {"label": "往返价差估计", "suffix": "bps"},
        "min_net_daily_pct": {"label": "净日费率≥", "suffix": "%"},
        "min_e_bps": {"label": "经济期望≥", "suffix": "bps"},
        "max_notional_per_candidate_usdt": {"label": "单币额度上限", "suffix": "U"},
        "max_total_armed_notional_usdt": {"label": "总额度上限", "suffix": "U"},
        "max_concurrent_positions": {"label": "并发仓位上限", "suffix": "个"},
        "per_symbol_cooldown_sec": {"label": "单币冷却", "suffix": "秒", "tip": "平仓后该币冷却期内不进候选"},
    }}


@router.put("/opener")
async def put_opener_guards(body: dict, op=Depends(require_operator)):
    """写 opener 护栏配置(差分 + 审计);opener 下一轮(60s)热读生效。"""
    r = ds.rds()
    if r is None:
        raise HTTPException(503, "redis 未配置")
    allowed = {"depth_enforce", "depth_k", "hold_hours", "fee_bps_per_fill", "est_roundtrip_cost_bps",
               "min_net_daily_pct", "min_e_bps", "max_notional_per_candidate_usdt",
               "max_total_armed_notional_usdt", "max_concurrent_positions", "per_symbol_cooldown_sec"}
    guards_raw = await r.get("dcm:exec:opener:guards")
    current = {}
    if guards_raw:
        try:
            current = json.loads(guards_raw)
        except Exception:  # noqa: BLE001
            pass
    changed = {}
    for k, v in (body.get("guards") or {}).items():
        if k not in allowed:
            continue
        if k == "depth_enforce":
            v = bool(v)
        elif k in ("max_concurrent_positions",):
            v = int(v) if v not in (None, "") else None
        else:
            try:
                v = float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                v = None
        if current.get(k) != v:
            changed[k] = v
    if not changed:
        return {"saved": False, "applied": [], "note": "无变更"}
    merged = {**current, **changed}
    await r.set("dcm:exec:opener:guards", json.dumps(merged, ensure_ascii=False))
    await proxy.audit(op["operator"], op["role"], "rules.opener", "dcm:exec:opener:guards",
                      changed, "ok")
    return {"saved": True, "applied": list(changed), "hotReloadSec": 60,
            "note": "opener 每轮(60s)读配置生效;深度/额度/频率三闸已 enforce"}


@router.post("/dry-run")
async def rules_dry_run(body: dict, _who=Depends(require_viewer)):
    """规则发布流程 dry-run(N2yrk:草稿→schema校验→影响预览→dry-run)。
    只算不写:字段 schema 校验 + 差异(current vs draft)+ 影响面预估。绝不落任何写入。"""
    scope_key = str(body.get("scope_key") or "")
    fields = body.get("fields") or []
    # 取当前值
    current = {}
    if scope_key == "strategy:S3":
        panel = await ds.get_json("dcm:coin:panel") or {}
        current = panel.get("rules") or {}
    elif scope_key == "strategy:S2":
        try:
            current = {f.key: f.value for f in await _engine_config_fields("dualperp")}
        except Exception:
            current = {}
    diff, schema_errors = [], []
    for f in fields:
        k, v = str(f.get("key", "")), f.get("value")
        if not k:
            continue
        old = current.get(k)
        # schema 校验:数值字段须可转 float(点差/金额/比例类)
        if any(t in k for t in ("spread", "amount", "ratio", "notional", "funding")):
            try:
                float(v)
            except (TypeError, ValueError):
                schema_errors.append({"key": k, "error": f"须数值,得到 '{v}'"})
                continue
        if str(old) != str(v):
            diff.append({"key": k, "old": old, "new": v})
    # 影响面预估:S3 影响在管坑位数;S2 影响活跃路由数
    impact = {}
    if scope_key == "strategy:S3":
        snap = await ds.get_json("dcm:engine:coin:positions") or {}
        impact["affected_open_pits"] = len([p for p in (snap.get("positions") or [])
                                            if p.get("status") not in ("CLOSED", "FAILED")])
        impact["hot_reload_sec"] = 30
    elif scope_key == "strategy:S2":
        ra = await ds.hgetall_json("dcm:route:assignments")
        impact["active_routes"] = len([r for r in (ra or {}).values()
                                       if (r or {}).get("state") == "active"])
        impact["hot_reload_sec"] = 3
    return {"scope_key": scope_key, "diff": diff, "diff_count": len(diff),
            "schema_errors": schema_errors, "schema_ok": not schema_errors,
            "impact": impact,
            "note": "dry-run 只算不写;发布须重新认证(TOTP)+确认;发布后冷却观察,可回滚上一版"}
