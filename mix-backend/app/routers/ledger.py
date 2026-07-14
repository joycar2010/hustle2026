"""LedgerProjector / NAVProjector(V2 §5.2/§9)——不可变账本到会计/风险投影。

架构铁律:**源账本即 append-only 真相,投影器只归一映射不物理复制**(防与源分叉):
  - income_records(dcm_main,唯一约束 venue+ext_id)=交易所账单权威(FEE/FUNDING/PNL/TRANSFER)
  - withdrawal_observation(dcm_main)=提现事实(外部资本流)
  - trade_history(mix_main)=仓位生命周期(归因上下文,不重复计 PnL)
每条源分录映射到 NAV-bridge 类目;无类目=UNMAPPED(V2 验收 §14:UNMAPPED=0)。
NAV bridge 恒等式(V2 §9.2):
  Δ(Accounting NAV) − ExternalFlows = TradingPnL + Funding + Earn − Borrow − Fee + FX + Settlement + IncidentPnL
残差=ΔNAV − 外部流 − 类目和;连续 14 天仅精度残差=验收通过。
"""
import time

from fastapi import APIRouter, Depends, Query

from ..deps import require_viewer
from .. import datasources as ds

router = APIRouter()

# income_records.itype → NAV-bridge 类目(V2 §9.1 覆盖面)。未知 itype=UNMAPPED。
_ITYPE_CATEGORY = {
    "FEE": "FEE", "COMMISSION": "FEE", "REALIZED_PNL": "TRADING_PNL", "PNL": "TRADING_PNL",
    "FUNDING": "FUNDING", "FUNDING_FEE": "FUNDING", "INTEREST": "BORROW", "BORROW_INTEREST": "BORROW",
    "EARN": "EARN", "SAVINGS": "EARN", "REBATE": "FEE", "TRANSFER": "EXTERNAL_FLOW",
    "DEPOSIT": "EXTERNAL_FLOW", "WITHDRAW": "EXTERNAL_FLOW", "COMMISSION_REBATE": "FEE",
    "INSURANCE_CLEAR": "SETTLEMENT", "DELIVERED_SETTELMENT": "SETTLEMENT",
}
# 类目在恒等式中的符号(external_flow 单列;其余进 component_sum)
_SIGN_COMPONENT = ("FEE", "FUNDING", "TRADING_PNL", "BORROW", "EARN", "SETTLEMENT", "INCIDENT_PNL")


def _cat(itype: str) -> str:
    return _ITYPE_CATEGORY.get((itype or "").upper(), "UNMAPPED")


@router.get("/ledger/entries")
async def ledger_entries(days: int = Query(30, ge=1, le=365),
                         category: str = Query(""), symbol: str = Query(""),
                         _who=Depends(require_viewer)):
    """统一归一账本视图(源=income_records,append-only 真相)。每条带 nav_category;
    category=UNMAPPED 过滤可直接查未归类分录(应为 0)。"""
    pool = await ds.pg()
    if pool is None:
        return {"rows": [], "note": "dcm_main 不可达"}
    conds, args = ["ts > now() - ($1||' days')::interval"], [str(days)]
    if symbol:
        args.append(symbol.upper())
        conds.append(f"symbol = ${len(args)}")
    rows = await pool.fetch(
        f"SELECT ts::text, venue, symbol, itype, amount::float8, strategy_code FROM income_records "
        f"WHERE {' AND '.join(conds)} ORDER BY ts DESC LIMIT 500", *args)
    out = []
    for r in rows:
        c = _cat(r["itype"])
        if category and c != category:
            continue
        out.append({**dict(r), "nav_category": c})
    return {"rows": out, "categories": sorted(set(_ITYPE_CATEGORY.values())) + ["UNMAPPED"]}


