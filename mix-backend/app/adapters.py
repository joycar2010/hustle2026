"""
适配层 —— 把真实数据源(dcm 总线/dcm_main/coin 桥快照)翻译成前端契约形状。
诚实呈现三原则：
  1) phase 直接映射引擎状态机，不推断；映射不到的状态原文放 phaseLabel。
  2) 拿不到的数值一律 '—'（dim），绝不编数；未启用策略如实标注，绝不用演示数据冒充。
  3) 数据源失联返回空集 + degraded 标记，绝不 500。
"""
import time
import datetime as dt
from typing import Any, Optional

from . import datasources as ds
from . import config

VENUES = ["binance", "bybit", "okx", "gate", "bitget", "hyperliquid"]

# ---- 状态机映射（引擎权威状态 → 契约 PhaseCode；label 保留引擎原语义） ----
DP_PHASE = {
    "OPENING": ("OPENING", "开仓中"),
    "OPEN": ("HOLDING", "持有·收费"),
    "CLOSING": ("EXITING", "平仓中"),
    "ROLLBACK": ("EXITING", "回滚中"),
    "CLOSED": ("SETTLED", "已结算"),
    "FAILED": ("SETTLED", "失败终态"),
}
COIN_PHASE = {
    "PENDING_BORROW": ("PENDING_BORROW", "借币中"),
    "BORROWED_IDLE": ("ARMED", "已借币·待建仓"),
    "OPEN": ("HOLDING", "持仓·收费率"),
    "PENDING_REPAY": ("REPAYING", "还币中"),
    "CLOSED": ("SETTLED", "已结算"),
    "FAILED": ("SETTLED", "失败终态"),
}
SVC_STRATEGY = {
    "engine-dualperp": "S2", "engine-basis": "S1", "coin-bridge": "S3",
    "lending-advisor": "S4", "event-calendar": "S5", "carry-advisor": "S2",
    "borrow-monitor": "S3",
}

S2_LABELS = ["多腿数量", "空腿数量", "费率差%/d", "下次结费", "净Delta", "距强平%"]
S1_LABELS = ["现货腿", "永续空", "日化%/d", "名义U", "开仓E bps", "距强平%"]
S3_LABELS = ["现-期", "爆率", "最大可借", "现币", "借币", "借币金额", "风险", "保证金", "净值"]

DASH = {"value": "—", "dim": True}


def _now() -> float:
    return time.time()


def _age_text(ts: Optional[float]) -> str:
    if not ts:
        return "—"
    a = max(0, int(_now() - float(ts)))
    if a < 90:
        return f"{a}s"
    if a < 5400:
        return f"{a // 60}m"
    return f"{a // 3600}h"


