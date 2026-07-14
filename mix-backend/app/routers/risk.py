"""G0 风险策略只读+操作员覆盖(V5 补充说明 ADR-001/002)。

铁律:风险策略权威=risk-ledger(唯一计算/发布者);mix-backend 只做:
  - 读 dcm:risk:policy(Redis 快照)与 risk_venue_cap/override(dcm_main,mix_ro)供 UI 全局风险条;
  - 操作员写=向 risk_policy_override **append**(dcm_main,mix_ro 仅授 INSERT)+ cap UPDATE;
    绝不直接写 dcm:risk:policy(那是 risk-ledger 的活),下一轮(≤30s)risk-ledger 合并生效。
"""
import json

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_viewer, require_operator
from .. import datasources as ds
from .. import proxy

router = APIRouter()

_MODES = ("NORMAL", "WATCH", "NO_NEW_RISK", "REDUCE_ONLY", "EXIT_ONLY", "FROZEN")
_SCOPES = ("VENUE", "ACCOUNT", "GLOBAL", "SYMBOL")


@router.get("/risk/overview")
async def risk_overview(_who=Depends(require_viewer)):
    """全局风险条数据源:各 venue 有效模式/敞口/上限 + 受限汇总。快照缺失=STALE(前端 fail-closed 展示)。"""
    pol = await ds.get_json("dcm:risk:policy")
    if not pol:
        return {"stale": True, "note": "risk-ledger 未发布策略(或快照超龄)", "venues": {}, "capped": []}
    import time
    age = int(time.time() - float(pol.get("ts") or 0))
    venues = pol.get("venues") or {}
    total_exposure = sum(float(v.get("exposure_notional") or 0) for v in venues.values())
    restricted_equity = sum(float(v.get("equity") or 0) for v in venues.values()
                            if v.get("mode") not in ("NORMAL",))
    return {
        "stale": age > 90, "age_sec": age, "policy_version": pol.get("policy_version"),
        "global_mode": pol.get("global_mode", "NORMAL"),
        "capped_venues": pol.get("capped_venues") or [],
        "capped_count": len(pol.get("capped_venues") or []),
        "total_exposure_usdt": round(total_exposure, 2),
        "restricted_equity_usdt": round(restricted_equity, 2),
        "venues": venues,
    }


@router.get("/risk/caps")
async def risk_caps(_who=Depends(require_viewer)):
    pool = await ds.pg()
    if pool is None:
        return {"caps": [], "note": "dcm_main 不可达"}
    rows = await pool.fetch("SELECT scope_key, tier, max_notional_usdt, warn_ratio, enabled, note, "
                            "updated_by, updated_at FROM risk_venue_cap ORDER BY scope_key")
    return {"caps": [dict(r) for r in rows]}


