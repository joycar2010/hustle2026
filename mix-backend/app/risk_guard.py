"""MIX-V6.2-PATCH-02 §8:C2.P/C3 点差扩大主动保护——C 侧 shadow 核心。

两条常驻 loop(main.py startup 拉起):
  spread_sampler_loop(300s)   前置③:逐在管/候选币采样 跨所费差+最窄点差 → mix_main.risk_spread_sample
                              (M3 软阈值 L4 的历史分位数据源;硬线不等它)
  risk_exit_loop(120s)        四层保护评估器:真实退出估值 closeout_pnl_net/L_now → 状态机(滞回+最短驻留)
                              → 发布 dcm:risk:exit + 落 snapshot/event → 工作项投影消费

铁律(批准前置④):本模块 SHADOW——绝不下单、绝不驱动退出;唯一的"硬"动作=
  风险保护态 >= NO_ADD 时该币新增风险动作(送入工作台/生成计划)在服务端降级禁用(硬线阻断新增)。
自动双腿退出(RiskExitSaga armed)单独立项,须混沌+shadow 触发记录+用户显式放行。

估值口径(§8.2,禁止K线/中间价冒充):
  C2 pair: closeout_pnl_net = Σ腿(按对手侧盘口可成交价平仓) upnl − taker费(5bps×2腿) − 半点差滑点
           (待付funding按结算边界≈0 计,approximation 记录在 evidence)
  C3 pos : L_now ≈ 借币利息(现查活口径×价) + 平仓成本(名义×(平点差+2×taker)) —— 保守上界
数据缺失=该层不触发+data_gaps 如实记录,绝不用 0 冒充。
"""
import asyncio
import json
import os
import time
import datetime as dt
import logging

from . import datasources as ds

log = logging.getLogger("mix.risk_guard")

VENUES = ("binance", "okx", "bybit", "gate", "bitget", "hyperliquid")
TAKER_BPS = 5.0
STATES = ["NORMAL", "WATCH", "NO_ADD", "REDUCE_REQUIRED", "EXIT_REQUIRED"]
LVL = {s: i for i, s in enumerate(STATES)}
EXIT_KEY = "dcm:risk:exit"          # 面板/投影消费
SM_KEY = "dcm:risk:exit:sm"         # 状态机驻留(hash: sym → {state,since,last_change})
# REV2 §15 MIX_V62_RISK_EXIT_ENFORCE:enforce=硬生存线阻断+态≥NO_ADD进blocked_symbols(已由policy消费,
# mode无关)+EXIT_REQUIRED告警升fatal;**armed双腿退出真金执行仍另门控(DCM_RISK_EXIT_ARMED),不受此flag影响**。
_ENFORCE = os.environ.get("MIX_V62_RISK_EXIT_ENFORCE", "false").lower() == "true"
_MODE = "enforce" if _ENFORCE else "shadow"

_DDL = """CREATE TABLE IF NOT EXISTS risk_spread_sample (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    gap_pct DOUBLE PRECISION,
    min_spread_bps DOUBLE PRECISION);
CREATE INDEX IF NOT EXISTS idx_rss_sym_ts ON risk_spread_sample (symbol, ts DESC);
CREATE TABLE IF NOT EXISTS risk_exit_policy (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    version INT NOT NULL DEFAULT 1,
    product_scope TEXT NOT NULL DEFAULT 'C2.P,C2.H,C3.S',
    hard_loss_budget_abs DOUBLE PRECISION NOT NULL,
    hard_loss_budget_pct_nav DOUBLE PRECISION NOT NULL,
    min_margin_level DOUBLE PRECISION NOT NULL DEFAULT 1.10,
    max_liq_pct DOUBLE PRECISION NOT NULL DEFAULT 80,
    max_recovery_windows DOUBLE PRECISION NOT NULL,
    spread_watch_q DOUBLE PRECISION NOT NULL DEFAULT 0.90,
    spread_reduce_q DOUBLE PRECISION NOT NULL DEFAULT 0.967,
    hysteresis DOUBLE PRECISION NOT NULL DEFAULT 0.7,
    min_state_duration_sec INT NOT NULL DEFAULT 600,
    reduction_steps INT NOT NULL DEFAULT 3,
    emergency_exit_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS risk_exit_snapshot (
    id BIGSERIAL PRIMARY KEY,
    work_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    product TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    closeout_pnl_net DOUBLE PRECISION,
    l_now DOUBLE PRECISION,
    hard_budget DOUBLE PRECISION,
    budget_remaining DOUBLE PRECISION,
    recovery_windows DOUBLE PRECISION,
    margin_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_name TEXT NOT NULL DEFAULT '',
    policy_version INT,
    as_of TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_res_key_ts ON risk_exit_snapshot (work_key, id DESC);
CREATE TABLE IF NOT EXISTS risk_exit_event (
    id BIGSERIAL PRIMARY KEY,
    work_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    ts TIMESTAMPTZ NOT NULL DEFAULT now())"""

