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


_ACCT_MODES = [("classic", "经典"), ("portfolio_margin", "统一账户"),
               ("cross_margin", "全仓杠杆"), ("isolated", "逐仓")]


async def _enabled_strategies(pool):
    """系统已启用策略(新 C 码体系)=product_catalog 中 stage 非 NA/KILLED 的产品(排除纯能力 O1/I1/R1)。
    动态覆盖,新产品上架自动进矩阵。回落=catalog 不可读时给 CEX 主产品。"""
    if pool is not None:
        try:
            rows = await pool.fetch(
                "SELECT product_id, name FROM product_catalog "
                "WHERE stage NOT IN ('NA','KILLED') AND product_id NOT IN ('O1','I1','R1') "
                "AND product_id NOT LIKE 'D%' "   # DEX 产品不用 CEX 账户模式,不进账户模式资格矩阵
                "ORDER BY sort_order, product_id")
            if rows:
                return [(r["product_id"], r["name"]) for r in rows]
        except Exception:  # noqa: BLE001
            pass
    return [("C1", "期现收费"), ("C2", "跨所费差"), ("C3", "借币点差"),
            ("C3.R", "利率套利"), ("C4", "期现交割"), ("C5", "永续交割")]


@router.get("/risk/eligibility")
async def eligibility_matrix(_who=Depends(require_viewer)):
    """策略×账户模式资格矩阵(单一权威):**动态覆盖系统已启用全部策略(新C码)×全部账户模式**;
    未配置格默认 ALLOWED。opener/executor 据此门控账户能跑哪些策略。"""
    pool = await ds.pg_main()
    strategies = await _enabled_strategies(pool)
    configured = {}
    if pool is not None:
        try:
            for r in await pool.fetch("SELECT strategy, account_mode, eligibility, reason "
                                      "FROM strategy_account_eligibility"):
                configured[(r["strategy"], r["account_mode"])] = {"eligibility": r["eligibility"],
                                                                  "reason": r["reason"]}
        except Exception:  # noqa: BLE001
            pass
    grid = []
    for scode, sname in strategies:
        for mkey, mname in _ACCT_MODES:
            c = configured.get((scode, mkey))
            grid.append({"strategy": scode, "strategy_name": sname,
                         "account_mode": mkey, "account_mode_name": mname,
                         "eligibility": (c or {}).get("eligibility", "ALLOWED"),
                         "reason": (c or {}).get("reason"),
                         "configured": c is not None})
    return {"strategies": [{"code": s, "name": n} for s, n in strategies],
            "account_modes": [{"key": k, "name": n} for k, n in _ACCT_MODES],
            "matrix": grid}


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