@router.put("/risk/caps")
async def risk_cap_put(body: dict, op=Depends(require_operator)):
    """设置/更新逐 venue 敞口上限(risk-ledger 下一轮读取生效)。"""
    scope_key = str(body.get("scope_key") or "").strip()
    if not scope_key or ":" not in scope_key:
        raise HTTPException(400, "scope_key 必须形如 venue:binance 或 account:xxx")
    try:
        max_notional = float(body["max_notional_usdt"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "max_notional_usdt 必填且为数字")
    tier = str(body.get("tier") or "B").upper()[:12]
    warn_ratio = float(body.get("warn_ratio") or 0.85)
    enabled = bool(body.get("enabled", True))
    pool = await ds.pg()
    if pool is None:
        raise HTTPException(503, "dcm_main 不可达")
    await pool.execute(
        "INSERT INTO risk_venue_cap(scope_key,tier,max_notional_usdt,warn_ratio,enabled,note,updated_by,updated_at)"
        " VALUES($1,$2,$3,$4,$5,$6,$7,now()) ON CONFLICT (scope_key) DO UPDATE SET "
        "tier=$2, max_notional_usdt=$3, warn_ratio=$4, enabled=$5, note=$6, updated_by=$7, updated_at=now()",
        scope_key, tier, max_notional, warn_ratio, enabled, str(body.get("note") or "")[:200], op["operator"])
    await proxy.audit(op["operator"], op["role"], "risk.cap.put", scope_key, body, "saved")
    return {"saved": True, "scope_key": scope_key, "note": "risk-ledger ≤30s 内读取生效"}


@router.get("/risk/overrides")
async def risk_overrides(_who=Depends(require_viewer)):
    """当前生效的手动覆盖(每 scope 最新未过期一条)+ 近期历史。"""
    pool = await ds.pg()
    if pool is None:
        return {"active": [], "history": []}
    active = await pool.fetch(
        "SELECT DISTINCT ON (scope_type, scope_key) scope_type, scope_key, mode, reason, expires_at, "
        "created_by, created_at FROM risk_policy_override "
        "WHERE expires_at IS NULL OR expires_at > now() "
        "ORDER BY scope_type, scope_key, id DESC")
    history = await pool.fetch(
        "SELECT scope_type, scope_key, mode, reason, expires_at, created_by, created_at "
        "FROM risk_policy_override ORDER BY id DESC LIMIT 50")
    return {"active": [dict(r) for r in active], "history": [dict(r) for r in history]}


@router.post("/risk/overrides")
async def risk_override_add(body: dict, op=Depends(require_operator)):
    """操作员手动风险模式覆盖(append-only)。解除=对同 scope 追加 NORMAL。
    risk-ledger 下一轮合并(取自动判定与覆盖的最严格值);仅能更严格,NORMAL 覆盖=解除人工加压。"""
    scope_type = str(body.get("scope_type") or "").upper()
    if scope_type not in _SCOPES:
        raise HTTPException(400, f"scope_type 必须∈{_SCOPES}")
    mode = str(body.get("mode") or "").upper()
    if mode not in _MODES:
        raise HTTPException(400, f"mode 必须∈{_MODES}")
    scope_key = str(body.get("scope_key") or ("GLOBAL" if scope_type == "GLOBAL" else "")).strip()
    if not scope_key:
        raise HTTPException(400, "scope_key 必填(GLOBAL 除外)")
    expires_at = body.get("expires_at")   # ISO8601 或 null
    pool = await ds.pg()
    if pool is None:
        raise HTTPException(503, "dcm_main 不可达")
    await pool.execute(
        "INSERT INTO risk_policy_override(scope_type,scope_key,mode,reason,expires_at,created_by) "
        "VALUES($1,$2,$3,$4,$5,$6)",
        scope_type, scope_key, mode, str(body.get("reason") or "")[:300], expires_at, op["operator"])
    await proxy.audit(op["operator"], op["role"], "risk.override", f"{scope_type}:{scope_key}", body, mode)
    return {"saved": True, "scope": f"{scope_type}:{scope_key}", "mode": mode,
            "note": "risk-ledger ≤30s 内合并生效"}


@router.get("/risk/corebox")
async def risk_corebox(_who=Depends(require_viewer)):
    """CORE_POOL 封闭盒子组状态:成员(主+子账户)、逐户权益、组总权益。
    封闭盒子=book=CORE_POOL 的账户组;提现处处关,组总权益只应因入金+PnL 变化。"""
    from .. import adapters
    st = await adapters.corebox_state()
    baseline = await ds.get_json("dcm:risk:corebox:baseline") or {}
    st["baseline_equity_usdt"] = baseline.get("equity_usdt")
    st["monitor"] = await ds.get_json("dcm:risk:corebox:monitor") or {"note": "监控未就绪"}
    return st


@router.put("/accounts/{account_key}/mode")
async def set_account_mode(account_key: str, body: dict, op=Depends(require_operator)):
    """#5 设账户模式(account_mode)——决定该账户能跑什么策略(经资格矩阵)。
    classic=经典钱包分离(C3);portfolio_margin=统一账户(借贷套利)。"""
    mode = str(body.get("account_mode") or "").strip()
    if mode not in ("classic", "portfolio_margin", "cross_margin", "isolated", "unknown"):
        raise HTTPException(400, "account_mode 须∈ classic/portfolio_margin/cross_margin/isolated/unknown")
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "dcm_main 不可达")
    n = await pool.execute("UPDATE accounts_registry SET account_mode=$2, updated_at=now() WHERE account_key=$1",
                           account_key, mode)
    if n.endswith("0"):
        raise HTTPException(404, f"账户 {account_key} 不存在")
    await proxy.audit(op["operator"], op["role"], "account.set_mode", account_key, {"mode": mode}, "saved")
    return {"saved": True, "account_key": account_key, "account_mode": mode}


@router.get("/risk/eligibility")
async def eligibility_matrix(_who=Depends(require_viewer)):
    """策略×账户模式资格矩阵(单一权威)。opener/executor 据此门控账户能跑哪些策略。"""
    pool = await ds.pg_main()
    if pool is None:
        return {"matrix": []}
    rows = await pool.fetch("SELECT strategy, account_mode, eligibility, reason, updated_at "
                            "FROM strategy_account_eligibility ORDER BY strategy, account_mode")
    return {"matrix": [dict(r) for r in rows]}


@router.put("/risk/eligibility")
async def eligibility_put(body: dict, op=Depends(require_operator)):
    """改资格矩阵一格(strategy×account_mode→eligibility)。政策可配,不硬编码。"""
    strategy = str(body.get("strategy") or "").strip()
    mode = str(body.get("account_mode") or "").strip()
    elig = str(body.get("eligibility") or "").strip().upper()
    if not strategy or not mode or elig not in ("PREFERRED", "ALLOWED", "FORBIDDEN"):
        raise HTTPException(400, "strategy/account_mode 必填,eligibility∈PREFERRED/ALLOWED/FORBIDDEN")
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "dcm_main 不可达")
    await pool.execute(
        "INSERT INTO strategy_account_eligibility(strategy,account_mode,eligibility,reason,updated_by,updated_at) "
        "VALUES($1,$2,$3,$4,$5,now()) ON CONFLICT (strategy,account_mode) DO UPDATE SET "
        "eligibility=$3, reason=$4, updated_by=$5, updated_at=now()",
        strategy, mode, elig, str(body.get("reason") or "")[:200], op["operator"])
    await proxy.audit(op["operator"], op["role"], "eligibility.put", f"{strategy}:{mode}", body, elig)
    return {"saved": True}


@router.get("/risk/restrictions")
async def risk_restrictions(_who=Depends(require_viewer)):
    """账户限制原始事实(近 100 条;V5 §6.3)。"""
    pool = await ds.pg()
    if pool is None:
        return {"events": []}
    rows = await pool.fetch(
        "SELECT venue, account_key, scope, signal_type, source_type, severity, raw_code, http_status, "
        "endpoint, first_seen, last_seen, hit_count FROM restriction_event ORDER BY last_seen DESC LIMIT 100")
    return {"events": [dict(r) for r in rows]}