# 三档模板(操作员只见档位;强平生存线/硬亏损线任何档都不放宽——宽松档只放软层)
_POLICY_SEED = [
    # name, abs, pct_nav, min_ml, max_liq, max_rec, watch_q, reduce_q, is_default
    ("保守", 20.0, 2.0, 1.15, 75, 9, 0.90, 0.967, True),
    ("均衡", 35.0, 3.0, 1.12, 78, 12, 0.93, 0.98, False),
    ("宽松", 60.0, 5.0, 1.10, 80, 18, 0.95, 0.99, False),
]

_seeded = False
_qcache: dict = {}   # sym → (ts, {watch_px, reduce_px, n})


async def _pool():
    p = await ds.pg_main()
    if p is None:
        return None
    global _seeded
    if not _seeded:
        await p.execute(_DDL)
        for n, a, pct, ml, lq, rec, wq, rq, dflt in _POLICY_SEED:
            await p.execute(
                "INSERT INTO risk_exit_policy(name, hard_loss_budget_abs, hard_loss_budget_pct_nav, "
                "min_margin_level, max_liq_pct, max_recovery_windows, spread_watch_q, spread_reduce_q, "
                "is_default) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT (name) DO NOTHING",
                n, a, pct, ml, lq, rec, wq, rq, dflt)
        _seeded = True
    return p


async def _hget_json(key: str, field: str):
    try:
        raw = await ds.rds().hget(key, field)
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


async def _l1(venue: str, sym: str):
    l1 = await _hget_json(f"dcm:feed:{venue}:perp", sym)
    if not l1:
        return None
    b, a = float(l1.get("bid") or 0), float(l1.get("ask") or 0)
    if b <= 0 or a <= 0:
        return None
    fresh = (time.time() * 1000 - float(l1.get("recv_ts") or 0)) < 120000
    return {"bid": b, "ask": a, "mid": (a + b) / 2,
            "spread_bps": (a - b) / ((a + b) / 2) * 10000, "fresh": fresh}


async def _funding_gap(sym: str):
    fs = {}
    for v in VENUES:
        f = await _hget_json(f"dcm:feed:funding:{v}", sym)
        if f and f.get("daily_pct") is not None:
            fs[v] = float(f["daily_pct"])
    if len(fs) < 2:
        return None, fs
    return max(fs.values()) - min(fs.values()), fs


async def _active_symbols() -> set:
    """采样/评估范围=在管(manager C1/C2 + coin C3)∪opener 候选。"""
    syms: set = set()
    try:
        mgr = await ds.get_json("dcm:exec:manager") or {}
        for x in (mgr.get("symbols") or []):
            if x.get("symbol"):
                syms.add(x["symbol"])
        for p in (mgr.get("pairs") or []):
            s = p.get("symbol") or p.get("pair")
            if s:
                syms.add(s)
    except Exception:  # noqa: BLE001
        pass
    try:
        snap = await ds.get_json("dcm:engine:coin:positions") or {}
        for p in (snap.get("positions") or []):
            if p.get("symbol") and str(p.get("status")) not in ("CLOSED", "FAILED", "SETTLED"):
                syms.add(p["symbol"])
    except Exception:  # noqa: BLE001
        pass
    try:
        op = await ds.get_json("dcm:exec:opener") or {}
        for c in (op.get("candidates") or [])[:20]:
            if c.get("symbol"):
                syms.add(c["symbol"])
    except Exception:  # noqa: BLE001
        pass
    return syms


# ─────────────────────── ③ 分位采样器(300s) ───────────────────────

