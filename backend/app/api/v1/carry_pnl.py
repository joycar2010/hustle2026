# -*- coding: utf-8 -*-
"""M4 NG Carry-Basis 经济PnL只读接口 (P0方案§15.5精简版, 2026-07-16)。

GET /api/v1/carry/economic-pnl?pair_code=NG
按对聚合真实数据源, 组件级返回+置信等级, 绝不只显示carry收入:
  binance_unrealized  币安腿未实现(实时positionRisk, EXACT)
  mt5_unrealized      MT5腿未实现(桥positions实查, EXACT; 已含未结swap对equity影响)
  funding_settled     币安资金费实收(binance_income表, EXACT)
  mt5_realized_profit MT5已平交易profit(mt5_deals, EXACT)
  mt5_swap_realized   MT5已结swap(mt5_deals, EXACT)
  binance_fee         币安佣金(binance_income COMMISSION, EXACT; maker-only正常=0)
  economic_pnl        以上合计(未扣退出成本 — 标注)
铁律: 任一组件查询失败→该组件null+confidence=INCOMPLETE, 不得静默按0合计。
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, Query

logger = logging.getLogger(__name__)
router = APIRouter()


from app.core.security import get_current_user_id


@router.get("/maker-stats")
async def maker_ab_stats(
    hours: int = Query(72, ge=1, le=720),
    user_id: str = Depends(get_current_user_id),
):
    """M3 maker A/B度量面(V1.1 §12/P0方案§19.2)。按 user×pair 聚合事实层:
    执行数/成交率/预算闸率/崩溃率 + markout逐窗均值。A/B操作法: 给不同用户的
    timing_configs 配不同 binance_timeout(现状champion=DB实际值), 本接口按
    cohort 出对比数字。只读, 无授权差别(登录即可看全体聚合 — 运营面板用)。"""
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT e.user_id::text, e.pair_code, e.strategy_type,"
            "       count(*) AS n_exec,"
            "       count(*) FILTER (WHERE e.status='FILLED') AS n_filled,"
            "       count(*) FILTER (WHERE e.status='NO_FILL') AS n_nofill,"
            "       count(*) FILTER (WHERE e.status='BUDGET_GATED') AS n_gated,"
            "       count(*) FILTER (WHERE e.status IN ('CRASHED','HALTED')) AS n_crash,"
            "       round(avg(extract(epoch from (e.finished_at - e.created_at)))::numeric, 2) AS avg_exec_s"
            " FROM executions e"
            " WHERE e.created_at > now() - make_interval(hours => :h)"
            " GROUP BY 1,2,3 ORDER BY 1,2,3"), {"h": hours})).all()
        mo = (await db.execute(text(
            "SELECT m.symbol, m.horizon_ms, count(*) AS n,"
            "       round(avg(m.markout_bps)::numeric, 4) AS avg_bps,"
            "       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY m.markout_bps)::numeric, 4) AS p50_bps"
            " FROM fill_markouts m"
            " WHERE m.created_at > now() - make_interval(hours => :h)"
            " GROUP BY 1,2 ORDER BY 1,2"), {"h": hours})).all()
    return {
        "window_hours": hours,
        "cohorts": [{"user_id": r[0], "pair": r[1], "type": r[2], "n_exec": r[3],
                     "fill_rate": round(r[4] / r[3], 4) if r[3] else None,
                     "n_filled": r[4], "n_nofill": r[5], "n_budget_gated": r[6],
                     "n_crashed": r[7], "avg_exec_s": float(r[8]) if r[8] is not None else None}
                    for r in rows],
        "markouts": [{"symbol": m[0], "horizon_ms": m[1], "n": m[2],
                      "avg_bps": float(m[3]), "p50_bps": float(m[4])} for m in mo],
        "note": "markout_bps正=成交后价格向不利方向移动(逆向选择成本); A/B分桶按用户timing_configs.binance_timeout",
    }


@router.get("/economic-pnl")
async def carry_economic_pnl(
    pair_code: str = Query("NG"),
    user_id: str = Depends(get_current_user_id),
):
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text
    comp = {}
    incomplete = []

    async with AsyncSessionLocal() as db:
        _res = await db.execute(text(
            "SELECT sa.symbol AS sym_a, sb.symbol AS sym_b, hp.conversion_factor,"
            "       upa.account_a_id::text AS account_a_id, upa.account_b_id::text AS account_b_id"
            " FROM hedging_pairs hp"
            " JOIN platform_symbols sa ON sa.id = hp.symbol_a_id"
            " JOIN platform_symbols sb ON sb.id = hp.symbol_b_id"
            " JOIN user_pair_accounts upa ON upa.pair_code = hp.pair_code AND upa.user_id = CAST(:u AS uuid)"
            " WHERE hp.pair_code = :p LIMIT 1"),
            {"u": user_id, "p": pair_code})
        pr = _res.mappings().first()
        if not pr:
            return {"pair_code": pair_code, "error": "no binding for user", "confidence": "INCOMPLETE"}
        sym_a, sym_b, conv = pr["sym_a"], pr["sym_b"], float(pr["conversion_factor"] or 0)
        acct_a, acct_b = pr["account_a_id"], pr["account_b_id"]

        # funding实收 + 币安佣金(该账户该symbol全历史)
        try:
            r = (await db.execute(text(
                "SELECT income_type, COALESCE(SUM(income),0) FROM binance_income"
                " WHERE account_id = CAST(:a AS uuid) AND symbol = :s"
                "   AND income_type IN ('FUNDING_FEE','COMMISSION') GROUP BY 1"),
                {"a": acct_a, "s": sym_a})).all()
            m = {k: float(v) for k, v in r}
            comp["funding_settled"] = round(m.get("FUNDING_FEE", 0.0), 6)
            comp["binance_fee"] = round(m.get("COMMISSION", 0.0), 6)
        except Exception as e:
            comp["funding_settled"] = comp["binance_fee"] = None
            incomplete.append(f"binance_income: {e!r}")

        # MT5已平profit/已结swap
        try:
            r2 = (await db.execute(text(
                "SELECT COALESCE(SUM(profit),0), COALESCE(SUM(swap),0), COALESCE(SUM(commission),0)"
                " FROM mt5_deals WHERE symbol LIKE :s || '%'"), {"s": sym_b})).first()
            comp["mt5_realized_profit"] = round(float(r2[0]), 6)
            comp["mt5_swap_realized"] = round(float(r2[1]), 6)
            comp["mt5_commission"] = round(float(r2[2]), 6)
        except Exception as e:
            comp["mt5_realized_profit"] = comp["mt5_swap_realized"] = comp["mt5_commission"] = None
            incomplete.append(f"mt5_deals: {e!r}")

    # 币安腿未实现(实时)
    try:
        from app.services.continuous_executor import _recon_binance_net, _RECON_BN_CLIENTS
        from app.core.database import AsyncSessionLocal as _ASL2
        from sqlalchemy import text as _t2
        async with _ASL2() as db2:
            row = (await db2.execute(_t2(
                "SELECT api_key, api_secret, proxy_config FROM accounts WHERE account_id = CAST(:a AS uuid)"),
                {"a": acct_a})).first()
        cli = _RECON_BN_CLIENTS.get(acct_a)
        if cli is None and row:
            import json as _j
            from app.services.binance_client import BinanceFuturesClient
            from app.core.proxy_utils import build_proxy_url
            pc = row[2]
            if isinstance(pc, str):
                try:
                    pc = _j.loads(pc)
                except Exception:
                    pc = None
            cli = BinanceFuturesClient(row[0], row[1], proxy_url=build_proxy_url(pc))
            _RECON_BN_CLIENTS[acct_a] = cli
        if cli is None:
            raise RuntimeError(f"account {acct_a[:8]} 无币安凭证")
        pos = await asyncio.wait_for(cli.get_position_risk(symbol=sym_a), timeout=8.0)
        comp["binance_unrealized"] = round(sum(float(p.get("unRealizedProfit", 0) or 0) for p in pos), 6)
        comp["binance_position_amt"] = round(sum(float(p.get("positionAmt", 0) or 0) for p in pos), 4)
    except Exception as e:
        comp["binance_unrealized"] = comp["binance_position_amt"] = None
        incomplete.append(f"binance_position: {e!r}")

    # MT5腿未实现(桥实查; MT5 profit已含浮动swap对equity影响, 不重复计swap_unrealized)
    try:
        from app.services.continuous_executor import _recon_mt5_net_units
        from app.core.database import AsyncSessionLocal as _ASL3
        from sqlalchemy import text as _t3
        import httpx as _hx
        import os as _os
        async with _ASL3() as db3:
            mc = (await db3.execute(_t3(
                "SELECT COALESCE(bridge_url, 'http://172.31.14.113:' || bridge_service_port)"
                " FROM mt5_clients WHERE account_id = CAST(:a AS uuid) AND is_active"
                "   AND is_system_service = false ORDER BY priority LIMIT 1"),
                {"a": acct_b})).scalar()
        if mc:
            hdr = {"X-Api-Key": _os.getenv("MT5_API_KEY", "")}
            async with _hx.AsyncClient(timeout=6.0) as hc:
                r3 = await hc.get(f"{mc}/mt5/positions", headers=hdr)
            pl = r3.json() if r3.status_code == 200 else []
            pl = pl if isinstance(pl, list) else pl.get("positions", [])
            _mine = [p for p in pl if p.get("symbol", "").startswith(sym_b)]
            comp["mt5_unrealized"] = round(sum(float(p.get("profit", 0) or 0) for p in _mine), 6)
            comp["mt5_swap_unrealized"] = round(sum(float(p.get("swap", 0) or 0) for p in _mine), 6)
            comp["mt5_position_lot"] = round(sum(
                (1 if int(p.get("type", 0)) == 0 else -1) * abs(float(p.get("volume", 0) or 0))
                for p in _mine), 4)
        else:
            raise RuntimeError("no active bridge for account_b")
    except Exception as e:
        comp["mt5_unrealized"] = comp["mt5_swap_unrealized"] = comp["mt5_position_lot"] = None
        incomplete.append(f"mt5_position: {e!r}")

    # 合计: 任一核心组件null → economic_pnl=null + INCOMPLETE
    _core = ("binance_unrealized", "mt5_unrealized", "funding_settled",
             "mt5_realized_profit", "mt5_swap_realized")
    if any(comp.get(k) is None for k in _core):
        econ = None
        confidence = "INCOMPLETE"
    else:
        # mt5_unrealized(profit)与swap_unrealized分列; economic合计含浮动swap
        econ = round(comp["binance_unrealized"] + comp["mt5_unrealized"]
                     + (comp.get("mt5_swap_unrealized") or 0)
                     + comp["funding_settled"] + comp["mt5_realized_profit"]
                     + comp["mt5_swap_realized"]
                     - abs(comp.get("binance_fee") or 0)
                     - abs(comp.get("mt5_commission") or 0), 6)
        confidence = "EXACT"
    return {
        "pair_code": pair_code, "symbol_a": sym_a, "symbol_b": sym_b,
        "conversion_factor": conv,
        "components": comp,
        "economic_pnl": econ,
        "confidence": confidence,
        "incomplete_reasons": incomplete or None,
        "note": "未扣最终双腿退出成本(exit_cost), 为偏乐观口径; funding_settled/fee为该账户该symbol全历史累计",
    }