@router.get("/risk/summary")
async def risk_summary(_who=Depends(require_viewer)):
    """V2 双行状态条+平台风险工作台数据源(批次6e/V5 §14):
    行2风险摘要=受限账户/受限权益/风险调整可用权益/最老pending提现/24h提现成功率/未复核条款/最高Incident;
    venue 表=模式/incident_state/恢复阶梯/权益/折价/tier/提现健康/命中作用域。
    数据超龄→stale=true,前端必须按 UNKNOWN/STALE 灰 fail-closed 展示,禁止装绿。"""
    import time
    pol = await ds.get_json("dcm:risk:policy")
    age = int(time.time() - float((pol or {}).get("ts") or 0)) if pol else None
    stale = (pol is None) or age > 90
    venues = (pol or {}).get("venues") or {}
    nav = (pol or {}).get("nav") or {}
    reg = (pol or {}).get("policy_registry") or {}
    # 提现健康逐所 + 最老 pending
    wd, oldest = {}, {"venue": None, "age_sec": 0}
    for v in venues:
        h = await ds.get_json(f"dcm:risk:withdrawal:{v}")
        if h:
            wd[v] = h
            if float(h.get("oldest_pending_age_sec") or 0) > oldest["age_sec"]:
                oldest = {"venue": v, "age_sec": int(h["oldest_pending_age_sec"])}
    # 活跃 Incident + 24h 提现成功率 + 最近模式转变(dcm_main,mix_ro 只读)
    incidents, wd24, transitions = [], {"total": 0, "ok": 0, "rate": None}, []
    pool = await ds.pg()
    if pool is not None:
        try:
            incidents = [dict(r) for r in await pool.fetch(
                "SELECT venue, rule, state, severity, title, detail, hit_count, "
                "extract(epoch from now()-first_seen)::int AS age_sec "
                "FROM venue_incident WHERE state != 'CLOSED' ORDER BY severity DESC, first_seen DESC LIMIT 30")]
        except Exception:
            pass
        try:
            row = await pool.fetchrow(
                "SELECT count(*) AS total, count(*) FILTER (WHERE status='CONFIRMED') AS ok "
                "FROM withdrawal_observation WHERE recorded_at > now() - interval '24 hours' "
                "AND status != 'CANCELLED'")
            if row and row["total"]:
                wd24 = {"total": int(row["total"]), "ok": int(row["ok"]),
                        "rate": round(int(row["ok"]) / int(row["total"]) * 100, 1)}
        except Exception:
            pass
        try:
            transitions = [dict(r) for r in await pool.fetch(
                "SELECT scope_key AS venue, before_mode, after_mode, reason, recorded_at::text "
                "FROM venue_mode_transition ORDER BY id DESC LIMIT 20")]
        except Exception:
            pass
    _sev = {"QUARANTINED": 6, "FROZEN": 6, "EXIT_ONLY": 5, "REDUCE_ONLY": 4,
            "NO_NEW_RISK": 3, "WATCH": 2, "RECOVERY_WATCH": 1, "NORMAL": 0}
    worst = max(venues.values(), key=lambda d: _sev.get(d.get("mode"), 0), default=None)
    restricted = {v: d for v, d in venues.items()
                  if _sev.get(d.get("mode"), 0) >= _sev["NO_NEW_RISK"]}
    rows = [{"venue": v, **{k: d.get(k) for k in (
        "mode", "incident_state", "recovery", "reason", "modes_hit", "equity",
        "exposure_notional", "cap_usdt", "tier", "haircut_pct", "trapped_usdt")},
        "withdrawal": wd.get(v)} for v, d in venues.items()]
    rows.sort(key=lambda r: (-_sev.get(r["mode"], 0), -(r.get("equity") or 0)))
    return {
        "stale": stale, "age_sec": age,
        "policy_epoch": (pol or {}).get("policy_epoch"), "policy_version": (pol or {}).get("policy_version"),
        "global_mode": (pol or {}).get("global_mode", "NORMAL"),
        "worst_mode": (worst or {}).get("mode", "NORMAL") if not stale else "STALE",
        "restricted_accounts": len(restricted),
        "restricted_equity_usdt": round(sum(float(d.get("equity") or 0) for d in restricted.values()), 2),
        "nav": nav,
        "oldest_pending": oldest,
        "wd_24h": wd24,
        "unreviewed_terms": reg.get("unreviewed") or [],
        "prohibited": reg.get("prohibited") or [],
        "top_incident": incidents[0] if incidents else None,
        "incidents": incidents,
        "venues": rows,
        "transitions": transitions,
        "credential_epochs": (pol or {}).get("credential_epochs") or {},
    }