@router.get("/ledger/nav-bridge")
async def nav_bridge(days: int = Query(14, ge=1, le=90), _who=Depends(require_viewer)):
    """NAV bridge 恒等式检查(V2 §9.2 验收核心):
    Δ(Accounting NAV) − ExternalFlows =?= Σ类目(Fee/Funding/TradingPnL/Borrow/Earn/Settlement)。
    残差=左−右;UNMAPPED=未归类分录数。连续 14 天仅精度残差 + UNMAPPED=0 = 验收通过。"""
    pool = await ds.pg()
    if pool is None:
        return {"note": "dcm_main 不可达"}
    # 类目汇总(income_records)
    cat_rows = await pool.fetch(
        "SELECT itype, sum(amount)::float8 AS amt, count(*) AS n FROM income_records "
        "WHERE ts > now() - ($1||' days')::interval GROUP BY itype", str(days))
    categories, unmapped, unmapped_itypes = {}, 0, []
    external_flow, component_sum = 0.0, 0.0
    for r in cat_rows:
        c = _cat(r["itype"])
        categories[c] = round(categories.get(c, 0.0) + r["amt"], 4)
        if c == "UNMAPPED":
            unmapped += int(r["n"])
            unmapped_itypes.append(r["itype"])
        elif c == "EXTERNAL_FLOW":
            external_flow += r["amt"]
        else:
            component_sum += r["amt"]
    # 提现事实外部流(withdrawal_observation:CONFIRMED 计入外部流出;与 income TRANSFER 可能重叠,
    # 此处只报事实供交叉核对,不重复进恒等式主算——恒等式用 income TRANSFER 为准)
    wd_out = None
    try:
        wd = await pool.fetchrow(
            "SELECT coalesce(sum(amount),0)::float8 AS s, count(*) AS n FROM withdrawal_observation "
            "WHERE status='CONFIRMED' AND recorded_at > now() - ($1||' days')::interval", str(days))
        wd_out = {"confirmed_amount": round(wd["s"], 2), "count": int(wd["n"])}
    except Exception:  # noqa: BLE001
        pass
    # ΔNAV:pool_nav_snapshot 首末(mix_main;不足两点则 N/A,不臆造)
    mpool = await ds.pg_main()
    d_nav = nav_start = nav_end = None
    if mpool is not None:
        try:
            snaps = await mpool.fetch(
                "SELECT pool_nav::float8, as_of FROM pool_nav_snapshot "
                "WHERE as_of > now() - ($1||' days')::interval ORDER BY as_of", str(days))
            if len(snaps) >= 2:
                nav_start, nav_end = snaps[0]["pool_nav"], snaps[-1]["pool_nav"]
                d_nav = round(nav_end - nav_start, 4)
        except Exception:  # noqa: BLE001
            pass
    # 恒等式残差(仅两端 NAV 快照齐备时可算)
    residual = None
    if d_nav is not None:
        residual = round(d_nav - external_flow - component_sum, 4)
    return {
        "window_days": days,
        "categories": categories,
        "component_sum": round(component_sum, 4),
        "external_flow_income": round(external_flow, 4),
        "withdrawal_facts": wd_out,
        "delta_nav": d_nav, "nav_start": nav_start, "nav_end": nav_end,
        "residual": residual,
        "unmapped_count": unmapped, "unmapped_itypes": unmapped_itypes,
        "identity_ok": (unmapped == 0 and residual is not None and abs(residual) < 1.0),
        "note": ("恒等式:ΔNAV−外部流=类目和;残差应仅精度级(|.|<1U)且 UNMAPPED=0"
                 if d_nav is not None else
                 "ΔNAV=N/A(pool_nav_snapshot 不足两点)——先在 账本与资金 定期打快照建立基线"),
    }


