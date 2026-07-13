"""规则中心 —— 读：dcm engine_config 真值；写(P2)：代理 gateway engine_config API
（令牌透传保留操作者身份，RBAC/武装联锁/confirm=ARM/审计全在 gateway），绝不直写引擎库。"""
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


@router.get("/{scope_key}/audit")
async def rules_audit(scope_key: str, _who=Depends(require_viewer)):
    rows = await ds.fetch(
        "SELECT ts, operator, action, target, result FROM admin_audit ORDER BY ts DESC LIMIT 30")
    return [{"at": r["ts"].strftime("%m-%d %H:%M"), "user": r["operator"], "scope": scope_key,
             "field": f"{r['action']} {r['target']}".strip(), "change": str(r["result"])[:120]}
            for r in rows]
