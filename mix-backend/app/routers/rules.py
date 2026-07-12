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
    engine_of_scope = {"strategy:S2": "dualperp", "strategy:S1": "basis", "global": "global"}
    eng = engine_of_scope.get(scope)
    if eng:
        fields = await _engine_config_fields(eng)
        return RulesResponse(scope=scope, fields=fields)
    return RulesResponse(scope=scope, fields=[])


@router.put("/{scope_key}")
async def put_rules(scope_key: str, body: dict, op=Depends(require_operator),
                    x_op_token: str | None = Header(default=None)):
    """S2 写代理：只转发**变更过**的键到 gateway（差分写，防全量重写刷审计/版本号）。
    mode=armed 需 confirm=ARM —— gateway 428 原样透传，武装类操作请仍走 dcm 控制台。"""
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


@router.get("/{scope_key}/audit")
async def rules_audit(scope_key: str, _who=Depends(require_viewer)):
    rows = await ds.fetch(
        "SELECT ts, operator, action, target, result FROM admin_audit ORDER BY ts DESC LIMIT 30")
    return [{"at": r["ts"].strftime("%m-%d %H:%M"), "user": r["operator"], "scope": scope_key,
             "field": f"{r['action']} {r['target']}".strip(), "change": str(r["result"])[:120]}
            for r in rows]