@router.get("/ledger/recon-breaks")
async def recon_breaks(_who=Depends(require_viewer)):
    """RECON 断点面(V2 §9/§14):①UNMAPPED 分录(账本口径破);②账户实盘 vs 期望腿差
    (portfolio 口径,借自 risk portfolio 的 recon);③income 缺失 strategy_code 的分录(归因破)。"""
    pool = await ds.pg()
    breaks = []
    if pool is not None:
        try:
            um = await pool.fetch(
                "SELECT itype, count(*) AS n, sum(amount)::float8 AS amt FROM income_records "
                "WHERE ts > now() - interval '30 days' GROUP BY itype")
            for r in um:
                if _cat(r["itype"]) == "UNMAPPED":
                    breaks.append({"kind": "UNMAPPED_ITYPE", "detail": f"{r['itype']} × {r['n']}",
                                   "amount": round(r["amt"], 2)})
        except Exception:  # noqa: BLE001
            pass
        try:
            noattr = await pool.fetchval(
                "SELECT count(*) FROM income_records WHERE (strategy_code IS NULL OR strategy_code='') "
                "AND itype IN ('PNL','FUNDING') AND ts > now() - interval '7 days'")
            if noattr and int(noattr) > 0:
                breaks.append({"kind": "UNATTRIBUTED_INCOME",
                               "detail": f"近7天 {int(noattr)} 条 PNL/FUNDING 无 strategy_code(归因破)",
                               "amount": None})
        except Exception:  # noqa: BLE001
            pass
    # portfolio 口径 RECON(账户快照 vs 期望腿)
    pf_breaks = 0
    try:
        from .risk import risk_portfolio
        pf = await risk_portfolio(_who)
        pf_breaks = sum(1 for r in (pf.get("rows") or []) if r.get("recon") != "ok")
        for r in (pf.get("rows") or []):
            if r.get("recon") != "ok":
                breaks.append({"kind": "POSITION_RECON", "detail": f"{r['symbol']}: {r['recon']}",
                               "amount": None})
    except Exception:  # noqa: BLE001
        pass
    return {"breaks": breaks, "total": len(breaks), "position_recon_breaks": pf_breaks,
            "ts": int(time.time()),
            "note": "V2 §14 验收:UNMAPPED=0 且连续14天 NAV bridge 仅精度残差"}


@router.get("/audit/facts")
async def audit_facts(kind: str = Query("orders"), symbol: str = Query(""),
                      days: int = Query(30, ge=1, le=180), _who=Depends(require_viewer)):
    """交易与审计历史(SRRZX)多事实流。kind∈orders|bills|ledger|proposals|maintenance|recon。
    一行一事实,支持 symbol 筛选。原始事实不可编辑,只读。"""
    mpool = await ds.pg_main()
    dpool = await ds.pg()
    rows = []
    if kind == "bills" and dpool is not None:  # 交易所账单(income_records)
        conds, args = ["ts > now()-($1||' days')::interval"], [str(days)]
        if symbol:
            args.append(symbol.upper()); conds.append(f"symbol=${len(args)}")
        for r in await dpool.fetch(f"SELECT ts::text, venue, symbol, itype, amount::float8, strategy_code, "
                                   f"ext_id FROM income_records WHERE {' AND '.join(conds)} ORDER BY ts DESC LIMIT 200", *args):
            rows.append(dict(r))
    elif kind == "orders" and mpool is not None:  # 平仓/成交(trade_history)
        conds, args = ["created_at > now()-($1||' days')::interval"], [str(days)]
        if symbol:
            args.append(symbol.upper()); conds.append(f"symbol=${len(args)}")
        for r in await mpool.fetch(f"SELECT opened_at::text, closed_at::text, symbol, strategy_code, "
                                   f"master_venue, hedge_venue, qty::float8, notional::float8, pnl::float8, state, source "
                                   f"FROM trade_history WHERE {' AND '.join(conds)} ORDER BY created_at DESC LIMIT 200", *args):
            rows.append(dict(r))
    elif kind == "proposals" and mpool is not None:  # PositionIntent 代理=DRY_RUN 提案
        for r in await mpool.fetch("SELECT id, symbol, product, venue_long, venue_short, state, "
                                   "created_by, approved_by, created_at::text FROM dry_run_proposal "
                                   "ORDER BY id DESC LIMIT 100"):
            rows.append(dict(r))
    elif kind == "maintenance" and mpool is not None:
        for r in await mpool.fetch("SELECT id, mtype, state, reason, created_by, closed_by, "
                                   "created_at::text, updated_at::text FROM maintenance_request ORDER BY id DESC LIMIT 50"):
            rows.append(dict(r))
    elif kind == "ledger":
        r = await ledger_entries(days=days, symbol=symbol, _who=_who)
        rows = r["rows"]
    elif kind == "recon":
        r = await recon_breaks(_who=_who)
        rows = r["breaks"]
    return {"kind": kind, "rows": rows,
            "kinds": ["orders", "bills", "ledger", "proposals", "maintenance", "recon"],
            "note": "原始事实不可编辑,只读;时间线因果链 Intent→Order→Fill→Bill→Ledger→RECON→NAV"}