async def spread_sampler_loop():
    await asyncio.sleep(10)
    n_runs = 0
    while True:
        try:
            pool = await _pool()
            if pool is not None:
                for sym in await _active_symbols():
                    gap, _ = await _funding_gap(sym)
                    spreads = []
                    for v in VENUES:
                        l1 = await _l1(v, sym)
                        if l1 and l1["fresh"]:
                            spreads.append(l1["spread_bps"])
                    await pool.execute(
                        "INSERT INTO risk_spread_sample(symbol, gap_pct, min_spread_bps) VALUES($1,$2,$3)",
                        sym, gap, (min(spreads) if spreads else None))
                n_runs += 1
                if n_runs % 288 == 0:   # 约每天清理一次 90 天外样本
                    await pool.execute("DELETE FROM risk_spread_sample WHERE ts < now() - interval '90 days'")
        except Exception as e:  # noqa: BLE001
            log.warning("spread sampler: %s", e)
        await asyncio.sleep(300)


async def _quantiles(pool, sym: str, wq: float, rq: float):
    """30 天窗 |gap| 分位;<100 样本=L4 不启用(样本不足用保守模板+限仓,不拟合长尾)。"""
    now = time.time()
    c = _qcache.get(sym)
    if c and now - c[0] < 600:
        return c[1]
    out = None
    try:
        row = await pool.fetchrow(
            "SELECT count(*) AS n, "
            "percentile_cont($2) WITHIN GROUP (ORDER BY abs(gap_pct)) AS wq, "
            "percentile_cont($3) WITHIN GROUP (ORDER BY abs(gap_pct)) AS rq "
            "FROM risk_spread_sample WHERE symbol=$1 AND ts > now() - interval '30 days' "
            "AND gap_pct IS NOT NULL", sym, wq, rq)
        if row and int(row["n"]) >= 100:
            out = {"n": int(row["n"]), "watch": float(row["wq"]), "reduce": float(row["rq"])}
    except Exception:  # noqa: BLE001
        pass
    _qcache[sym] = (now, out)
    return out


# ─────────────────────── 四层评估(§8.3) ───────────────────────

async def _nav() -> float | None:
    try:
        st = await ds.get_json("dcm:risk:status") or {}
        v = ((st.get("reconcile") or {}).get("total_equity_usdt"))
        return float(v) if v is not None else None
    except Exception:  # noqa: BLE001
        return None


async def _eval_c2_pair(pair: dict) -> dict | None:
    """C2 双永续:closeout=按对手侧盘口平两腿 upnl−费−滑点。"""
    sym = pair.get("symbol") or pair.get("pair")
    legs = [lg for lg in (pair.get("legs") or []) if abs(float(lg.get("amt") or 0)) > 1e-12]
    if not sym or not legs:
        return None
    gaps: list = []
    min_dist: list = []   # [(venue, dist_liq_pct)] 逐腿强平距离(PATCH-02 ③)
    fees = slip = notional = upnl = 0.0
    fresh_all, have_upnl = True, False
    for lg in legs:
        v, amt = lg.get("venue"), float(lg.get("amt") or 0)
        l1 = await _l1(v, sym)
        if not l1:
            gaps.append(f"L1缺失:{v}")
            fresh_all = False
            continue
        if not l1["fresh"]:
            fresh_all = False
        leg_not = abs(amt) * l1["mid"]
        notional += leg_not
        fees += leg_not * TAKER_BPS / 10000
        slip += leg_not * (l1["spread_bps"] / 2 / 10000)
        acct = await ds.get_json(f"dcm:account:{v}") or {}
        pd = (acct.get("pos_detail") or {}).get(sym) or {}
        if pd.get("upnl") is not None:
            upnl += float(pd["upnl"])
            have_upnl = True
        # PATCH-02 ③:逐venue强平距离(account-snapshot 已发 dist_liq_pct/liq,全六所)——补 L1 数据缺口
        dlp = pd.get("dist_liq_pct")
        if dlp is not None:
            min_dist.append((v, float(dlp)))
    if not have_upnl:
        gaps.append("upnl缺失(账户快照无该仓)")
    closeout = (upnl - fees - slip) if have_upnl else None
    gap, fmap = await _funding_gap(sym)
    # 保守净carry/结算窗:费差×名义×(窗/天)⁻¹×0.6 折价(扣费/滑点/平台折价的粗保守系数)
    carry_w = (abs(gap) / 100 * notional / 3 * 0.6) if (gap is not None and notional > 0) else None
    # L1 生存线:取所有腿里最近强平的那条(最小 dist_liq_pct);缺失=如实不触发(不冒充安全)
    margin = {}
    if min_dist:
        worst_v, worst_dist = min(min_dist, key=lambda x: x[1])
        margin = {"min_dist_liq_pct": worst_dist, "worst_venue": worst_v}
    else:
        gaps.append("逐venue强平距离缺失(账户快照无dist_liq_pct)")
    return {"symbol": sym, "product": "C2", "work_key": f"pair:{sym}",
            "closeout_pnl_net": closeout, "notional": notional,
            "l_now": (max(0.0, -closeout) if closeout is not None else None),
            "carry_per_window": carry_w, "gap_now": gap, "funding": fmap,
            "margin": margin,
            "fresh": fresh_all, "data_gaps": gaps}


