"""V6 统一投影层(V6 Rev.2 §4 主控台三分屏 / §5 统一策略工作台)。

铁律:
- 三分屏是同一 control_snapshot 的三个投影,不是三套后端;禁止各页面自行计算风险状态。
- strategy_work_item_projection 只把各域事实拼成操作员可理解的一行,
  **不成为订单或账本权威**(可随时重建,权威在 dcm_main/coin/manager/risk-ledger)。
- 数据缺失一律 None/N/A,绝不用哨兵值冒充。
- generation 单调递增(Redis INCR),三屏必须显示相同 generation;快照>90s=过期,前端 fail-closed。
"""
import json
import time
import asyncio
import logging
import hashlib
import datetime as dt

from . import datasources as ds

log = logging.getLogger("mix.v6core")

SNAPSHOT_KEY = "mix:v6:control_snapshot"
GEN_KEY = "mix:v6:generation"
FRAMES_CHANNEL = "mix:ws:frames"   # Rust hub 纯中继

# 通用生命周期(§5.3)
STAGES = ("DISCOVERED", "REVIEW", "RESERVED", "EXECUTING",
          "HOLDING", "EXITING", "RECONCILING", "CLOSED")

# coin C3.S 状态 → 通用阶段(策略专用阶段作模板扩展,不压成巨型枚举:保留 stage_detail)
_COIN_STAGE = {
    "PENDING_BORROW": ("RESERVED", "借币预占"),
    "BORROWED_IDLE": ("EXECUTING", "已借待卖"),
    "PENDING_OPEN": ("EXECUTING", "maker挂单"),
    "PARTIAL": ("EXECUTING", "部分成交"),
    "OPEN": ("HOLDING", "已对冲持有"),
    "PENDING_CLOSE": ("EXITING", "买回中"),
    "PENDING_REPAY": ("EXITING", "待还币"),
    "REPAYING": ("EXITING", "还币中"),
    "QUARANTINED": ("RECONCILING", "隔离待人工"),
}

_SEV = {"QUARANTINED": 6, "FROZEN": 6, "EXIT_ONLY": 5, "REDUCE_ONLY": 4,
        "NO_NEW_RISK": 3, "WATCH": 2, "RECOVERY_WATCH": 1, "NORMAL": 0}