@router.get("/risk/venue/{venue}")
async def risk_venue_detail(venue: str, _who=Depends(require_viewer)):
    """平台详情页(V2 设计 KdKdE 五标签)数据源:概览/账户限制时间线/提现与网络/敞口仓位/条款与证据。"""
    pol = await ds.get_json("dcm:risk:policy")
    vd = ((pol or {}).get("venues") or {}).get(venue) or {}
    wd = await ds.get_json(f"dcm:risk:withdrawal:{venue}")
    out = {"venue": venue, "policy": vd, "withdrawal": wd,
           "restrictions": [], "transitions": [], "observations": [],
           "venue_policy": None, "artifacts": [], "defense_packs": [], "incidents": []}
    pool = await ds.pg()
    if pool is None:
        out["note"] = "dcm_main 不可达"
        return out

    async def _rows(key, sql, *args):
        try:
            out[key] = [dict(r) for r in await pool.fetch(sql, *args)]
        except Exception:
            pass
    await _rows("restrictions",
                "SELECT signal_type, severity, raw_code, raw_payload, hit_count, first_seen::text, "
                "last_seen::text FROM restriction_event WHERE venue=$1 ORDER BY last_seen DESC LIMIT 50", venue)
    await _rows("transitions",
                "SELECT before_mode, after_mode, reason, policy_epoch, policy_version, recorded_at::text "
                "FROM venue_mode_transition WHERE scope_key=$1 ORDER BY id DESC LIMIT 50", venue)
    await _rows("observations",
                "SELECT asset, network, amount::text, status, venue_tx_id, chain_tx, initiated_at::text, "
                "confirmed_at::text, duration_sec::text FROM withdrawal_observation WHERE venue=$1 "
                "ORDER BY id DESC LIMIT 50", venue)
    await _rows("incidents",
                "SELECT rule, state, severity, title, detail, hit_count, first_seen::text, last_seen::text "
                "FROM venue_incident WHERE venue=$1 ORDER BY id DESC LIMIT 30", venue)
    await _rows("artifacts",
                "SELECT kind, title, url_or_ref, note, recorded_at::text FROM venue_policy_artifact "
                "WHERE venue=$1 ORDER BY id DESC LIMIT 20", venue)
    await _rows("defense_packs",
                "SELECT id, trigger_rule, note, generated_at::text FROM account_defense_pack "
                "WHERE venue=$1 ORDER BY id DESC LIMIT 10", venue)
    try:
        row = await pool.fetchrow("SELECT * FROM venue_policy WHERE venue=$1", venue)
        if row:
            out["venue_policy"] = {k: (str(v) if v is not None else None) for k, v in dict(row).items()}
    except Exception:
        pass
    return out


@router.get("/risk/opportunities")
async def risk_opportunities(_who=Depends(require_viewer)):
    """通过硬闸的机会(tlOCA 底条+候选行 venue 风险字段,lQKF8):
    dcm:exec:opener 候选(已带 risk_charge_bps/risk_adjusted_e_bps)× 两腿 venue mode。
    NO_NEW_RISK 以上的腿=候选行显示限制原因,前端不给开仓入口。"""
    op = await ds.get_json("dcm:exec:opener") or {}
    pol = await ds.get_json("dcm:risk:policy") or {}
    venues = pol.get("venues") or {}
    out = []
    for c in (op.get("candidates") or [])[:12]:
        vl, vs = c.get("venue_long"), c.get("venue_short")
        ml = (venues.get(vl) or {}).get("mode", "N/A")
        ms = (venues.get(vs) or {}).get("mode", "N/A")
        blocked = any(m in ("NO_NEW_RISK", "REDUCE_ONLY", "EXIT_ONLY", "FROZEN") for m in (ml, ms))
        out.append({**{k: c.get(k) for k in ("symbol", "venue_long", "venue_short", "e_bps",
                    "net_daily_pct", "risk_charge_bps", "risk_adjusted_e_bps", "target_notional_usdt")},
                    "venue_long_mode": ml, "venue_short_mode": ms, "blocked": blocked,
                    "blocked_reason": ("腿venue受限" if blocked else "")})
    return {"ts": op.get("ts"), "mode": op.get("mode", "shadow"), "candidates": out,
            "skipped_count": len(op.get("skipped") or [])}