async def _eval_c3_pos(pos: dict, panel: dict) -> dict | None:
    """C3 借币点差:L_now 保守上界=活口径利息+平仓成本(平点差+2×taker)。"""
    sym = pos.get("symbol")
    if not sym or str(pos.get("status")) in ("CLOSED", "FAILED", "SETTLED"):
        return None
    base = sym[:-4] if sym.endswith("USDT") else sym
    gaps: list = []
    sm = None
    for _uid, bal in (panel.get("balances") or {}).items():
        if isinstance(bal, dict) and isinstance((bal.get("symbol_margin") or {}).get(base), dict):
            sm = bal["symbol_margin"][base]
            break
    l1 = await _l1("binance", sym)
    px = l1["mid"] if l1 else None
    if px is None:
        gaps.append("L1缺失:binance")
    borrowed = float((sm or {}).get("borrowed") or 0)
    interest = float((sm or {}).get("interest") or 0)
    if sm is None:
        gaps.append("panel无该币margin")
    notional = (borrowed * px) if px else float(pos.get("open_usdt_amount") or 0)
    interest_usdt = interest * px if px else None
    close_pct = None
    try:
        srt = await _hget_json("dcm:coin:spreads_rt", sym) or await _hget_json("dcm:coin:spreads_rt", base)
        if isinstance(srt, dict):
            close_pct = srt.get("close_pct") or srt.get("close") or None
    except Exception:  # noqa: BLE001
        pass
    if close_pct is None:
        gaps.append("平点差缺失(按0.2%保守)")
    close_cost = notional * ((float(close_pct) if close_pct is not None else 0.2) / 100 + 2 * TAKER_BPS / 10000)
    l_now = (interest_usdt + close_cost) if interest_usdt is not None else None
    ml = (sm or {}).get("margin_level")
    liq = None
    try:
        liqmap = panel.get("master_futures_liq_pct")
        if isinstance(liqmap, dict):
            liq = liqmap.get(sym) or liqmap.get(base)
        elif liqmap is not None:
            liq = liqmap
    except Exception:  # noqa: BLE001
        pass
    # C3 收益/窗:点差收益按开点差估计缺账本口径→保守用 gap=None(L3 由 L_now/预算主导)
    return {"symbol": sym, "product": "C3.S", "work_key": f"c3:{pos.get('id')}:{sym}",
            "closeout_pnl_net": (-l_now if l_now is not None else None), "notional": notional,
            "l_now": l_now, "carry_per_window": None, "gap_now": None, "funding": {},
            "margin": {"margin_level": ml, "master_liq_pct": liq},
            "fresh": bool(l1 and l1["fresh"]), "data_gaps": gaps}