def _wid(*parts) -> str:
    """稳定 work_item_id(可重建投影,同源同 id)。"""
    return "wi-" + hashlib.sha1(":".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _canon(symbol: str) -> str:
    for suf in ("USDT", "USDC", "USD"):
        if symbol and symbol.endswith(suf):
            return symbol[: -len(suf)]
    return symbol or "?"


def _next_settle_utc(interval_h: int = 8) -> str:
    """下一 funding 结算 UTC 边界(00/08/16)。"""
    now = dt.datetime.now(dt.timezone.utc)
    nxt = (now.replace(minute=0, second=0, microsecond=0)
           + dt.timedelta(hours=interval_h - now.hour % interval_h))
    return nxt.strftime("%H:%M UTC")


def _venue_mode(pol_venues: dict, venue: str) -> str:
    return (pol_venues.get(venue) or {}).get("mode", "N/A")


def _risk_of_legs(pol_venues: dict, venues: list[str]) -> dict:
    """工作项风险状态=各腿 venue 有效模式的最严格档。"""
    worst, why = "NORMAL", ""
    for v in venues:
        m = _venue_mode(pol_venues, v)
        if _SEV.get(m, 0) > _SEV.get(worst, 0):
            worst, why = m, f"{v} {m}"
    return {"level": worst, "reason": why}


async def _confirmed_income() -> dict[str, float]:
    """逐币已确认收益(income_records FUNDING/PNL/FEE 累加,net 口径与 pnl-recorder 一致)。"""
    rows = await ds.fetch(
        "SELECT upper(symbol) AS s, round(sum(income)::numeric,2) AS v FROM income_records "
        "WHERE income_type IN ('FUNDING','PNL','FEE','COMMISSION','REALIZED_PNL') "
        "GROUP BY upper(symbol)")
    return {r["s"]: float(r["v"]) for r in rows if r.get("s")}


async def build_work_items() -> list[dict]:
    """strategy_work_item_projection(§5.2)——五源拼装,任一源失败降级跳过。"""
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    pol = await ds.get_json("dcm:risk:policy") or {}
    pvenues = pol.get("venues") or {}
    income = {}
    try:
        income = await _confirmed_income()
    except Exception as e:  # noqa: BLE001
        log.warning("confirmed income: %s", e)
    items: list[dict] = []

    def _mk(**kw) -> dict:
        base = {
            "work_item_id": None, "environment": "PROD_CEX", "portfolio_id": "CORE_POOL",
            "owner_key": None, "strategy_code": None, "workflow_template": None,
            "workflow_stage": None, "stage_detail": None,
            "automation_mode": None, "symbol": None, "route": None,
            "physical_accounts": [], "capital_reserved": None,
            "expected_net_return": None, "confirmed_pnl": None,
            "risk_status": None, "next_action": None, "next_deadline": None,
            "position_intent_id": None, "saga_id": None, "ledger_status": None,
            "source": None, "as_of": now_iso,
        }
        base.update(kw)
        if base["work_item_id"] is None:
            base["work_item_id"] = _wid(base["source"], base["symbol"], base["strategy_code"])
        return base

    # ── 源1: opener 候选(shadow 决策服务)→ DISCOVERED ──────────────────
    try:
        op = await ds.get_json("dcm:exec:opener") or {}
        for c in (op.get("candidates") or [])[:20]:
            vl, vs = c.get("venue_long"), c.get("venue_short")
            risk = _risk_of_legs(pvenues, [v for v in (vl, vs) if v])
            blocked = _SEV.get(risk["level"], 0) >= _SEV["NO_NEW_RISK"]
            items.append(_mk(
                source="opener", symbol=c.get("symbol"), strategy_code="C2.H",
                workflow_template="C2_PERP_PERP", workflow_stage="DISCOVERED",
                stage_detail="候选(过E闸)", automation_mode="AUTO",
                route=f"{vl}↔{vs}", physical_accounts=[vl, vs],
                capital_reserved=c.get("target_notional_usdt"),
                expected_net_return=c.get("risk_adjusted_e_bps") or c.get("e_bps"),
                risk_status=risk,
                next_action=("受限:换腿或忽略" if blocked else "送入工作台"),
                next_deadline=None))
    except Exception as e:  # noqa: BLE001
        log.warning("wi opener: %s", e)

    # ── 源2: dry_run_proposal(mix_main)→ REVIEW/RESERVED ────────────────
    try:
        pool = await ds.pg_main()
        if pool is not None:
            rows = await pool.fetch(
                "SELECT id, symbol, product, venue_long, venue_short, target_notional::float8 AS tn, "
                "state, created_at FROM dry_run_proposal "
                "WHERE state IN ('COOLDOWN','PENDING_APPROVAL','APPROVED') "
                "AND created_at > now() - interval '24 hours' "   # 与 proposals_list 过期口径一致,旧测试单不进投影
                "ORDER BY id DESC LIMIT 30")
            # 同币同态多条提案=归并为最新一条+×N 标注(每条事实仍在审批页,投影只降噪不隐藏)
            grouped: dict[tuple, list] = {}
            for r in rows:
                grouped.setdefault((r["symbol"], r["state"]), []).append(r)
            for (sym, state), grp in grouped.items():
                r = grp[0]
                st = {"COOLDOWN": ("REVIEW", "冷却期"),
                      "PENDING_APPROVAL": ("REVIEW", "待审批"),
                      "APPROVED": ("RESERVED", "已批准(shadow终态)")}[state]
                if len(grp) > 1:
                    st = (st[0], f"{st[1]} ×{len(grp)}")
                items.append(_mk(
                    source="proposal", work_item_id=_wid("proposal", r["id"]),
                    symbol=r["symbol"], strategy_code=r["product"] or "—",
                    route=(f"{r['venue_long']}↔{r['venue_short']}" if r["venue_long"] else None),
                    capital_reserved=r["tn"],
                    workflow_template="DRY_RUN", workflow_stage=st[0], stage_detail=st[1],
                    automation_mode="ASSISTED",
                    risk_status={"level": "NORMAL", "reason": ""},
                    next_action=("等待冷却" if r["state"] == "COOLDOWN" else
                                 "TOTP审批" if r["state"] == "PENDING_APPROVAL" else "shadow终态·不下单"),
                    position_intent_id=f"dryrun:{r['id']}"))
    except Exception as e:  # noqa: BLE001
        log.warning("wi proposal: %s", e)

    # ── 源3: exec-manager 在管(C1 symbols + C2 pairs)→ HOLDING/EXITING ──
    try:
        mgr = await ds.get_json("dcm:exec:manager") or {}
        for ss in (mgr.get("symbols") or []):
            sym = ss.get("symbol")
            has = abs(float(ss.get("perp_amt") or 0)) > 1e-9 or abs(float(ss.get("spot") or 0)) > 1e-9
            if not sym or not has:
                continue
            closing = str(ss.get("target") or "hold") == "close"
            armed = str(ss.get("mode") or "shadow") == "armed"
            items.append(_mk(
                source="manager", symbol=sym, strategy_code="C1",
                workflow_template="SPOT_LONG_DERIVATIVE_SHORT",
                workflow_stage=("EXITING" if closing else "HOLDING"),
                stage_detail=("平仓中" if closing else "持有中"),
                automation_mode=("AUTO" if armed else "ASSISTED"),
                route="binance", physical_accounts=["binance"],
                capital_reserved=ss.get("notional_usdt"),
                confirmed_pnl=income.get(str(sym).upper()),
                risk_status=_risk_of_legs(pvenues, ["binance"]),
                next_action=("盯平仓收敛" if closing else "持有·下一结算"),
                next_deadline=_next_settle_utc(),
                saga_id=ss.get("saga_id")))
        for ps in (mgr.get("pairs") or []):
            sym = ps.get("symbol") or ps.get("pair")
            legs = ps.get("legs") or []
            if not sym or not any(abs(float(lg.get("amt") or 0)) > 1e-9 for lg in legs):
                continue
            closing = str(ps.get("target") or "hold") == "close"
            armed = str(ps.get("mode") or "shadow") == "armed"
            single = "SINGLE_LEG" in str(ps.get("action") or "")
            venues = [lg.get("venue") for lg in legs if lg.get("venue")]
            items.append(_mk(
                source="manager", symbol=sym, strategy_code="C2.H",
                workflow_template="DERIVATIVE_LONG_DERIVATIVE_SHORT",
                workflow_stage=("RECONCILING" if single else "EXITING" if closing else "HOLDING"),
                stage_detail=("单腿裸露!" if single else "平仓中" if closing else "持有·收费差"),
                automation_mode=("AUTO" if armed else "ASSISTED"),
                route="↔".join(venues), physical_accounts=venues,
                capital_reserved=ps.get("notional_usdt"),
                confirmed_pnl=income.get(_canon(str(sym)).upper() + "USDT") or income.get(str(sym).upper()),
                risk_status=({"level": "QUARANTINED", "reason": "单腿裸露"} if single
                             else _risk_of_legs(pvenues, venues)),
                next_action=("立即补对冲/修复" if single else "盯平仓" if closing else "持有·下一结算"),
                next_deadline=("立即" if single else _next_settle_utc()),
                saga_id=ps.get("saga_id")))
    except Exception as e:  # noqa: BLE001
        log.warning("wi manager: %s", e)

    # ── 源4: coin C3.S 坑位(意图账快照)→ 模板扩展阶段 ────────────────────
    try:
        snap = await ds.get_json("dcm:engine:coin:positions") or {}
        for p in (snap.get("positions") or []):
            st = str(p.get("status") or "")
            if st in ("CLOSED", "FAILED", "SETTLED"):
                continue
            stage, detail = _COIN_STAGE.get(st, ("HOLDING", st))
            sym = p.get("symbol")
            items.append(_mk(
                source="coin", work_item_id=_wid("coin", p.get("id"), sym),
                symbol=sym, strategy_code="C3.S",
                workflow_template="BORROW_SPOT_SHORT_DERIVATIVE_LONG",
                workflow_stage=stage, stage_detail=detail,
                automation_mode="AUTO",
                route="binance(margin)", physical_accounts=[f"sub:{p.get('sub_account_id')}"],
                capital_reserved=p.get("open_usdt_amount"),
                confirmed_pnl=income.get(str(sym).upper()) if sym else None,
                risk_status=_risk_of_legs(pvenues, ["binance"]),
                next_action={"RESERVED": "等成交", "EXECUTING": "盯挂单",
                             "HOLDING": "持有·收点差", "EXITING": "买回/还币",
                             "RECONCILING": "人工处理"}.get(stage, "查看"),
                next_deadline=(_next_settle_utc() if stage == "HOLDING" else None),
                ledger_status="coin意图账"))
    except Exception as e:  # noqa: BLE001
        log.warning("wi coin: %s", e)

    # ── 源6(V6.2 PATCH-01 §3.2): C2.P 人工研判案件 → RESEARCH ────────────
    # 未生成计划的活跃研判(72h 内,非 REJECT)=一个工作项;生成计划后由源2(proposal)接棒。
    try:
        pool = await ds.pg_main()
        if pool is not None:
            rrows = await pool.fetch(
                "SELECT id, canonical_symbol, product_code, market_stage, decision, status, "
                "review_at, summary_text, created_by FROM c2p_research_decision "
                "WHERE proposal_id IS NULL AND decision != 'REJECT' "
                "AND created_at > now() - interval '72 hours' "
                "ORDER BY id DESC LIMIT 20")
            seen_syms: set = set()
            for r in rrows:
                sym = r["canonical_symbol"] + ("" if r["canonical_symbol"].endswith("USDT") else "USDT")
                if sym in seen_syms:   # 同币多案件只投影最新一条(事实都在研判页)
                    continue
                seen_syms.add(sym)
                done = r["status"] == "COMPLETED"
                items.append(_mk(
                    source="research", work_item_id=_wid("research", r["id"]),
                    symbol=sym, strategy_code=r["product_code"] or "C2.P",
                    workflow_template="C2P_MANUAL", workflow_stage="RESEARCH",
                    stage_detail=(f"研判完成:{r['market_stage']}" if done else "研判草稿"),
                    automation_mode="MANUAL",
                    risk_status={"level": "NORMAL", "reason": ""},
                    next_action=("生成人工计划" if (done and r["decision"] == "PREPARE_PLAN")
                                 else "完成研判" if not done else "持续观察"),
                    position_intent_id=f"research:{r['id']}",
                    research_case_id=r["id"], research_decision=r["decision"]))
    except Exception as e:  # noqa: BLE001
        log.warning("wi research: %s", e)

    # ── 源5: RiskRepair 意图 → RECONCILING ───────────────────────────────
    try:
        rep = await ds.get_json("dcm:exec:repair") or {}
        for it in (rep.get("intents") or []):
            items.append(_mk(
                source="repair", work_item_id=_wid("repair", it.get("id"), it.get("symbol")),
                symbol=it.get("symbol"), strategy_code=it.get("product") or "—",
                workflow_template="RISK_REPAIR", workflow_stage="RECONCILING",
                stage_detail=f"修复意图 {it.get('kind') or ''}".strip(),
                automation_mode="ASSISTED",
                risk_status={"level": "REDUCE_ONLY", "reason": it.get("reason") or "受限venue撤离"},
                next_action="审阅修复方案", next_deadline="TTL 30m",
                position_intent_id=f"repair:{it.get('id')}"))
    except Exception as e:  # noqa: BLE001
        log.warning("wi repair: %s", e)

    await _enrich_v61(items, pol)
    try:
        await _attach_account_legs(items)
    except Exception as e:  # noqa: BLE001
        log.warning("wi account_legs: %s", e)   # 腿投影失败=行降级无腿,绝不拖垮快照
    return items


# ══ V6.2 PATCH-02-REV4 批A:GroupRow 经济字段 + AccountLegRow 投影(§6A) ══════════
# 铁律:聚合只在服务端算(版本化);父行保证金=最差腿;缺数=None 前端显'—',绝不冒充 0。
_LEG_AGG_VERSION = "legagg-v1"
_POS_STAGES = {"RESERVED", "EXECUTING", "HOLDING", "EXITING", "RECONCILING"}


def _norm_sym(s: str) -> str:
    return str(s or "").upper().replace("-", "").replace("_", "").replace("SWAP", "")


def _match_pos(pd: dict, sym: str) -> dict | None:
    """按归一化符号在 pos_detail 里找该币(各所符号格式不同:XVGUSDT/VANRY_USDT/BTC-USDT-SWAP/HL币名)。"""
    ns = _norm_sym(sym)
    base = ns[:-4] if ns.endswith("USDT") else ns
    for k, v in (pd or {}).items():
        nk = _norm_sym(k)
        if nk == ns or nk == base:
            return v
    return None


async def _fund_daily(venue: str, sym: str):
    """dcm:feed:funding:{venue} 是 Redis hash(field=币,value=json{daily_pct,interval_h,...})。"""
    try:
        r = ds.rds()
        if r is None:
            return None, None
        v = await r.hget(f"dcm:feed:funding:{venue}", sym)
        if not v:   # gate 等下划线符号变体
            v = await r.hget(f"dcm:feed:funding:{venue}",
                             sym.replace("USDT", "_USDT") if "USDT" in sym else sym)
        if not v:
            return None, None
        e = json.loads(v)
        d = e.get("daily_pct")
        return (round(float(d), 4) if d is not None else None), e.get("interval_h")
    except Exception:  # noqa: BLE001
        return None, None


def _mk_leg(venue: str, role: str, side: str, qty, acct=None, pos=None, fund=None,
            extra: dict | None = None) -> dict:
    mark = (pos or {}).get("mark")
    leg = {"leg_id": f"{venue}:{role}", "venue": venue, "account": acct or venue,
           "role": role, "side": side, "qty": qty,
           "mark": mark,
           "notional_usdt": (round(abs(float(qty)) * float(mark), 2)
                             if qty is not None and mark else None),
           "upnl": (pos or {}).get("upnl"),
           "dist_liq_pct": (pos or {}).get("dist_liq_pct"),
           "adl": (pos or {}).get("adl"),
           "funding_daily_pct": fund,
           "data_state": ("PRESENT" if pos or qty is not None else "NOT_CONNECTED")}
    if extra:
        leg.update(extra)
    return leg


async def _attach_account_legs(items: list[dict]) -> None:
    """给持仓类工作项挂 account_legs[](账户腿直拉事实)+group_econ(风险退出评估器同源经济面)。
    源:dcm:exec:manager legs + dcm:account:{venue}.pos_detail + dcm:feed:funding:{venue}
      + dcm:risk:exit(closeout/预算/费差/最差强平——与点差保护同一权威,不二次发明口径)
      + dcm:coin:panel(C3 借币腿)。任一源缺=该字段 None,行不失败。"""
    pos_items = [it for it in items if it.get("workflow_stage") in _POS_STAGES]
    if not pos_items:
        return
    venues: set = set()
    for it in pos_items:
        for a in (it.get("physical_accounts") or []):
            if a and not str(a).startswith("sub:"):
                venues.add(str(a))
    accounts = {v: (await ds.get_json(f"dcm:account:{v}") or {}) for v in venues}
    rexit = ((await ds.get_json("dcm:risk:exit")) or {}).get("items") or {}
    mgr = await ds.get_json("dcm:exec:manager") or {}
    mgr_syms = {str(s.get("symbol")): s for s in (mgr.get("symbols") or [])}
    mgr_pairs = {str(p.get("symbol") or p.get("pair")): p for p in (mgr.get("pairs") or [])}
    panel = None   # C3 惰性取(24KB,无 C3 持仓不拉)

    spreads_rt = None   # C3 实时点差(惰性)
    for it in pos_items:
        sym = str(it.get("symbol") or "")
        legs: list[dict] = []
        extra_econ: dict = {}
        src = it.get("source")
        try:
            if src == "manager" and sym in mgr_syms:      # C1 现货多+永续空(binance)
                ss = mgr_syms[sym]
                pd = (accounts.get("binance") or {}).get("pos_detail") or {}
                pos = _match_pos(pd, sym)
                fd, fiv = await _fund_daily("binance", sym)
                legs.append(_mk_leg("binance", "PERP_SHORT", "SHORT", ss.get("perp_amt"),
                                    pos=pos, fund=fd, extra={"funding_interval_h": fiv}))
                spot_qty = ss.get("spot")
                legs.append(_mk_leg("binance", "SPOT_LONG", "LONG", spot_qty,
                                    pos={"mark": (pos or {}).get("mark")} if pos else None,
                                    extra={"note": "现货腿(含理财LD份额)"}))
            elif src == "manager" and sym in mgr_pairs:   # C2 双永续跨所
                for lg in (mgr_pairs[sym].get("legs") or []):
                    v = str(lg.get("venue") or "")
                    amt = lg.get("amt")
                    pd = (accounts.get(v) or {}).get("pos_detail") or {}
                    pos = _match_pos(pd, sym)
                    side = "LONG" if (amt or 0) > 0 else "SHORT"
                    fd, fiv = await _fund_daily(v, sym)
                    legs.append(_mk_leg(v, f"PERP_{side}", side, amt, pos=pos, fund=fd,
                                        extra={"funding_interval_h": fiv}))
            elif src == "coin":                            # C3 借币空+主账户永续多
                if panel is None:
                    panel = await ds.get_json("dcm:coin:panel") or {}
                base = sym[:-4] if sym.upper().endswith("USDT") else sym
                sm = None
                for bal in (panel.get("balances") or {}).values():
                    cand = _match_pos((bal or {}).get("symbol_margin") or {}, base)
                    if cand and (cand.get("borrowed") or cand.get("free")):
                        sm = cand
                        break
                legs.append(_mk_leg("binance-margin", "BORROW_SPOT_SHORT", "SHORT",
                                    (sm or {}).get("borrowed"),
                                    acct=(it.get("physical_accounts") or ["sub:?"])[0],
                                    extra={"debt": (sm or {}).get("borrowed"),
                                           "interest_daily_pct": (sm or {}).get("daily_interest_rate"),
                                           "free": (sm or {}).get("free"),
                                           "data_state": "PRESENT" if sm else "NOT_CONNECTED"}))
                # C3 组合经济面(批B §6A.8):借币/利率/实时点差——桥 panel+spreads_rt 真相源
                if sm:
                    extra_econ["borrowed_qty"] = sm.get("borrowed")
                    extra_econ["interest_daily_pct"] = sm.get("daily_interest_rate")
                if spreads_rt is None:
                    spreads_rt = await ds.get_json("dcm:coin:spreads_rt") or {}
                sp = _match_pos(spreads_rt, sym)
                if isinstance(sp, (list, tuple)) and len(sp) >= 2:
                    extra_econ["spread_open_pct"], extra_econ["spread_close_pct"] = sp[0], sp[1]
                elif isinstance(sp, dict):
                    extra_econ["spread_open_pct"] = sp.get("open") or sp.get("open_spread")
                    extra_econ["spread_close_pct"] = sp.get("close") or sp.get("close_spread")
                mfp = (panel.get("master_futures_positions") or {})
                hedge_amt = mfp.get(sym) or mfp.get(base)
                legs.append(_mk_leg("binance", "PERP_LONG_HEDGE", "LONG", hedge_amt,
                                    acct="master",
                                    extra={"liq_pct": panel.get("master_futures_liq_pct"),
                                           "note": "hedge_via_master",
                                           "data_state": "PRESENT" if hedge_amt is not None else "NOT_CONNECTED"}))
        except Exception as e:  # noqa: BLE001
            log.warning("legs %s: %s", sym, e)
        # group_econ:与点差保护评估器同源(dcm:risk:exit)——同一权威绝不二次发明口径
        e = rexit.get(sym) or rexit.get(_norm_sym(sym)) or {}
        marg = e.get("margin") or {}
        gross = round(sum(l["notional_usdt"] for l in legs if l.get("notional_usdt")), 2) or None
        # 批B §6A.7:双腿名义差+逐侧费率(服务端算,前端不得用可见行重算——§6A.13)
        ln = sum(l["notional_usdt"] for l in legs if l.get("side") == "LONG" and l.get("notional_usdt"))
        sn = sum(l["notional_usdt"] for l in legs if l.get("side") == "SHORT" and l.get("notional_usdt"))
        if ln and sn:
            extra_econ["notional_gap_usdt"] = round(abs(ln - sn), 2)
        fl = next((l["funding_daily_pct"] for l in legs
                   if l.get("side") == "LONG" and l.get("funding_daily_pct") is not None), None)
        fs = next((l["funding_daily_pct"] for l in legs
                   if l.get("side") == "SHORT" and l.get("funding_daily_pct") is not None), None)
        if fl is not None:
            extra_econ["funding_long_daily_pct"] = fl
        if fs is not None:
            extra_econ["funding_short_daily_pct"] = fs
        it["account_legs"] = legs
        it["group_econ"] = {
            **extra_econ,
            "agg_version": _LEG_AGG_VERSION,
            "closeout_pnl_net": e.get("closeout_pnl_net"),      # 真实退出盈亏(保守口径)
            "gap_now_pct": e.get("gap_now"),                    # 当前费差/点差(%/d 或 %)
            "carry_per_window": e.get("carry_per_window"),
            "hard_budget": e.get("hard_budget"),
            "budget_remaining": e.get("budget_remaining"),
            "margin_min_dist_liq_pct": marg.get("min_dist_liq_pct"),   # 最差腿口径
            "margin_worst_venue": marg.get("worst_venue"),
            "protection_state": e.get("state"),
            "gross_notional": gross,
            "net_delta": (mgr_syms.get(sym) or {}).get("delta"),
            "leg_count": len(legs),
        }


async def _maintenance_active() -> bool:
    try:
        pool = await ds.pg_main()
        if pool is not None:
            row = await pool.fetchrow(
                "SELECT 1 FROM maintenance_request WHERE state NOT IN ('CLOSED') LIMIT 1")
            return bool(row)
    except Exception:  # noqa: BLE001
        pass
    return False


async def _elig_gate() -> tuple[set, dict]:
    """第七维:策略×账户模式资格矩阵(strategy_account_eligibility 权威)。
    返回 (forbidden={(策略根,mode)}, venue_modes={venue:{该所已登记账户的模式集}})。"""
    forbidden, venue_modes = set(), {}
    try:
        pool = await ds.pg_main()
        if pool is not None:
            for r in await pool.fetch(
                    "SELECT strategy, account_mode FROM strategy_account_eligibility WHERE eligibility='FORBIDDEN'"):
                forbidden.add((r["strategy"], r["account_mode"]))
            for r in await pool.fetch(
                    "SELECT r.account_key, r.account_mode, c.venue FROM accounts_registry r "
                    "LEFT JOIN api_credentials c ON c.account_key=r.account_key AND c.state<>'revoked' "
                    "WHERE r.enabled IS DISTINCT FROM false"):
                v = r["venue"]
                if v:
                    venue_modes.setdefault(v, set()).add(r["account_mode"] or "classic")
    except Exception as e:  # noqa: BLE001
        log.warning("elig gate: %s", e)
    return forbidden, venue_modes


def _elig_blocked(strategy_code: str, venues: list, forbidden: set, venue_modes: dict) -> str:
    """某 venue 上全部已登记账户模式都被该策略禁止 → 拦。无登记模式=不拦(信息不足不误杀)。"""
    root = str(strategy_code or "").split(".")[0]
    if not root or not forbidden:
        return ""
    for v in venues or []:
        modes = venue_modes.get(v)
        if modes and all((root, m) in forbidden or (strategy_code, m) in forbidden for m in modes):
            return f"资格矩阵禁止:{strategy_code}×{v}全部账户模式"
    return ""


async def _lease_map() -> dict:
    """scope → (holder, epoch, automation_mode)。租约过期视为无控制人。"""
    out = {}
    try:
        pool = await ds.pg_main()
        if pool is not None:
            for r in await pool.fetch(
                    "SELECT scope, active_writer, writer_epoch, automation_mode FROM strategy_writer_lease "
                    "WHERE valid_until > now()"):
                out[r["scope"]] = (r["active_writer"], int(r["writer_epoch"]), r["automation_mode"])
    except Exception:  # noqa: BLE001
        pass
    return out


async def _enrich_v61(items: list[dict], pol: dict) -> None:
    """V6.1 §3/§4 契约补齐:能力注册表→effective_actions(服务端算,前端不猜按钮)、
    control_epoch(join 租约)、runtime_stage、origin_mode、data_state 八态、row_version。"""
    from . import v6lang
    caps = await v6lang.capabilities()
    maint = await _maintenance_active()
    leases = await _lease_map()
    # PATCH-02 §8:点差保护评估(shadow)→ 逐币保护态;>=NO_ADD 硬线阻断新增(前置④)
    rexit: dict = {}
    try:
        rexit = ((await ds.get_json("dcm:risk:exit")) or {}).get("items") or {}
    except Exception:  # noqa: BLE001
        pass
    # V6.2 PATCH-01 §4.5:逐币最新研判 → research_status/thesis_status/next_review_at
    research: dict[str, dict] = {}
    try:
        pool = await ds.pg_main()
        if pool is not None:
            for r in await pool.fetch(
                    "SELECT DISTINCT ON (canonical_symbol) canonical_symbol, id, status, decision, "
                    "review_at FROM c2p_research_decision ORDER BY canonical_symbol, id DESC"):
                research[r["canonical_symbol"]] = dict(r)
    except Exception:  # noqa: BLE001
        pass
    elig_forbidden, venue_modes = await _elig_gate()   # 第七维:策略×账户模式资格矩阵
    pol_age = time.time() - float(pol.get("ts") or 0) if pol else 9e9
    can_open = bool(pol) and pol_age <= 90 and pol.get("global_mode", "NORMAL") == "NORMAL" and not maint
    risk_cap = "STALE" if (not pol or pol_age > 90) else pol.get("global_mode", "NORMAL")
    for it in items:
        sc, sym, src = it.get("strategy_code") or "", it.get("symbol") or "", it.get("source")
        it["economic_case_id"] = "ec-" + hashlib.sha1(f"{sc}:{sym}".encode()).hexdigest()[:10]
        it["origin_mode"] = "OPERATOR" if src == "proposal" else "SYSTEM"
        it["control_mode"] = it.get("automation_mode")
        it["approval_policy"] = "APPROVAL_EACH"
        lease = leases.get(f"CORE_POOL:{sc}:{sym}")
        it["control_holder"] = lease[0] if lease else ("system" if it.get("automation_mode") == "AUTO" else None)
        it["control_epoch"] = lease[1] if lease else None
        it["runtime_stage"] = ("ARMED" if src == "coin" else
                               "ARMED" if (src == "manager" and it.get("automation_mode") == "AUTO") else
                               "SHADOW")
        # 研判维度(§4.5):同一 WorkItem 单一事实,今日工作/AiCoin/表格都读这里不各自复制
        rc = research.get(_canon(sym)) or research.get(sym)
        if rc:
            expired = bool(rc["review_at"] and rc["review_at"].timestamp() < time.time())
            it.setdefault("research_case_id", rc["id"])
            it["research_status"] = ("EXPIRED" if expired else
                                     "COMPLETED" if rc["status"] == "COMPLETED" else "PENDING")
            it["thesis_status"] = ("INVALID" if rc["decision"] == "REJECT" else
                                   "UNKNOWN" if expired else
                                   "VALID" if rc["status"] == "COMPLETED" else "UNKNOWN")
            it["next_review_at"] = str(rc["review_at"]) if rc["review_at"] else None
        else:
            it["research_status"] = ("PENDING" if it.get("workflow_stage") == "RESEARCH"
                                     else "NOT_REQUIRED")
            it["thesis_status"] = "UNKNOWN" if it.get("workflow_stage") == "RESEARCH" else None
            it["next_review_at"] = None
        # 八态缺值:区分『真0/没接入/待产生』(§6.2)
        it["data_state"] = {
            "capital_reserved": v6lang.dv(it.get("capital_reserved"),
                                          source=src or "")["state"],
            "expected_net_return": v6lang.dv(
                it.get("expected_net_return"),
                state=(None if it.get("expected_net_return") is not None else
                       "NOT_YET_AVAILABLE" if it["workflow_stage"] in ("HOLDING", "EXITING") else
                       "NOT_CONNECTED"))["state"],
            "confirmed_pnl": v6lang.dv(
                it.get("confirmed_pnl"),
                state=(None if it.get("confirmed_pnl") is not None else
                       "NOT_CONNECTED" if src == "coin" else   # C3账本在coin库,归因待接
                       "NOT_YET_AVAILABLE"))["state"],
        }
        acts, block = v6lang.effective_actions(it, caps, can_open, risk_cap, maint)
        # 第七维叠加:资格矩阵禁止 → 开仓类动作降为禁用展示(减险不受影响)
        eb = _elig_blocked(sc, it.get("physical_accounts") or [], elig_forbidden, venue_modes)
        if eb:
            for a in acts:
                if a["code"] in ("opportunity_to_workbench", "proposal_dry_run"):
                    a["wired"] = False
                    a["reason"] = eb
            block = block or eb
        # 第八维(PATCH-02 §8,前置④):点差保护 >=NO_ADD → 该币新增风险动作硬阻断(减险不受影响)
        rx = rexit.get(sym) or {}
        it["risk_protection_state"] = rx.get("state") or "NORMAL"
        it["closeout_pnl_net"] = rx.get("closeout_pnl_net")
        it["hard_loss_budget_remaining"] = rx.get("budget_remaining")
        it["recovery_windows"] = rx.get("recovery_windows")
        it["margin_survival_summary"] = rx.get("margin") or {}
        it["risk_exit_policy_version"] = rx.get("policy")
        it["next_risk_review_at"] = rx.get("as_of")
        if rx and rx.get("state") in ("NO_ADD", "REDUCE_REQUIRED", "EXIT_REQUIRED"):
            why = f"点差保护[{rx['state']}]:{';'.join(rx.get('reasons') or [])[:120]}(shadow评估·退出决策仍人工)"
            for a in acts:
                if a["code"] in v6lang.RISK_ADDING_ACTS:
                    a["wired"] = False
                    a["reason"] = why
            block = block or why
        it["allowed_actions"] = acts
        it["blocking_reason"] = block
        it["product_capability"] = v6lang.cap_of(caps, sc)
        it.update(v6lang.narrate(it, acts))   # v2.2 五字段:确定性状态机叙述,非LLM
        it["row_version"] = hashlib.sha1(json.dumps(
            [it.get(k) for k in ("workflow_stage", "stage_detail", "capital_reserved",
                                 "confirmed_pnl", "control_epoch")], default=str).encode()).hexdigest()[:8]


async def build_control_snapshot(generation: int | None = None) -> dict:
    """control_snapshot(§4)——三屏共享单一事实。"""
    now = dt.datetime.now(dt.timezone.utc)
    work_items = await build_work_items()
    pol = await ds.get_json("dcm:risk:policy") or {}
    pol_age = int(time.time() - float(pol.get("ts") or 0)) if pol else None
    stale = (not pol) or (pol_age or 9e9) > 90

    # 维护状态(公开端点同源逻辑,直接读表)
    site_state, site_note = "NORMAL", ""
    try:
        pool = await ds.pg_main()
        if pool is not None:
            row = await pool.fetchrow(
                "SELECT state, reason FROM maintenance_request WHERE state != 'CLOSED' "
                "ORDER BY id DESC LIMIT 1")
            if row:
                site_state, site_note = row["state"], row["reason"]
    except Exception:  # noqa: BLE001
        pass

    # 有效能力(风险权威覆盖运行方式;快照过期=fail-closed 禁新增)
    gmode = pol.get("global_mode", "NORMAL")
    can_open = (not stale) and gmode == "NORMAL" and site_state in ("NORMAL", "CLOSED")
    capabilities = {
        "risk_capability": ("STALE" if stale else gmode),
        "can_open": can_open,
        "can_reduce": True,   # 减险永远放行(撤单/补对冲/减仓/买回/还币)
        "reason": ("风险快照过期,fail-closed 禁新增" if stale else
                   f"维护 {site_state}" if site_state not in ("NORMAL", "CLOSED") else
                   "" if gmode == "NORMAL" else f"全局 {gmode}"),
    }

    # 机会(过闸)=DISCOVERED 工作项
    opportunities = [w for w in work_items if w["workflow_stage"] == "DISCOVERED"]
    positions = [w for w in work_items if w["workflow_stage"] in
                 ("RESERVED", "EXECUTING", "HOLDING", "EXITING", "RECONCILING")]

    # Incident 待办
    incidents = []
    try:
        incidents = await ds.fetch(
            "SELECT venue, rule, state, severity, title, detail, hit_count, "
            "extract(epoch from now()-first_seen)::int AS age_sec "
            "FROM venue_incident WHERE state != 'CLOSED' ORDER BY severity DESC, first_seen DESC LIMIT 20")
    except Exception:  # noqa: BLE001
        pass

    # 账本健康
    ledger_health = {"status": "N/A", "last_income_age_sec": None, "recon_breaks": None}
    try:
        rows = await ds.fetch("SELECT extract(epoch from now()-max(recorded_at))::int AS age FROM income_records")
        if rows and rows[0].get("age") is not None:
            age = int(rows[0]["age"])
            ledger_health = {"status": ("正常" if age < 7200 else "延迟"),
                             "last_income_age_sec": age, "recon_breaks": None}
    except Exception:  # noqa: BLE001
        pass

    top = incidents[0] if incidents else None
    # PATCH-02 §4.2 补齐:valid_until(=as_of+90s fail-closed 窗)/下一关键时间/点差保护摘要
    rexit_summary = {"mode": None, "counts": {}}
    try:
        rx = (await ds.get_json("dcm:risk:exit")) or {}
        cnt: dict = {}
        for v in (rx.get("items") or {}).values():
            cnt[v["state"]] = cnt.get(v["state"], 0) + 1
        rexit_summary = {"mode": rx.get("mode"), "policy": rx.get("policy"), "counts": cnt}
    except Exception:  # noqa: BLE001
        pass
    snap = {
        "snapshot_id": f"cs-{int(now.timestamp()*1000)}",
        "generation": generation,
        "as_of": now.isoformat(),
        "valid_until": (now + dt.timedelta(seconds=90)).isoformat(),
        "next_critical_time": _next_settle_utc(),
        "risk_exit_summary": rexit_summary,
        "environment": "PROD_CEX",
        "site_maintenance_state": site_state,
        "site_maintenance_note": site_note,
        "effective_capabilities": capabilities,
        "policy": {"epoch": pol.get("policy_epoch"), "version": pol.get("policy_version"),
                   "global_mode": gmode, "age_sec": pol_age, "stale": stale,
                   "nav": pol.get("nav") or {}},
        "top_alert": ({"severity": top.get("severity"), "title": top.get("title"),
                       "venue": top.get("venue")} if top else None),
        "opportunities": opportunities,
        "work_items": work_items,
        "positions": positions,
        "incidents": incidents,
        "ledger_health": ledger_health,
        "counts": {
            "candidates": len(opportunities),
            "candidates_raw": (lambda o: len(o.get("candidates") or []) + len(o.get("skipped") or []))(
                await ds.get_json("dcm:exec:opener") or {}),
            "executing": sum(1 for w in positions if w["workflow_stage"] in ("RESERVED", "EXECUTING")),
            "holding": sum(1 for w in positions if w["workflow_stage"] == "HOLDING"),
            "exiting": sum(1 for w in positions if w["workflow_stage"] == "EXITING"),
            "abnormal": sum(1 for w in positions if w["workflow_stage"] == "RECONCILING"),
        },
    }
    return snap


_VOLATILE = {"as_of", "snapshot_id", "generation", "seq", "age_sec",
             "last_income_age_sec", "next_deadline", "valid_until",
             "next_critical_time", "next_risk_review_at",
             # 批A:腿事实与经济面含行情级波动(mark/upnl/dist_liq逐tick变),
             # 不进 generation 签名——状态级变化(阶段/风险/保护态)已由其他字段承载
             "account_legs", "group_econ"}


def _strip_volatile(x):
    if isinstance(x, dict):
        return {k: _strip_volatile(v) for k, v in x.items() if k not in _VOLATILE}
    if isinstance(x, list):
        return [_strip_volatile(v) for v in x]
    return x


def _sig(snap: dict) -> str:
    """变更签名:剔除时间流逝类易变字段——generation 只反映真实状态变化,
    否则每 3s 递增一次,WS 全是噪音帧且『同 generation』失去审计意义。"""
    return hashlib.sha1(json.dumps(_strip_volatile(snap), sort_keys=True, default=str,
                                   ensure_ascii=False).encode()).hexdigest()


async def control_snapshot_loop():
    """常驻 worker(3s):重建快照,变更→generation++,存 Redis+发 WS 帧(hub 中继)。
    验收线:三屏增量同步 ≤3s(§12)。"""
    await asyncio.sleep(8)
    last_sig, last_gen, seq = None, 0, 0
    while True:
        try:
            r = ds.rds()
            snap = await build_control_snapshot()
            sig = _sig(snap)
            changed = sig != last_sig
            if r is not None:
                if changed:
                    last_gen = int(await r.incr(GEN_KEY))
                    last_sig = sig
                snap["generation"] = last_gen
                seq += 1
                snap["seq"] = seq
                await r.set(SNAPSHOT_KEY, json.dumps(snap, ensure_ascii=False, default=str), ex=120)
                if changed or seq % 20 == 0:   # 变更帧 + ~60s 心跳帧(客户端看门狗判过期)
                    await r.publish(FRAMES_CHANNEL, json.dumps(
                        {"channel": "control:snapshot", "generation": last_gen, "seq": seq,
                         "changed": changed, "as_of": snap["as_of"], "counts": snap["counts"],
                         "capabilities": snap["effective_capabilities"],
                         "top_alert": snap["top_alert"]},
                        ensure_ascii=False, default=str))
        except Exception as e:  # noqa: BLE001
            log.warning("control_snapshot_loop: %s", e)
        await asyncio.sleep(3.0)