def _combo_net_pnl(realized, upnl):
    """逐组合净PnL = 已实现(income_records 各 itype 累加)+ 未实现(upnl)。两者全缺=None(不冒充0)。"""
    if not realized and upnl is None:
        return None
    r = sum(float(v) for v in (realized or {}).values())
    u = float(upnl) if upnl is not None else 0.0
    return round(r + u, 2)


@router.get("/risk/portfolio")
async def risk_portfolio(_who=Depends(require_viewer)):
    """经济组合表(tlOCA 十二列)+四采集件:
    保证金缓冲=逐腿 dist_liq_pct 最小值 · RECON=期望腿 vs 账户快照实盘差 ·
    下一现金流=funding 结算边界(interval_h 对齐 UTC)+净差×名义估额 ·
    退出成本=两腿半点差+taker费估算。净PnL 仍 N/A(逐组合账本=下批,upnl 进抽屉不冒充净PnL)。"""
    import json as _j
    import time as _t
    mgr = await ds.get_json("dcm:exec:manager") or {}
    pol = await ds.get_json("dcm:risk:policy") or {}
    rep = await ds.get_json("dcm:exec:repair") or {}
    acct: dict = {}
    # 逐 symbol 已实现账本(income_records:PNL/FEE/FUNDING/…),供逐组合净PnL=已实现+未实现
    realized: dict = {}
    _rpool = await ds.pg()
    if _rpool is not None:
        try:
            for _r in await _rpool.fetch(
                    "SELECT symbol, itype, sum(amount)::float8 AS amt FROM income_records "
                    "WHERE itype <> 'TRANSFER' GROUP BY symbol, itype"):
                realized.setdefault(_r["symbol"], {})[_r["itype"]] = _r["amt"]
        except Exception:
            pass

    async def _acct(venue):
        if venue not in acct:
            acct[venue] = await ds.get_json(f"dcm:account:{venue}") or {}
        return acct[venue]

    async def _l1(venue, sym):
        try:
            raw = await ds.rds().hget(f"dcm:feed:{venue}:perp", sym)
            l1 = _j.loads(raw) if raw else None
            if l1:
                b, a = float(l1.get("bid") or 0), float(l1.get("ask") or 0)
                if b > 0 and a > 0:
                    return (b + a) / 2, b, a
        except Exception:
            pass
        return None, None, None

    async def _fund(venue, sym):
        try:
            raw = await ds.rds().hget(f"dcm:feed:funding:{venue}", sym)
            return _j.loads(raw) if raw else None
        except Exception:
            return None

    TAKER_BPS = 5.0
    rows = []
    for ps in (mgr.get("pairs") or []):
        sym = ps.get("symbol") or ps.get("pair")
        legs, delta_usdt, route = [], 0.0, []
        buffers, recon_diffs, exit_cost, notional = [], [], 0.0, 0.0
        for lg in (ps.get("legs") or []):
            v, amt = lg.get("venue"), float(lg.get("amt") or 0)
            mid, bid, ask = await _l1(v, sym)
            snap = await _acct(v)
            pd = (snap.get("pos_detail") or {}).get(sym) or {}
            live_amt = float((snap.get("positions") or {}).get(sym) or 0)
            if snap.get("ok") and abs(live_amt - amt) > max(1e-9, abs(amt) * 0.05):
                recon_diffs.append(f"{v} 期望{amt}实盘{live_amt}")
            if pd.get("dist_liq_pct") is not None:
                buffers.append(float(pd["dist_liq_pct"]))
            leg_notional = abs(amt) * mid if mid else 0.0
            notional += leg_notional
            if mid and bid and ask and leg_notional:
                exit_cost += leg_notional * ((ask - bid) / 2 / mid + TAKER_BPS / 10000)
            legs.append({"venue": v, "amt": amt, "mark": mid,
                         "upnl": pd.get("upnl"), "dist_liq_pct": pd.get("dist_liq_pct"),
                         "adl": pd.get("adl"),
                         "mode": ((pol.get("venues") or {}).get(v) or {}).get("mode", "N/A")})
            route.append(f"{v}永续")
            if mid:
                delta_usdt += amt * mid
        # funding 结算日历:净差(空腿−多腿 daily_pct)+ 最近结算边界(interval_h 对齐 UTC)
        fl = await _fund(legs[0]["venue"], sym) if legs else None
        fs = await _fund(legs[-1]["venue"], sym) if len(legs) > 1 else None
        cashflow = None
        if fl and fs:
            net_daily = float(fs.get("daily_pct") or 0) - float(fl.get("daily_pct") or 0)
            ih = min(float(fl.get("interval_h") or 8), float(fs.get("interval_h") or 8))
            now = _t.time()
            next_ts = (int(now // (ih * 3600)) + 1) * int(ih * 3600)
            est = notional * (net_daily / 100.0) / (24.0 / ih) / 2 if notional else None
            cashflow = {"net_daily_pct": round(net_daily, 4), "next_at": next_ts,
                        "in_min": int((next_ts - now) / 60),
                        "est_usdt": round(est, 3) if est is not None else None}
        rows.append({
            "owner": "exec-mgr", "product": "C2.H", "symbol": sym,
            "route": " + ".join(route) or "N/A",
            "saga": ps.get("saga"), "saga_state": ps.get("action") or "N/A",
            "target": ps.get("target"), "mode": ps.get("mode"), "signal": ps.get("signal"),
            "next_cashflow": cashflow,
            "realized": realized.get(sym),
            "net_pnl": _combo_net_pnl(realized.get(sym),
                       sum(float(x["upnl"]) for x in legs if x.get("upnl") is not None)
                       if any(x.get("upnl") is not None for x in legs) else None),
            "upnl_sum": (round(sum(float(x["upnl"]) for x in legs if x.get("upnl") is not None), 2)
                         if any(x.get("upnl") is not None for x in legs) else None),
            "net_delta_usdt": round(delta_usdt, 2) if legs else None,
            "margin_buffer": (round(min(buffers), 1) if buffers else None),
            "exit_cost": (round(-exit_cost, 2) if exit_cost else None),
            "recon": ("⚠ " + "; ".join(recon_diffs)[:60]) if recon_diffs
                     else ("单腿!" if "SINGLE_LEG" in str(ps.get("action")) else "ok"),
            "notional_usdt": round(notional, 2),
            "legs": legs,
        })
    for ss in (mgr.get("symbols") or []):
        sym = ss.get("symbol")
        snap = await _acct("binance")
        pd = (snap.get("pos_detail") or {}).get(sym) or {}
        f = await _fund("binance", sym)
        cashflow = None
        if f:
            dp = float(f.get("daily_pct") or 0)
            ih = float(f.get("interval_h") or 8)
            now = _t.time()
            next_ts = (int(now // (ih * 3600)) + 1) * int(ih * 3600)
            # C1 期现=现货多+永续空:fr>0 时空腿**收**资金费 → 组合净差=+daily_pct
            mk = float(pd.get("mark") or 0)
            perp_notional = abs(float(ss.get("perp_amt") or 0)) * mk
            est = perp_notional * (dp / 100.0) / (24.0 / ih) if perp_notional else None
            cashflow = {"net_daily_pct": round(dp, 4), "next_at": next_ts,
                        "in_min": int((next_ts - now) / 60),
                        "est_usdt": round(est, 3) if est is not None else None}
        rows.append({
            "owner": "exec-mgr", "product": "C1", "symbol": sym,
            "route": "BN现货 + BN永续", "saga": None, "saga_state": ss.get("action") or "N/A",
            "target": ss.get("target"), "mode": ss.get("mode"), "signal": ss.get("signal"),
            "next_cashflow": cashflow,
            "realized": realized.get(sym),
            "net_pnl": _combo_net_pnl(realized.get(sym), pd.get("upnl")),
            "upnl_sum": pd.get("upnl"),
            # manager 的 delta 是 base 数量——换成 USDT 口径(mark 缺=N/A,绝不冒充)
            "net_delta_usdt": (round(float(ss.get("delta") or 0) * float(pd.get("mark") or 0), 2)
                               if pd.get("mark") else None),
            "margin_buffer": (round(float(pd["dist_liq_pct"]), 1) if pd.get("dist_liq_pct") is not None else None),
            "exit_cost": None, "recon": "ok", "notional_usdt": None,
            "legs": [{"venue": "binance", "amt": ss.get("perp_amt"), "spot": ss.get("spot"),
                      "upnl": pd.get("upnl"), "dist_liq_pct": pd.get("dist_liq_pct")}],
        })
    return {"ts": mgr.get("ts"), "rows": rows,
            "repair": {"trigger_venues": rep.get("trigger_venues") or [],
                       "intents": rep.get("intents") or []}}


@router.get("/risk/cashflows")
async def risk_cashflows(_who=Depends(require_viewer)):
    """屏3·资金流水:withdrawal_observation 近20笔(全所,链上tx/状态/耗时)。"""
    pool = await ds.pg()
    if pool is None:
        return {"rows": []}
    try:
        rows = await pool.fetch(
            "SELECT venue, asset, network, amount::text, status, venue_tx_id, chain_tx, "
            "initiated_at::text, confirmed_at::text, duration_sec::text "
            "FROM withdrawal_observation ORDER BY id DESC LIMIT 20")
        return {"rows": [dict(r) for r in rows]}
    except Exception:
        return {"rows": []}


@router.get("/risk/symbol-analysis")
async def risk_symbol_analysis(symbol: str, _who=Depends(require_viewer)):
    """屏1·标的分析:逐所 L1中价/点差/资金费(按结算周期日化)/新鲜度 + venue mode。OI=N/A(未采集)。"""
    import json as _j
    import time as _t
    pol = await ds.get_json("dcm:risk:policy") or {}
    out = []
    for v in ("binance", "okx", "bybit", "gate", "bitget", "hyperliquid"):
        row = {"venue": v, "mode": ((pol.get("venues") or {}).get(v) or {}).get("mode", "N/A"),
               "mid": None, "spread_bps": None, "funding_daily_pct": None,
               "interval_h": None, "fresh": False, "oi": None}
        try:
            raw = await ds.rds().hget(f"dcm:feed:{v}:perp", symbol)
            l1 = _j.loads(raw) if raw else None
            if l1:
                b, a = float(l1.get("bid") or 0), float(l1.get("ask") or 0)
                if b > 0 and a > 0:
                    row["mid"] = round((b + a) / 2, 8)
                    row["spread_bps"] = round((a - b) / ((a + b) / 2) * 10000, 2)
                    row["fresh"] = (_t.time() * 1000 - float(l1.get("recv_ts") or 0)) < 120000
        except Exception:
            pass
        try:
            raw = await ds.rds().hget(f"dcm:feed:funding:{v}", symbol)
            f = _j.loads(raw) if raw else None
            if f:
                row["funding_daily_pct"] = round(float(f.get("daily_pct") or 0), 4)
                row["interval_h"] = f.get("interval_h")
        except Exception:
            pass
        out.append(row)
    return {"symbol": symbol, "venues": out}


@router.get("/risk/lab")
async def risk_lab(_who=Depends(require_viewer)):
    """屏1·LAB 卡:engine-lending shadow 决策账快照(HOUSE_RND,不进 CORE_POOL)。"""
    snap = await ds.get_json("dcm:engine:lending:positions") or {}
    return {"mode": snap.get("mode", "shadow"), "would_hold": snap.get("would_hold") or [],
            "slots": snap.get("slots"), "ts": snap.get("ts")}


@router.get("/c3/overview")
async def c3_overview(_who=Depends(require_viewer)):
    """C3 工作台(qI0s6/QuReD/ERX5c)聚合:coin 生命周期仓位+七项风险灯+推送/可借监控。
    数据源=coin-bridge 面板(dcm:coin:panel)+意图账(dcm:engine:coin:positions),零新增交易所调用。"""
    panel = await ds.get_json("dcm:coin:panel") or {}
    snap = await ds.get_json("dcm:engine:coin:positions") or {}
    # symbol_margin 藏在 balances[uid] 里(coin 面板真实结构)——跨子账户合并,利率顶层兜底
    sm: dict = {}
    for _uid, bal in (panel.get("balances") or {}).items():
        if not isinstance(bal, dict):
            continue
        for _s, _v in (bal.get("symbol_margin") or {}).items():
            if not isinstance(_v, dict):
                continue
            if _s in sm:   # 跨子账户合并:借币量累加,其余字段first-wins
                try:
                    sm[_s]["borrowed"] = float(sm[_s].get("borrowed") or 0) + float(_v.get("borrowed") or 0)
                except Exception:
                    pass
            else:
                sm[_s] = dict(_v)
    ir = panel.get("interest_rates") or {}
    for _s, _v in sm.items():
        if _v.get("daily_interest_rate") in (None, "") and _s in ir:
            _v["daily_interest_rate"] = ir.get(_s) if not isinstance(ir.get(_s), dict) else (ir[_s].get("daily") or ir[_s].get("rate"))
    positions = snap.get("positions") or []
    # 七项风险灯(ERX5c):有数据源的真判,没有的如实 N/A
    hi_interest = [{"sym": s, "rate": v.get("daily_interest_rate")} for s, v in sm.items()
                   if v.get("daily_interest_rate") not in (None, "") and float(v["daily_interest_rate"] or 0) >= 1.0]
    no_inv = [{"sym": s, "cooldown_sec": v.get("noinv_remaining_sec")} for s, v in sm.items()
              if v.get("no_inventory")]
    repayhold = [{"sym": s, "reason": v.get("borrow_cap_reason")} for s, v in sm.items() if v.get("repayhold")]
    debt_syms = {s: float(v.get("borrowed") or 0) for s, v in sm.items() if float(v.get("borrowed") or 0) > 0}
    pos_syms = {str(p.get("symbol") or "").replace("USDT", ""): p for p in positions
                if p.get("status") not in ("CLOSED", "FAILED")}
    naked_debt = [{"sym": s, "borrowed": b} for s, b in debt_syms.items()
                  if s not in pos_syms and s not in ("USDT", "BNB")]
    lights = [
        {"k": "借息尖峰", "n": len(hi_interest), "detail": hi_interest[:5], "note": "日息≥1%/d"},
        {"k": "可借归零(-3045)", "n": len(no_inv), "detail": no_inv[:5], "note": "冷却中"},
        {"k": "债务>回购", "n": None, "detail": [], "note": "N/A(回购深度源待接)"},
        {"k": "卖未对冲", "n": None, "detail": [], "note": "N/A(单腿判定在 risk-ledger R7/R11)"},
        {"k": "裸债P0", "n": len(naked_debt), "detail": naked_debt[:5], "note": "有借无仓(意图账口径)"},
        {"k": "还币失败/闸", "n": len(repayhold), "detail": repayhold[:5], "note": "repayhold"},
        {"k": "主子划转异常", "n": None, "detail": [], "note": "N/A(transfer事实源待接)"},
    ]
    rows = [{"symbol": p.get("symbol"), "status": p.get("status"),
             "sub": p.get("account_note") or p.get("sub_account") or "",
             "borrowed": p.get("borrowed_qty") or p.get("borrow_qty"),
             "spot_sell": p.get("spot_sell_qty"), "spot_buy": p.get("spot_buy_qty"),
             "futures_long": p.get("futures_long_qty"),
             "opened_at": str(p.get("created_at") or p.get("opened_at") or "")[:16]}
            for p in positions]
    return {"ts": snap.get("ts") or panel.get("ts"), "rows": rows, "lights": lights,
            "pushed": panel.get("pushed") or (panel.get("pushed_symbols") or []),
            "borrowable_top": sorted(
                [{"sym": s, "max_borrowable": v.get("max_borrowable"),
                  "rate": v.get("daily_interest_rate")} for s, v in sm.items()
                 if v.get("max_borrowable") not in (None, "", 0, "0")],
                key=lambda x: float(x["max_borrowable"] or 0), reverse=True)[:12]}


@router.get("/c3/brief")
async def c3_brief(symbol: str, _who=Depends(require_viewer)):
    """C3 人工推送·系统补数九宫格(qI0s6):逐项真数据,缺=N/A。经济闸/风险闸在此预判展示,
    权威判定仍在 coin 引擎(推送后 coin 规则/黑名单/借币闸原样生效)。"""
    sym = symbol.upper().replace("USDT", "")
    panel = await ds.get_json("dcm:coin:panel") or {}
    pol = await ds.get_json("dcm:risk:policy") or {}
    sm = {}
    for _uid, bal in (panel.get("balances") or {}).items():
        if not isinstance(bal, dict):
            continue
        hit = (bal.get("symbol_margin") or {}).get(sym)
        if isinstance(hit, dict):
            sm = dict(hit)
            break
    if sm.get("daily_interest_rate") in (None, "") and sym in (panel.get("interest_rates") or {}):
        sm["daily_interest_rate"] = (panel.get("interest_rates") or {}).get(sym)
    spreads = panel.get("spreads") or {}
    sp = spreads.get(sym + "USDT") or spreads.get(sym) or {}
    if not isinstance(sp, dict):
        sp = {"value": sp}
    bl = {str(b.get("symbol", "")).upper() for b in (panel.get("blacklist") or [])}
    rules = panel.get("rules") or {}
    vb = ((pol.get("venues") or {}).get("binance") or {})
    grid = {
        "spread": sp if sp else None,
        "daily_interest_rate": sm.get("daily_interest_rate"),
        "max_borrowable": sm.get("max_borrowable"),
        "borrow_limit": sm.get("borrow_limit"),
        "no_inventory": bool(sm.get("no_inventory")),
        "noinv_remaining_sec": sm.get("noinv_remaining_sec"),
        "repayhold": bool(sm.get("repayhold")),
        "blacklist_hit": (sym + "USDT") in bl or sym in bl,
        "order_amount": rules.get("order_amount"),
        "policy_mode": vb.get("mode", "N/A"),
        "policy_can_open": bool((vb.get("capabilities") or {}).get("CAN_OPEN")),
    }
    gates = [
        {"k": "人工推送", "ok": True, "note": "案件登记,不进命令队列不触发借币"},
        {"k": "系统补数", "ok": bool(sm or sp), "note": "面板九宫格" if (sm or sp) else "面板无此币数据"},
        {"k": "经济闸", "ok": bool(sp), "note": f"点差快照 {sp}" if sp else "无点差数据=不判"},
        {"k": "风险闸", "ok": grid["policy_can_open"] and not grid["blacklist_hit"] and not grid["no_inventory"],
         "note": f"policy={grid['policy_mode']} 黑名单={'命中' if grid['blacklist_hit'] else '无'} 可借={'归零' if grid['no_inventory'] else 'ok'}"},
        {"k": "DRY_RUN", "ok": None, "note": "N/A(提案链下批)"},
        {"k": "操作员确认", "ok": None, "note": "确认后走既有 push_symbol(coin 状态机权威)"},
        {"k": "PositionIntent", "ok": None, "note": "coin 引擎生成"},
    ]
    return {"symbol": sym + "USDT", "grid": grid, "gates": gates}