def _desired_level(m: dict, pol: dict, nav: float | None, q: dict | None) -> tuple[int, list]:
    reasons = []
    lvl = 0
    # 预算=min(绝对上限, NAV×pct)——不按名义×固定百分比(§8.3)
    budget = pol["hard_loss_budget_abs"]
    if nav:
        budget = min(budget, nav * pol["hard_loss_budget_pct_nav"] / 100)
    m["hard_budget"] = round(budget, 2)
    ln = m.get("l_now")
    # L1 生存线(触发即 EXIT_REQUIRED,任何档不放宽)
    mg = m.get("margin") or {}
    ml = mg.get("margin_level")          # C3:全仓保证金率(币安 999=无负债哨兵)
    liq = mg.get("master_liq_pct")       # C3:主账户合约强平占比
    min_dist = mg.get("min_dist_liq_pct")  # C2:逐venue最近强平距离%(PATCH-02 ③)
    if ml is not None and float(ml) < pol["min_margin_level"] and float(ml) < 900:
        return 4, [f"L1生存线:margin_level {float(ml):.3f} < {pol['min_margin_level']}"]
    if liq is not None and float(liq) > pol["max_liq_pct"]:
        return 4, [f"L1生存线:强平距离 liq {float(liq):.0f}% > {pol['max_liq_pct']}%"]
    # C2 逐腿强平距离:min_dist_liq_pct 越近(<100-max_liq_pct 的余量)=生存线告急
    if min_dist is not None:
        dist_floor = 100 - pol["max_liq_pct"]   # max_liq_pct=80 → 距强平<20% 即触发
        if float(min_dist) < dist_floor:
            return 4, [f"L1生存线:{mg.get('worst_venue', '')}腿距强平仅 {float(min_dist):.1f}% < {dist_floor:.0f}%"]
        if float(min_dist) < dist_floor * 1.5:
            lvl, reasons = max(lvl, 3), reasons + [f"L1告警:{mg.get('worst_venue', '')}腿距强平 {float(min_dist):.1f}%"]
    # L2 硬亏损预算
    if ln is not None:
        m["budget_remaining"] = round(budget - ln, 2)
        if ln >= budget:
            return 4, [f"L2硬亏损:L_now {ln:.2f}U ≥ 预算 {budget:.2f}U"]
        if ln >= budget * 0.8:
            lvl, reasons = max(lvl, 3), reasons + [f"L2预算告急:L_now {ln:.2f}U ≥ 80%预算"]
    # L3 回本期限
    cw = m.get("carry_per_window")
    if ln is not None and ln > 0 and cw is not None:
        rec = (ln / cw) if cw > 0 else float("inf")
        m["recovery_windows"] = (round(rec, 1) if rec != float("inf") else None)
        if rec == float("inf"):
            lvl = max(lvl, 3 if ln > budget * 0.5 else 2)
            reasons.append("L3回本:保守净carry≤0,回本=∞")
        elif rec > pol["max_recovery_windows"]:
            lvl = max(lvl, 2)
            reasons.append(f"L3回本:{rec:.1f}窗 > {pol['max_recovery_windows']:.0f}窗上限")
    # L4 历史分位(≥100样本才启用)
    g = m.get("gap_now")
    if g is not None and q:
        if abs(g) >= q["reduce"]:
            lvl = max(lvl, 2)
            reasons.append(f"L4分位:|gap|{abs(g):.3f} ≥ p{int(pol['spread_reduce_q']*1000)/10}({q['reduce']:.3f},n={q['n']})")
        elif abs(g) >= q["watch"]:
            lvl = max(lvl, 1)
            reasons.append(f"L4分位:|gap|{abs(g):.3f} ≥ p{int(pol['spread_watch_q']*100)}({q['watch']:.3f})")
    return lvl, reasons


async def _transition(r, key: str, desired: int, reasons: list, pol: dict) -> tuple[str, bool]:
    """状态机:升级即时;降级须 滞回(desired 明显更低)+最短驻留+逐级。返回(新状态,是否变化)。"""
    now = time.time()
    cur, since = 0, now
    try:
        raw = await r.hget(SM_KEY, key)
        if raw:
            st = json.loads(raw)
            cur = LVL.get(st.get("state"), 0)
            since = float(st.get("since") or now)
    except Exception:  # noqa: BLE001
        pass
    new = cur
    if desired > cur:
        new = desired                      # 升级即时(且可跳级,如直达 EXIT_REQUIRED)
    elif desired < cur:
        if now - since >= pol["min_state_duration_sec"] and desired <= cur - 1:
            new = cur - 1                  # 降级逐级+最短驻留(滞回由 desired 计算端体现)
    changed = new != cur
    if changed or True:
        await r.hset(SM_KEY, key, json.dumps(
            {"state": STATES[new], "since": (now if changed else since), "last_change": now if changed else None}))
    return STATES[new], changed