def _hours_since(iso: Any) -> str:
    try:
        t = dt.datetime.fromisoformat(str(iso))
        h = (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600
        return f"持仓 {h:.1f}h"
    except Exception:  # noqa: BLE001
        return "持仓"


def _num(v, nd=4) -> str:
    try:
        return f"{float(v):,.{nd}f}"
    except Exception:  # noqa: BLE001
        return "—"


async def _funding(venue: str) -> dict[str, dict]:
    return await ds.hgetall_json(f"dcm:feed:funding:{venue}")


async def _accounts_snap() -> dict[str, dict]:
    """{venue: snapshot} —— dcm:account:*"""
    raw = await ds.keys_values("dcm:account:*")
    return {k.rsplit(":", 1)[-1]: v for k, v in raw.items() if v}


def _next_settle(interval_h: Optional[float]) -> tuple[Optional[int], str]:
    """按 interval 对齐 UTC 边界估下次结算。返回 (epoch_ms, 'HH:MM:SS 剩余')。"""
    try:
        sec = int(float(interval_h) * 3600)
        if sec <= 0:
            return None, "—"
        nxt = (int(_now()) // sec + 1) * sec
        rem = nxt - int(_now())
        return nxt * 1000, f"{rem // 3600:02d}:{rem % 3600 // 60:02d}:{rem % 60:02d}"
    except Exception:  # noqa: BLE001
        return None, "—"


# ================= 坑位行 =================

async def position_rows(strategy: Optional[str] = None) -> list[dict]:
    rows: list[dict] = []
    if strategy in (None, "", "S2"):
        rows += await _s2_rows()
    if strategy in (None, "", "S1"):
        rows += await _s1_rows()
    if strategy in (None, "", "S3"):
        rows += await _s3_rows()
    return rows


async def _s2_rows() -> list[dict]:
    db = await ds.fetch(
        "SELECT symbol, venue_long, venue_short, qty_base, notional_usdt, state, opened_at "
        "FROM dualperp_positions WHERE state NOT IN ('CLOSED','FAILED') ORDER BY opened_at")
    if not db:
        return []
    snaps = await _accounts_snap()
    risk = await ds.get_json("dcm:risk:status") or {}
    guards = {g.get("symbol"): g for g in (risk.get("guards") or {}).get("pairs", [])}
    fund = {v: await _funding(v) for v in {r["venue_long"] for r in db} | {r["venue_short"] for r in db}}

    by_sym: dict[str, list[dict]] = {}
    for r in db:
        by_sym.setdefault(r["symbol"], []).append(r)

    out = []
    for sym, group in by_sym.items():
        r0 = group[-1]
        vl, vs = r0["venue_long"], r0["venue_short"]
        fl = (fund.get(vl) or {}).get(sym) or {}
        fs = (fund.get(vs) or {}).get(sym) or {}
        edge = None
        if fl.get("daily_pct") is not None and fs.get("daily_pct") is not None:
            edge = float(fs["daily_pct"]) - float(fl["daily_pct"])
        ddl_ms, ddl_txt = _next_settle(fs.get("interval_h") or fl.get("interval_h"))
        g = guards.get(sym) or {}
        dl = (g.get("dist_liq") or {})
        pdl = (snaps.get(vl) or {}).get("pos_detail", {}).get(sym) or {}
        pds = (snaps.get(vs) or {}).get("pos_detail", {}).get(sym) or {}
        upnl = None
        if pdl.get("upnl") is not None or pds.get("upnl") is not None:
            upnl = round(float(pdl.get("upnl") or 0) + float(pds.get("upnl") or 0), 4)
        ql = (snaps.get(vl) or {}).get("positions", {}).get(sym)
        qs = (snaps.get(vs) or {}).get("positions", {}).get(sym)
        delta = None
        if ql is not None or qs is not None:
            delta = float(ql or 0) + float(qs or 0)
        phase, label = DP_PHASE.get(r0["state"], ("HOLDING", r0["state"]))
        qty = sum(float(x["qty_base"]) for x in group)
        notion = sum(float(x["notional_usdt"]) for x in group)

        def leg(venue, qty_cell, side, pd, dliq):
            return {
                "executingAccount": f"{venue}", "accountKind": "master",
                "venue": venue, "platformType": "cex",
                "values": [
                    qty_cell if side == "L" else DASH,
                    qty_cell if side == "S" else DASH,
                    {"value": f"{edge:+.3f}" if edge is not None else "—", "tone": "up" if (edge or 0) > 0 else "down"},
                    {"value": ddl_txt, "tone": "accent"},
                    {"value": f"{delta:+.4f}" if delta is not None else "—",
                     "tone": "up" if abs(delta or 0) < 1e-9 else "down"},
                    {"value": f"{dliq:.1f}%" if dliq is not None else "—",
                     "tone": "down" if (dliq is not None and dliq < 20) else None},
                ],
                "econParams": [
                    {"label": "润", "value": f"{pd.get('upnl'):+.4f}" if pd.get("upnl") is not None else "—",
                     "tone": "up" if (pd.get("upnl") or 0) >= 0 else "down"},
                    {"label": "ADL", "value": str(int(pd["adl"])) if pd.get("adl") is not None else "—"},
                    {"label": "标记", "value": _num(pd.get("mark"), 6) if pd.get("mark") is not None else "—"},
                ],
                "state": {"kind": "holding", "text": _hours_since(r0["opened_at"])},
                "fundingRateRatio": f"{edge:+.3f}" if edge is not None else None,
                "apiRestricted": False, "apiStatus": "ok",
            }

        out.append({
            "id": f"DP-{sym}", "symbol": sym, "positionCount": len(group),
            "strategyCode": "S2", "phase": phase, "phaseLabel": label,
            "columnLabels": S2_LABELS,
            "marketParams": [
                {"label": "多", "value": f"{vl} {float(fl.get('daily_pct')):.3f}%/d" if fl.get("daily_pct") is not None else vl},
                {"label": "空", "value": f"{vs} {float(fs.get('daily_pct')):.3f}%/d" if fs.get("daily_pct") is not None else vs, "tone": "accent"},
                {"label": "差", "value": f"{edge:+.3f}%/d" if edge is not None else "—", "tone": "up" if (edge or 0) > 0 else "down"},
                {"label": "名义", "value": f"{notion:,.0f}U"},
            ],
            "pushStatus": f"结费 {ddl_txt}" if ddl_ms else "—",
            "fundingRateRatio": f"{edge:+.3f}" if edge is not None else "—",
            "singleRuleBrief": "-", "allowRemove": False, "allowRepay": False,
            "pnl": upnl,
            "openedAt": str(r0["opened_at"]) if r0["opened_at"] else None,
            "keyDeadlineTs": ddl_ms, "ruleScope": "template",
            "subRows": [
                leg(vl, {"value": _num(qty, 4), "tone": "strategy"}, "L", pdl, dl.get("long")),
                leg(vs, {"value": _num(qty, 4), "tone": "strategy"}, "S", pds, dl.get("short")),
            ],
        })
    return out


async def _s1_rows() -> list[dict]:
    db = await ds.fetch(
        "SELECT symbol, base_asset, qty_base, notional_usdt, state, open_e_bps, funding_daily, opened_at "
        "FROM basis_positions WHERE state NOT IN ('CLOSED','FAILED') ORDER BY opened_at")
    if not db:
        return []
    snaps = await _accounts_snap()
    fund_bn = await _funding("binance")
    out = []
    for r in db:
        sym = r["symbol"]
        f = fund_bn.get(sym) or {}
        pd = (snaps.get("binance") or {}).get("pos_detail", {}).get(sym) or {}
        daily = f.get("daily_pct", r["funding_daily"])
        phase, label = DP_PHASE.get(r["state"], ("HOLDING", r["state"]))
        ddl_ms, ddl_txt = _next_settle(f.get("interval_h"))
        dliq = pd.get("dist_liq_pct")
        out.append({
            "id": f"BS-{sym}", "symbol": sym, "positionCount": 1,
            "strategyCode": "S1", "phase": phase, "phaseLabel": f"{label}·期现",
            "columnLabels": S1_LABELS,
            "marketParams": [
                {"label": "资", "value": f"{float(daily):.3f}%/d" if daily is not None else "—", "tone": "accent"},
                {"label": "时", "value": f"{f.get('interval_h', '—')}h"},
                {"label": "名义", "value": f"{float(r['notional_usdt']):,.0f}U"},
            ],
            "pushStatus": f"结费 {ddl_txt}" if ddl_ms else "—",
            "fundingRateRatio": f"{float(daily):.3f}" if daily is not None else "—",
            "singleRuleBrief": "-", "allowRemove": False, "allowRepay": False,
            "pnl": round(float(pd["upnl"]), 4) if pd.get("upnl") is not None else None,
            "openedAt": str(r["opened_at"]) if r["opened_at"] else None,
            "keyDeadlineTs": ddl_ms, "ruleScope": "template",
            "subRows": [{
                "executingAccount": "binance", "accountKind": "master",
                "venue": "binance", "platformType": "cex",
                "values": [
                    {"value": _num(r["qty_base"], 4), "tone": "strategy"},
                    {"value": _num(pd.get("qty"), 4) if pd.get("qty") is not None else "—"},
                    {"value": f"{float(daily):.3f}" if daily is not None else "—", "tone": "accent"},
                    {"value": f"{float(r['notional_usdt']):,.0f}"},
                    {"value": f"{float(r['open_e_bps']):.1f}" if r["open_e_bps"] is not None else "—"},
                    {"value": f"{dliq:.1f}%" if dliq is not None else "—"},
                ],
                "econParams": [
                    {"label": "润", "value": f"{pd.get('upnl'):+.4f}" if pd.get("upnl") is not None else "—",
                     "tone": "up" if (pd.get("upnl") or 0) >= 0 else "down"},
                    {"label": "ADL", "value": str(int(pd["adl"])) if pd.get("adl") is not None else "—"},
                ],
                "state": {"kind": "holding", "text": _hours_since(r["opened_at"])},
                "fundingRateRatio": None, "apiRestricted": False, "apiStatus": "ok",
            }],
        })
    return out


def _mmss(sec) -> Optional[str]:
    try:
        s = int(float(sec))
        if s <= 0:
            return None
        return f"{s // 60}:{s % 60:02d}"
    except Exception:  # noqa: BLE001
        return None


async def _s3_rows() -> list[dict]:
    """S3 = coin 借币面板 1:1（dcm:coin:panel，coin-bridge 60s 发布）：
    币种行 = 推送中的币 ∪ 在管仓位；子行 = 各子账户杠杆户真实数值（同列位异义）。
    现-期/爆率两列需 master 合约快照，panel 暂无 —— 给 '—' 不编数（Phase B.2）。"""
    panel = await ds.get_json("dcm:coin:panel") or {}
    snap = await ds.get_json("dcm:engine:coin:positions") or {}
    positions = snap.get("positions") or []
    bal_top = panel.get("balances") or {}
    accounts = bal_top.get("balances") or []
    if not accounts and not positions:
        return []
    # ① master 合约快照（balance_pusher 顶层字段）：现-期=逐币 positionAmt、爆率=维持保证金率%
    master_pos = bal_top.get("master_futures_positions") or {}
    master_liq = bal_top.get("master_futures_liq_pct")
    uid_w = panel.get("uid_weight") or {}
    interest = panel.get("interest_rates") or {}
    spreads = panel.get("spreads") or {}
    bl_syms = {str(b.get("symbol", "")).upper() for b in (panel.get("blacklist") or [])}
    fund_bn = await _funding("binance")

    pos_by_sym: dict[str, list[dict]] = {}
    for p in positions:
        pos_by_sym.setdefault(str(p.get("symbol", "?")).upper(), []).append(p)
    syms = sorted({str(s).upper() for s in (panel.get("pushed") or [])} | set(pos_by_sym))

    out = []
    for sym in syms:
        base = sym[:-4] if sym.endswith("USDT") else sym
        sp = spreads.get(sym) or {}
        f = fund_bn.get(sym) or {}
        ir = interest.get(base)
        group = pos_by_sym.get(sym, [])
        spot_bid = None
        try:
            spot_bid = float(sp.get("spot_bid")) if sp.get("spot_bid") else None
        except Exception:  # noqa: BLE001
            pass

        sub_rows = []
        any_borrowable = False
        for acct in accounts:
            sm = (acct.get("symbol_margin") or {}).get(sym)
            aid = acct.get("account_id")
            pos = next((p for p in group if p.get("sub_account_id") == aid), None)
            if sm is None and pos is None:
                continue
            sm = sm or {}
            borrowed = float(sm.get("borrowed") or 0)
            free = float(sm.get("free") or 0)
            if float(sm.get("effective_borrowable") or 0) > 0:
                any_borrowable = True
            ml = acct.get("margin_level")
            ml_tone = "up" if (ml or 0) > 2 else ("accent" if (ml or 0) > 1.3 else "down")
            noinv = bool(sm.get("no_inventory"))
            repay_hold = float(sm.get("repayhold_remaining_sec") or 0)
            if pos:
                st = {"kind": "holding", "text": COIN_PHASE.get(str(pos.get("status")), ("", str(pos.get("status"))))[1]}
            elif repay_hold > 0:
                st = {"kind": "repay_paused", "text": "还币暂停", "resumable": False}
            elif borrowed > 0:
                st = {"kind": "borrowing", "text": "借币在身"}
            elif noinv:
                st = {"kind": "plain", "text": str(sm.get("borrow_cap_reason") or "无券")}
            else:
                st = {"kind": "plain", "text": "空闲"}
            uw = uid_w.get(str(aid)) or {}
            rate_txt = None
            if uw.get("uid_limit"):
                rate_txt = f"UID {uw.get('used_uid_weight_1m', 0)}/{uw['uid_limit']}·1m"
            dir_pct = sm.get("daily_interest_rate")
            econ = [
                {"label": "息", "value": f"{float(dir_pct) * 100:.3f}%" if dir_pct is not None else "—"},
                {"label": "累息", "value": _num(sm.get("interest"), 6), "tone": "down"},
            ]
            if pos:
                econ.append({"label": "开仓额", "value": _num(pos.get("open_usdt_amount"), 2)})
            mp = master_pos.get(sym)
            liq_tone = None
            if master_liq is not None:
                liq_tone = "down" if float(master_liq) > 80 else ("accent" if float(master_liq) > 50 else "up")
            sub_rows.append({
                "executingAccount": str(acct.get("note") or f"sub:{aid}"),
                "accountKind": "sub", "venue": "binance", "platformType": "cex",
                "values": [
                    # 现-期/爆率 = master 合约（hedge_via_master，全表同值即架构体现）
                    {"value": _num(mp, 4), "dim": abs(float(mp or 0)) < 1e-9} if mp is not None else DASH,
                    {"value": f"{float(master_liq):.1f}%", "tone": liq_tone} if master_liq is not None else DASH,
                    {"value": _num(sm.get("borrow_limit"), 0), "tone": "accent"},
                    {"value": _num(free, 4), "dim": free < 1e-9},
                    {"value": _num(borrowed, 4), "tone": "strategy", "dim": borrowed < 1e-9},
                    {"value": f"{borrowed * spot_bid:,.2f}" if (spot_bid and borrowed) else "—",
                     "dim": not (spot_bid and borrowed)},
                    {"value": _num(ml, 2), "tone": ml_tone},
                    {"value": _num(acct.get("margin_net_usdt"), 2)},
                    {"value": _num(acct.get("margin_usdt_free"), 2)},
                ],
                "econParams": econ,
                "state": st,
                "fundingRateRatio": None,
                "borrowRatePerSec": rate_txt,
                "banCountdown": _mmss(sm.get("noinv_remaining_sec")),
                "apiRestricted": False, "apiStatus": "ok",
            })

        if group:
            status = str(group[-1].get("status", "OPEN"))
            phase, label = COIN_PHASE.get(status, ("HOLDING", status))
        elif any_borrowable:
            phase, label = "BORROWABLE", "可借·候选"
        else:
            phase, label = "CANDIDATE", "推送中·无券"
        mark = None
        if sym in bl_syms:
            label += "·黑名单"
            mark = "risk"
        opened = group[-1].get("opened_ts") if group else None
        out.append({
            "id": f"CN-{sym}", "symbol": sym, "positionCount": len(group),
            "mark": mark,
            "strategyCode": "S3", "phase": phase, "phaseLabel": label,
            "columnLabels": S3_LABELS,
            "marketParams": [
                {"label": "开", "value": f"{float(sp.get('spread_long')):.3f}" if sp.get("spread_long") else "—",
                 "tone": "down" if sp.get("spread_long") and float(sp["spread_long"]) < 0 else None},
                {"label": "平", "value": f"{float(sp.get('spread_short')):.3f}" if sp.get("spread_short") else "—"},
                {"label": "资", "value": f"{float(f['daily_pct']):.3f}%/d" if f.get("daily_pct") is not None else "—",
                 "tone": "accent"},
                {"label": "时", "value": f"{f.get('interval_h', '—')}h"},
                {"label": "息", "value": f"{float(ir) * 100:.3f}%" if ir is not None else "—", "tone": "accent"},
            ],
            "pushStatus": "面板 " + _age_text(panel.get("ts")),
            "fundingRateRatio": f"{float(f['daily_pct']):.3f}" if f.get("daily_pct") is not None else "—",
            "singleRuleBrief": "-", "allowRemove": False, "allowRepay": False,
            "pnl": None,
            "openedAt": (dt.datetime.fromtimestamp(int(opened), dt.timezone.utc).isoformat()
                         if opened else None),
            "keyDeadlineTs": None, "ruleScope": "template",
            "subRows": sub_rows,
        })
    return out


async def resolve_coin_position(symbol: str, executing_account: str | None) -> Optional[dict]:
    """按 币种(+子账户备注名) 定位 coin 非终态持仓行（意图账）。找不到返回 None。"""
    snap = await ds.get_json("dcm:engine:coin:positions") or {}
    panel = await ds.get_json("dcm:coin:panel") or {}
    note_to_id = {str(a.get("note")): a.get("account_id")
                  for a in (panel.get("balances") or {}).get("balances") or []}
    cand = [p for p in (snap.get("positions") or [])
            if str(p.get("symbol", "")).upper() == symbol.upper()]
    if executing_account and executing_account in note_to_id:
        cand = [p for p in cand if p.get("sub_account_id") == note_to_id[executing_account]]
    return cand[-1] if cand else None


async def route_of(symbol: str) -> Optional[dict]:
    routes = await ds.hgetall_json("dcm:route:assignments")
    v = routes.get(symbol.upper())
    return v if isinstance(v, dict) else None


async def blacklist_rows() -> list[dict]:
    """coin 黑名单真读（panel 透传）。dcm-route: 前缀 = 路由互斥自动行。"""
    panel = await ds.get_json("dcm:coin:panel") or {}
    bl = panel.get("blacklist")
    if not isinstance(bl, list):
        return []
    out = []
    for b in bl:
        reason = str(b.get("reason") or "")
        mutex = reason.startswith("dcm-route:")
        out.append({
            "symbol": str(b.get("symbol", "")).replace("USDT", ""),
            "rawSymbol": b.get("symbol"),
            "source": "risk_trigger" if mutex else "manual",
            "reason": reason + ("（路由互斥：该币已归 dcm 引擎，coin 只拦新开仓）" if mutex else ""),
            "scope": ["S3"],
            "addedAt": str(b.get("created_at") or "")[5:16].replace("T", " "),
            "until": "路由解除自动移除" if mutex else "手动移除",
            "hits": 0,
        })
    return out


# ================= 策略总览 =================

async def strategies_overview() -> list[dict]:
    dp_snap = await ds.get_json("dcm:engine:dualperp:positions") or {}
    bs_snap = await ds.get_json("dcm:engine:basis:positions") or {}
    coin_state = await ds.get_json("dcm:engine:coin:state") or {}
    coin_pos = await ds.get_json("dcm:engine:coin:positions") or {}
    lending = await ds.get_json("dcm:lending:ranking") or {}
    lend_snap = await ds.get_json("dcm:engine:lending:positions")
    routes = await ds.hgetall_json("dcm:route:assignments")
    listings = await ds.get_json("dcm:event:new_listings")

    dp_db = await ds.fetch(
        "SELECT state, count(*) n, coalesce(sum(notional_usdt),0) notion FROM dualperp_positions "
        "WHERE state NOT IN ('CLOSED','FAILED') GROUP BY state")
    bs_db = await ds.fetch(
        "SELECT state, count(*) n, coalesce(sum(notional_usdt),0) notion FROM basis_positions "
        "WHERE state NOT IN ('CLOSED','FAILED') GROUP BY state")
    attr = await _attribution_totals()

    def agg(dbrows, key):
        return sum(int(r["n"]) for r in dbrows if r["state"] == key)

    active_routes = [v for v in routes.values() if isinstance(v, dict) and v.get("state") in ("active", "draining")]
    dp_routes = [v for v in active_routes if v.get("engine") == "dualperp"]
    dp_mode = dp_snap.get("mode", "—")
    bs_mode = bs_snap.get("mode", "shadow")
    scopes = coin_state.get("engine_state") or []
    running = sum(1 for s in scopes if s.get("status") == "RUNNING")
    _coin_st: dict[str, int] = {}
    for _p in coin_pos.get("positions") or []:
        _coin_st[str(_p.get("status"))] = _coin_st.get(str(_p.get("status")), 0) + 1
    lend_top = (lending.get("top") or [])
    n_listing = len(listings) if isinstance(listings, list) else (len(listings) if isinstance(listings, dict) else 0)

    return [
        {"code": "S1", "name": "单所期现基差 Carry", "layer": "底仓层",
         "enabled": bool(bs_db), "slots": sum(int(r["n"]) for r in bs_db),
         "notional": float(sum(float(r["notion"]) for r in bs_db)),
         "pnlToday": attr["S1"]["today"], "pnlTotal": attr["S1"]["total"], "ePass": "—",
         "pipeline": {"模式": bs_mode, "开仓中": agg(bs_db, "OPENING"), "持有": agg(bs_db, "OPEN"),
                      "平仓中": agg(bs_db, "CLOSING")}},
        {"code": "S2", "name": "双合约期期 Carry", "layer": "中层主力",
         "enabled": dp_mode in ("armed", "shadow"), "slots": agg(dp_db, "OPEN") + agg(dp_db, "OPENING"),
         "notional": float(sum(float(r["notion"]) for r in dp_db)),
         "pnlToday": attr["S2"]["today"], "pnlTotal": attr["S2"]["total"], "ePass": "—",
         "pipeline": {"模式": dp_mode, "活跃路由": len(dp_routes), "武装": len(dp_snap.get("armed_symbols") or []),
                      "开仓中": agg(dp_db, "OPENING"), "持有": agg(dp_db, "OPEN"),
                      "平仓中": agg(dp_db, "CLOSING") + agg(dp_db, "ROLLBACK")}},
        {"code": "S3", "name": "借币反向 Carry / 点差", "layer": "存量业务",
         "enabled": running > 0, "slots": int(coin_pos.get("count") or 0), "notional": 0,
         "pnlToday": 0, "pnlTotal": 0, "ePass": "—",
         "pipeline": {"可借扫描": len((await ds.get_json("dcm:coin:panel") or {}).get("pushed") or []),
                      "借币": _coin_st.get("PENDING_BORROW", 0),
                      "已借待对冲": _coin_st.get("BORROWED_IDLE", 0),
                      "收费率·在管": _coin_st.get("OPEN", 0),
                      "还币闸": _coin_st.get("PENDING_REPAY", 0),
                      "引擎": f"{running}/{len(scopes)}"}},
        {"code": "S4", "name": "借贷利率套利", "layer": "增强层",
         "enabled": bool(lend_snap), "slots": len((lend_snap or {}).get("would_hold") or []),
         "notional": 0, "pnlToday": 0, "pnlTotal": 0, "ePass": "—",
         "pipeline": {"模式": (lend_snap or {}).get("mode", "未启用"),
                      "would_hold": (lend_snap or {}).get("slots", "0"),
                      "候选榜": len(lend_top),
                      "榜首": f"{lend_top[0]['coin']} {lend_top[0]['net_daily_pct']:.2f}%/d" if lend_top else "—"}},
        {"code": "S5", "name": "事件驱动 + LST/锚定折价", "layer": "机会外挂",
         "enabled": False, "slots": 0, "notional": 0, "pnlToday": 0, "pnlTotal": 0, "ePass": "—",
         "pipeline": {"新上市监听": n_listing, "状态": "仅事件流·未启用"}},
        {"code": "S6", "name": "费率飞轮", "layer": "元游戏",
         "enabled": False, "slots": 0, "notional": 0, "pnlToday": 0, "pnlTotal": 0, "ePass": "—",
         "pipeline": {"状态": "未启用"}},
    ]


# ================= 监控 =================

async def heartbeats() -> list[dict]:
    hbs = await ds.keys_values("dcm:hb:*")
    out = []
    for k, v in hbs.items():
        svc = k.rsplit(":", 1)[-1]
        ts = (v or {}).get("ts")
        limit = config.HB_EXPECTED.get(svc, config.HB_DEFAULT_SEC)
        ok = bool(ts) and (_now() - float(ts)) < limit * 1.5
        out.append({"proc": svc, "shard": str((v or {}).get("pid", "—")), "age": _age_text(ts), "ok": ok})
    return sorted(out, key=lambda x: (x["ok"], x["proc"]))


async def freshness() -> dict:
    fund = await _funding("binance")
    stale = sum(1 for v in fund.values() if v.get("ts") and _now() - float(v["ts"]) > 1800)
    risk = await ds.get_json("dcm:risk:status") or {}
    coin = risk.get("coin") or {}
    return {
        "stale": {"count": stale, "of": len(fund)},
        "frozen": {"shards": len(coin.get("stale_scopes") or [])},
        "divergent": [],
    }


async def watermarks() -> list[dict]:
    prop = await ds.get_json("dcm:fund:proposal") or {}
    out = []
    for v in prop.get("venues") or []:
        eq, tgt = float(v.get("equity") or 0), float(v.get("target") or 0)
        if tgt <= 0:
            continue
        level = min(1.0, eq / tgt)
        threshold = "ok"
        sug = None
        if level < 1.0:
            threshold = "topup" if level >= 0.5 else "withdraw"
            sug = {"text": f"目标水位 {tgt:,.0f}U，缺口 {max(0, tgt - eq):,.0f}U（fund-scheduler 提案制，人工划转）",
                   "feasible": True}
        out.append({"account": v.get("venue"), "venue": v.get("venue"),
                    "available": f"{eq:,.2f}", "level": round(level, 3),
                    "threshold": threshold, "suggestion": sug})
    return out


async def spreads_board() -> list[dict]:
    """跨所费差榜（xv 口径:最优多/空腿日化差），点差列待 depth 采样接入。"""
    per_venue = {v: await _funding(v) for v in VENUES}
    best: dict[str, dict] = {}
    for venue, fund in per_venue.items():
        for sym, f in fund.items():
            d = f.get("daily_pct")
            if d is None:
                continue
            b = best.setdefault(sym, {"lo": None, "hi": None, "lo_v": "", "hi_v": "", "n": 0})
            b["n"] += 1
            if b["lo"] is None or d < b["lo"]:
                b["lo"], b["lo_v"] = d, venue
            if b["hi"] is None or d > b["hi"]:
                b["hi"], b["hi_v"] = d, venue
    rows = []
    for sym, b in best.items():
        if b["n"] < 2:
            continue
        edge = float(b["hi"]) - float(b["lo"])
        rows.append({"symbol": sym.replace("USDT", ""), "open": "—", "close": "—",
                     "funding": f"{edge:+.4f}",
                     "dailyRate": f"{edge:.3f}%",
                     "net": f"{edge:+.2f}",
                     "venues": f"多{b['lo_v']}/空{b['hi_v']}",
                     "status": "可开" if edge >= 0.15 else ("观察" if edge >= 0.05 else "不可")})
    rows.sort(key=lambda x: -float(x["funding"]))
    return rows[:30]


async def borrowables() -> list[dict]:
    avail = await ds.hgetall_json("dcm:borrow:avail")
    by_sym: dict[str, list] = {}
    for k, v in avail.items():
        venue, _, sym = k.partition(":")
        by_sym.setdefault(sym, []).append((venue, v))
    out = []
    for sym, lst in sorted(by_sym.items()):
        total = sum(float(x[1].get("amount") or 0) for x in lst)
        detail = " / ".join(f"{v}:{float(d.get('amount') or 0):,.0f}" for v, d in sorted(lst))
        out.append({"symbol": sym, "qty": f"{total:,.2f}", "usd": "—",
                    "health": "可借" if total > 0 else "无券", "detail": detail})
    out.sort(key=lambda x: (x["health"] != "无券", x["symbol"]))
    return out


# ================= 告警 / 报表 =================

async def monitor_overview() -> dict:
    """主控台聚合：全局工作流管道(8段,分策略堆叠) + 右栏五卡。全部真信号，无演示数。"""
    risk = await ds.get_json("dcm:risk:status") or {}
    dp_snap = await ds.get_json("dcm:engine:dualperp:positions") or {}
    coin_pos = (await ds.get_json("dcm:engine:coin:positions") or {}).get("positions") or []
    panel = await ds.get_json("dcm:coin:panel") or {}
    lend_snap = await ds.get_json("dcm:engine:lending:positions") or {}
    llm = await ds.get_json("dcm:advisor:llm") or {}
    summ = await ds.get_json("dcm:pnl:summary") or {}
    carry_e = await ds.hgetall_json("dcm:arb:carry_e")
    verdicts = await ds.hgetall_json("dcm:arb:verdicts")
    routes = await ds.hgetall_json("dcm:route:assignments")
    hbs = await heartbeats()
    hb_map = {h["proc"]: h for h in hbs}

    def _st(states, key):
        return sum(int(r["n"]) for r in states if r["state"] == key)

    dp_states = await ds.fetch("SELECT state, count(*) n FROM dualperp_positions GROUP BY 1")
    bs_states = await ds.fetch("SELECT state, count(*) n FROM basis_positions GROUP BY 1")
    dp_closed_24h = (await ds.fetch(
        "SELECT count(*) n FROM dualperp_positions WHERE state='CLOSED' AND closed_at > now() - interval '24 hours'"))
    bs_closed_24h = (await ds.fetch(
        "SELECT count(*) n FROM basis_positions WHERE state='CLOSED' AND closed_at > now() - interval '24 hours'"))
    coin_by_status: dict[str, int] = {}
    for p in coin_pos:
        coin_by_status[str(p.get("status"))] = coin_by_status.get(str(p.get("status")), 0) + 1
    active_routes = [v for v in routes.values() if isinstance(v, dict) and v.get("state") in ("active", "draining")]
    r_by_engine = {"dualperp": 0, "basis": 0, "coin": 0}
    for v in active_routes:
        r_by_engine[v.get("engine", "")] = r_by_engine.get(v.get("engine", ""), 0) + 1
    lend_hold = len(lend_snap.get("would_hold") or [])

    def seg(label, split: dict, note=""):
        return {"label": label, "total": sum(split.values()),
                "split": {k: v for k, v in split.items() if v}, "note": note}

    pipeline = [
        seg("候选", {"S2": len(carry_e), "S3": len(panel.get("pushed") or []),
                    "S4": len((await ds.get_json("dcm:lending:ranking") or {}).get("top") or [])}),
        seg("E 仲裁", {"S2": len(verdicts)}),
        seg("活跃路由", {"S2": r_by_engine.get("dualperp", 0), "S1": r_by_engine.get("basis", 0),
                     "S3": r_by_engine.get("coin", 0)}),
        seg("武装", {"S2": len(dp_snap.get("armed_symbols") or [])},
            note=f"mode={dp_snap.get('mode', '—')}"),
        seg("开仓中", {"S2": _st(dp_states, "OPENING"), "S1": _st(bs_states, "OPENING"),
                    "S3": coin_by_status.get("PENDING_BORROW", 0) + coin_by_status.get("BORROWED_IDLE", 0)}),
        seg("持有", {"S2": _st(dp_states, "OPEN"), "S1": _st(bs_states, "OPEN"),
                   "S3": coin_by_status.get("OPEN", 0), "S4": lend_hold},
            note="S4=shadow"),
        seg("退出", {"S2": _st(dp_states, "CLOSING") + _st(dp_states, "ROLLBACK"),
                   "S1": _st(bs_states, "CLOSING"), "S3": coin_by_status.get("PENDING_REPAY", 0)}),
        seg("结出·24h", {"S2": int(dp_closed_24h[0]["n"]) if dp_closed_24h else 0,
                       "S1": int(bs_closed_24h[0]["n"]) if bs_closed_24h else 0}),
    ]

    recon = risk.get("reconcile") or {}
    netexp = risk.get("net_exposure") or {}
    recon2 = risk.get("recon_v2") or {}
    waterline = risk.get("waterline") or []
    max_lev = max((float(w.get("lev") or 0) for w in waterline), default=0) if isinstance(waterline, list) else 0
    services = risk.get("services") or {}
    ok_n = sum(1 for v in services.values() if v == "ok")

    def hb_ok(svc):
        return bool(hb_map.get(svc, {}).get("ok"))

    advisors = [
        {"name": "carry 组合顾问", "cadence": "10min·选对/容量钳位/退出滞回",
         "status": "运行中" if hb_ok("carry-advisor") else "停更"},
        {"name": "借贷增强顾问", "cadence": "4min·三率净差榜",
         "status": "运行中" if hb_ok("lending-advisor") else "停更"},
        {"name": "S4 shadow 执行器", "cadence": "5min·决策流水",
         "status": f"shadow·{lend_snap.get('slots', '—')}" if hb_ok("engine-lending") else "停更"},
        {"name": "LLM 评审层", "cadence": "15min·只读只建议",
         "status": (f"ok·{llm.get('model', '')}" if llm.get("status") == "ok" else str(llm.get("status") or "未配置"))
         if hb_ok("llm-advisor") else "停更"},
    ]
    support_b = [
        {"name": "跨域净敞口账本 R8", "ok": not (netexp.get("breaches") or [])},
        {"name": "RECON 逆向对账 R11", "ok": not (recon2.get("orphans") or [])},
        {"name": "保证金对称/ADL R6", "ok": hb_ok("risk-ledger")},
        {"name": "实盘对账六所 R5", "ok": bool(recon.get("configured"))},
        {"name": "服务心跳巡检 R1", "ok": ok_n == len(services) and len(services) > 0},
        {"name": "coin 引擎活性 R2/R3", "ok": not ((risk.get("coin") or {}).get("stale_scopes") or [])},
        {"name": "PnL 三表持久化", "ok": hb_ok("pnl-recorder")},
        {"name": "资金水位提案", "ok": hb_ok("fund-scheduler")},
        {"name": "事件日历(上市/下架)", "ok": hb_ok("event-calendar")},
        {"name": "借币/充提监控", "ok": hb_ok("borrow-monitor") and hb_ok("transfer-monitor")},
    ]
    return {
        "pipeline": pipeline,
        "health": {"ok": ok_n, "total": len(services), "services": services},
        "risk": {"total_equity": recon.get("total_equity_usdt"),
                 "net_breaches": len(netexp.get("breaches") or []),
                 "net_floor": netexp.get("floor"),
                 "orphans": len(recon2.get("orphans") or []),
                 "max_lev": round(max_lev, 2),
                 "alerts_this_round": risk.get("alerts_this_round")},
        "advisors": advisors,
        "support_b": support_b,
        "pnl_today": summ.get("net_today"),
        "panel_age_sec": int(_now() - float(panel.get("ts") or _now())),
    }


async def monitor_events() -> list[dict]:
    """公告/上市事件（event-calendar 产物）。"""
    listings = await ds.get_json("dcm:event:new_listings")
    out = []
    items = listings if isinstance(listings, list) else (listings or {}).get("items", []) if isinstance(listings, dict) else []
    for x in (items or [])[:20]:
        if isinstance(x, dict):
            out.append({"type": x.get("type", "上市"), "text": x.get("symbol") or x.get("title") or str(x)[:80],
                        "at": x.get("ts") or x.get("first_seen") or ""})
        else:
            out.append({"type": "上市", "text": str(x), "at": ""})
    return out


async def alerts(limit: int = 50, strategy: Optional[str] = None) -> list[dict]:
    rows = await ds.fetch(
        "SELECT ts, service, level, title, content FROM alerts_log ORDER BY ts DESC LIMIT $1", limit)
    if strategy:
        rows = [r for r in rows if SVC_STRATEGY.get(r["service"]) == strategy]
    out = []
    for r in rows:
        lvl = str(r["level"]).upper()
        out.append({
            "at": r["ts"].astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%m-%d %H:%M:%S"),
            "level": lvl if lvl in ("FATAL", "WARN", "INFO") else "WARN",
            "strategy": SVC_STRATEGY.get(r["service"]),
            "text": f"[{r['service']}] {r['title']}" + (f" — {r['content'][:120]}" if r["content"] else ""),
        })
    return out


async def _strategy_symbol_sets() -> tuple[set, set]:
    dp = await ds.fetch("SELECT DISTINCT symbol FROM dualperp_positions")
    bs = await ds.fetch("SELECT DISTINCT symbol FROM basis_positions")
    return {r["symbol"] for r in dp}, {r["symbol"] for r in bs}


async def report_pnl(range_key: str) -> list[dict]:
    days = {"30d": 30, "90d": 90, "180d": 180, "all": 3650}.get(range_key, 30)
    rows = await ds.fetch(
        "SELECT (ts AT TIME ZONE 'UTC')::date d, itype, sum(amount) amt FROM income_records "
        "WHERE itype <> 'TRANSFER' AND ts > now() - ($1 || ' days')::interval GROUP BY 1,2 ORDER BY 1", str(days))
    # net 口径对齐 pnl-recorder（已对账验证）：net = FUNDING + PNL + FEE，OTHER 不计净但单列可见
    by_day: dict[str, dict] = {}
    for r in rows:
        d = str(r["d"])
        e = by_day.setdefault(d, {"date": d, "funding": 0.0, "spread": 0.0, "fee": 0.0, "other": 0.0, "net": 0.0})
        amt = float(r["amt"])
        it = r["itype"]
        if it == "FUNDING":
            e["funding"] += amt
        elif it == "PNL":
            e["spread"] += amt
        elif it == "FEE":
            e["fee"] += amt
        else:
            e["other"] += amt
            continue
        e["net"] += amt
    return [{**v, "funding": round(v["funding"], 4), "spread": round(v["spread"], 4),
             "fee": round(v["fee"], 4), "other": round(v["other"], 4),
             "net": round(v["net"], 4)} for v in by_day.values()]


async def _attribution_totals() -> dict:
    """归因主源=写入时打标的 strategy_code（0009 根治）；空标签行回落币种集合启发式兜底。"""
    dp_syms, bs_syms = await _strategy_symbol_sets()
    rows = await ds.fetch(
        "SELECT symbol, itype, coalesce(strategy_code,'') scode, "
        "sum(amount) total, sum(amount) FILTER (WHERE ts > date_trunc('day', now())) today "
        "FROM income_records WHERE itype <> 'TRANSFER' GROUP BY 1,2,3")
    acc = {s: {"today": 0.0, "total": 0.0, "subjects": {}} for s in ("S1", "S2")}
    for r in rows:
        strat = r["scode"] if r["scode"] in ("S1", "S2") else ("S1" if r["symbol"] in bs_syms else "S2")
        key = {"FUNDING": "funding", "PNL": "spread", "FEE": "fee"}.get(r["itype"], "other")
        if key != "other" and r["symbol"] and r["symbol"] not in bs_syms and r["symbol"] not in dp_syms:
            key = "unattributed"
        acc[strat]["subjects"][key] = round(acc[strat]["subjects"].get(key, 0.0) + float(r["total"] or 0), 4)
        if key == "other":  # net 口径对齐 pnl-recorder：OTHER 可见但不计净
            continue
        acc[strat]["total"] += float(r["total"] or 0)
        acc[strat]["today"] += float(r["today"] or 0)
    for s in acc.values():
        s["today"], s["total"] = round(s["today"], 4), round(s["total"], 4)
    return acc


async def attribution() -> list[dict]:
    acc = await _attribution_totals()
    return [
        {"code": "S2", "name": "双合约期期", "total": acc["S2"]["total"], "subjects": acc["S2"]["subjects"]},
        {"code": "S1", "name": "单所期现基差", "total": acc["S1"]["total"], "subjects": acc["S1"]["subjects"]},
        {"code": "S3", "name": "借币反向/点差", "total": 0, "subjects": {}, "note": "coin 账本待接入"},
        {"code": "S4", "name": "借贷利率套利", "total": 0, "subjects": {}, "note": "未启用"},
        {"code": "S5", "name": "事件/LST 折价", "total": 0, "subjects": {}, "note": "未启用"},
        {"code": "S6", "name": "费率飞轮", "total": 0, "subjects": {}, "note": "未启用"},
    ]


# ================= 账户 / 币管理 / 用户端 =================

async def account_nodes() -> list[dict]:
    snaps = await _accounts_snap()
    out = []
    for venue in VENUES:
        s = snaps.get(venue)
        if s is None:
            continue
        npos = len(s.get("positions") or {})
        out.append({
            "id": venue, "kind": "master", "platformType": "cex", "venue": venue,
            "domain": "B·exec", "apiStatus": "ok" if s.get("ok") else "restricted",
            "metrics": {"净值": f"{float(s.get('equity_usdt') or 0):,.2f} U",
                        "持仓数": str(npos),
                        "快照": _age_text(s.get("ts"))},
            "approvalState": None, "children": [],
        })
    return out


async def coins_board() -> list[dict]:
    routes = await ds.hgetall_json("dcm:route:assignments")
    fund_bn = await _funding("binance")
    dp_open = {r["symbol"] for r in await ds.fetch(
        "SELECT DISTINCT symbol FROM dualperp_positions WHERE state NOT IN ('CLOSED','FAILED')")}
    bs_open = {r["symbol"] for r in await ds.fetch(
        "SELECT DISTINCT symbol FROM basis_positions WHERE state NOT IN ('CLOSED','FAILED')")}
    eng_strat = {"dualperp": "S2", "basis": "S1", "coin": "S3"}
    out = []
    for sym, v in routes.items():
        if not isinstance(v, dict):
            continue
        f = fund_bn.get(sym) or {}
        strat = eng_strat.get(v.get("engine"))
        managed = (1 if sym in dp_open else 0) + (1 if sym in bs_open else 0)
        out.append({
            "symbol": sym.replace("USDT", ""),
            "state": "enabled" if v.get("state") in ("active", "draining") else ("watch" if v.get("state") == "proposed" else "paused"),
            "strategies": [strat] if strat else [],
            "venues": f"{v.get('venue_long', '')}/{v.get('venue_short', '')}",
            "rate8h": f"{float(f['fr']) * 100:+.4f}%" if f.get("fr") is not None else "—",
            "spreadBps": None, "vol24h": "—", "managed": managed,
        })
    out.sort(key=lambda x: (x["state"] != "enabled", -x["managed"], x["symbol"]))
    return out


async def me_summary(view: str, venues: Optional[list[str]] = None) -> dict:
    """venues=None → 全量（operator/owner）；venues=[] → 该用户零绑定=零数据（默认拒绝隔离）。"""
    if venues is None:
        summ = await ds.get_json("dcm:pnl:summary") or {}
        week = await ds.fetch(
            "SELECT coalesce(sum(amount),0) s FROM income_records "
            "WHERE itype IN ('FUNDING','PNL','FEE') AND ts > now() - interval '7 days'")
        return {"view": view,
                "today": round(float(summ.get("net_today") or 0), 4),
                "week": round(float(week[0]["s"]), 4) if week else 0,
                "total": round(float(summ.get("net_total") or 0), 4),
                "note": "全量口径（dcm 账本，coin 账本待并入）"}
    if not venues:
        return {"view": view, "today": 0, "week": 0, "total": 0,
                "note": "账户未绑定任何交易所范围（联系管理员分配）"}
    rows = await ds.fetch(
        "SELECT coalesce(sum(amount) FILTER (WHERE ts > date_trunc('day', now())),0) today, "
        "coalesce(sum(amount) FILTER (WHERE ts > now() - interval '7 days'),0) week, "
        "coalesce(sum(amount),0) total FROM income_records "
        "WHERE itype IN ('FUNDING','PNL','FEE') AND venue = ANY($1)", venues)
    r = rows[0] if rows else {"today": 0, "week": 0, "total": 0}
    return {"view": view, "today": round(float(r["today"]), 4), "week": round(float(r["week"]), 4),
            "total": round(float(r["total"]), 4), "note": f"绑定范围：{'/'.join(venues)}"}


async def me_sources(venues: Optional[list[str]] = None) -> list[dict]:
    if venues is not None and not venues:
        return []
    cond, args = ("AND venue = ANY($1)", [venues]) if venues else ("", [])
    rows = await ds.fetch(
        f"SELECT itype, sum(amount) s FROM income_records WHERE itype <> 'TRANSFER' {cond} GROUP BY 1",
        *args)
    names = {"FUNDING": ("funding", "资金费率收入"), "PNL": ("pnl", "价差/基差收敛"),
             "FEE": ("fee", "手续费成本"), "OTHER": ("other", "利息与其他")}
    total_abs = sum(abs(float(r["s"])) for r in rows) or 1.0
    out = []
    for r in sorted(rows, key=lambda x: -abs(float(x["s"]))):
        key, name = names.get(r["itype"], (r["itype"].lower(), r["itype"]))
        out.append({"key": key, "name": name, "share": round(abs(float(r["s"])) / total_abs, 4),
                    "amount": round(float(r["s"]), 4)})
    return out


async def me_subaccounts(view: str, venues: Optional[list[str]] = None) -> list[dict]:
    snaps = await _accounts_snap()
    today = await ds.fetch(
        "SELECT venue, coalesce(sum(amount),0) s FROM income_records "
        "WHERE itype IN ('FUNDING','PNL','FEE') AND ts > date_trunc('day', now()) GROUP BY 1")
    total = await ds.fetch(
        "SELECT venue, coalesce(sum(amount),0) s FROM income_records "
        "WHERE itype IN ('FUNDING','PNL','FEE') GROUP BY 1")
    t_map = {r["venue"]: float(r["s"]) for r in today}
    tt_map = {r["venue"]: float(r["s"]) for r in total}
    show = VENUES if venues is None else [v for v in VENUES if v in venues]
    return [{"venue": v, "asset": round(float((snaps.get(v) or {}).get("equity_usdt") or 0), 2),
             "today": round(t_map.get(v, 0), 4), "total": round(tt_map.get(v, 0), 4)}
            for v in show if v in snaps]


async def me_fund_flows(venues: Optional[list[str]] = None) -> list[dict]:
    if venues is not None and not venues:
        return []
    cond, args = ("AND venue = ANY($1)", [venues]) if venues else ("", [])
    rows = await ds.fetch(
        f"SELECT ts, venue, symbol, amount FROM income_records "
        f"WHERE itype = 'TRANSFER' {cond} ORDER BY ts DESC LIMIT 30", *args)
    return [{"at": r["ts"].astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%m-%d %H:%M"),
             "type": "transfer", "ccy": r["symbol"] or "USDT",
             "amount": round(float(r["amount"]), 4),
             "path": r["venue"], "state": "done"} for r in rows]


async def report_pnl_scoped(range_key: str, venues: list[str]) -> list[dict]:
    """按绑定范围过滤的日收益序列（隔离版）。"""
    if not venues:
        return []
    days = {"30d": 30, "90d": 90, "180d": 180, "all": 3650}.get(range_key, 30)
    rows = await ds.fetch(
        "SELECT (ts AT TIME ZONE 'UTC')::date d, itype, sum(amount) amt FROM income_records "
        "WHERE itype <> 'TRANSFER' AND venue = ANY($2) "
        "AND ts > now() - ($1 || ' days')::interval GROUP BY 1,2 ORDER BY 1", str(days), venues)
    by_day: dict[str, dict] = {}
    for r in rows:
        d = str(r["d"])
        e = by_day.setdefault(d, {"date": d, "funding": 0.0, "spread": 0.0, "fee": 0.0, "other": 0.0, "net": 0.0})
        amt = float(r["amt"])
        it = r["itype"]
        if it == "FUNDING":
            e["funding"] += amt
        elif it == "PNL":
            e["spread"] += amt
        elif it == "FEE":
            e["fee"] += amt
        else:
            e["other"] += amt
            continue
        e["net"] += amt
    return [{**v, **{k: round(v[k], 4) for k in ("funding", "spread", "fee", "other", "net")}}
            for v in by_day.values()]