async def risk_exit_loop():
    await asyncio.sleep(20)
    while True:
        try:
            pool = await _pool()
            r = ds.rds()
            if pool is None or r is None:
                await asyncio.sleep(120)
                continue
            pol = dict(await pool.fetchrow(
                "SELECT * FROM risk_exit_policy WHERE is_default ORDER BY id LIMIT 1"))
            nav = await _nav()
            metrics: list = []
            mgr = await ds.get_json("dcm:exec:manager") or {}
            for p in (mgr.get("pairs") or []):
                m = await _eval_c2_pair(p)
                if m:
                    metrics.append(m)
            # C1(单所两腿)也纳入 L1/L2(同 pair 口径,现货腿滑点近似 perp)
            for x in (mgr.get("symbols") or []):
                if abs(float(x.get("perp_amt") or 0)) > 1e-9:
                    m = await _eval_c2_pair({"symbol": x.get("symbol"),
                                             "legs": [{"venue": "binance", "amt": x.get("perp_amt")}]})
                    if m:
                        m["product"] = "C1"
                        m["work_key"] = f"c1:{x.get('symbol')}"
                        metrics.append(m)
            panel = await ds.get_json("dcm:coin:panel") or {}
            snap = await ds.get_json("dcm:engine:coin:positions") or {}
            for p in (snap.get("positions") or []):
                m = await _eval_c3_pos(p, panel)
                if m:
                    metrics.append(m)

            items = {}
            for m in metrics:
                q = await _quantiles(pool, m["symbol"], pol["spread_watch_q"], pol["spread_reduce_q"])
                desired, reasons = _desired_level(m, pol, nav, q)
                state, changed = await _transition(r, m["work_key"], desired, reasons, pol)
                rec = {
                    "state": state, "product": m["product"], "work_key": m["work_key"],
                    "closeout_pnl_net": (round(m["closeout_pnl_net"], 2) if m.get("closeout_pnl_net") is not None else None),
                    "l_now": (round(m["l_now"], 2) if m.get("l_now") is not None else None),
                    "hard_budget": m.get("hard_budget"),
                    "budget_remaining": m.get("budget_remaining"),
                    "recovery_windows": m.get("recovery_windows"),
                    "margin": m.get("margin"), "gap_now": m.get("gap_now"),
                    "reasons": reasons, "data_gaps": m.get("data_gaps") or [],
                    "policy": f"{pol['name']}v{pol['version']}", "mode": _MODE,
                    "as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
                # 同币取最严格档(一个币可能同时有 c1/c3 键)
                old = items.get(m["symbol"])
                if not old or LVL[state] > LVL[old["state"]]:
                    items[m["symbol"]] = rec
                if changed:
                    await pool.execute(
                        "INSERT INTO risk_exit_event(work_key, symbol, from_state, to_state, reason, evidence) "
                        "VALUES($1,$2,'',$3,$4,$5::jsonb)",
                        m["work_key"], m["symbol"], state, ";".join(reasons)[:400],
                        json.dumps(rec, ensure_ascii=False, default=str))
                    if LVL[state] >= 3:
                        try:   # 跑马灯+通知(shadow 标注,与 dcm_common 报文契约一致)
                            await r.publish("dcm:notify:broadcast", json.dumps({
                                "service": "risk-exit", "level": "fatal" if LVL[state] >= 4 else "warning",
                                "title": f"[shadow]点差保护 {m['symbol']} → {state}",
                                "content": ";".join(reasons)[:180], "color": "red", "blink": LVL[state] >= 4,
                            }, ensure_ascii=False))
                        except Exception:  # noqa: BLE001
                            pass
                await pool.execute(
                    "INSERT INTO risk_exit_snapshot(work_key, symbol, product, state, closeout_pnl_net, "
                    "l_now, hard_budget, budget_remaining, recovery_windows, margin_summary, evidence, "
                    "policy_name, policy_version) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,$12,$13)",
                    m["work_key"], m["symbol"], m["product"], state,
                    m.get("closeout_pnl_net"), m.get("l_now"), m.get("hard_budget"),
                    m.get("budget_remaining"), m.get("recovery_windows"),
                    json.dumps(m.get("margin") or {}, default=str),
                    json.dumps({"reasons": reasons, "gaps": m.get("data_gaps")}, ensure_ascii=False, default=str),
                    pol["name"], pol["version"])
            await r.set(EXIT_KEY, json.dumps({"items": items, "policy": f"{pol['name']}v{pol['version']}",
                                              "mode": _MODE, "ts": time.time()},
                                             ensure_ascii=False, default=str), ex=600)
        except Exception as e:  # noqa: BLE001
            log.warning("risk exit loop: %s", e)
        await asyncio.sleep(120)
