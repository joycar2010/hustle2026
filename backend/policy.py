# -*- coding: utf-8 -*-
"""P1-b 统一 Entry/Exit Policy — 阶段A: 纯函数收敛层 (2026-07-25)

铁律: 零行为变化。本模块把散落在 app.py 三处(auto_entry循环/cmd_open_pair/auto_exit循环)的
入出场闸**逐比特提取**为纯函数, 分歧用 PROFILES 显式声明(原样保留, 统一后另立小批次逐项收敛)。

上线路径: shadow双跑(内联闸全放行到达执行点后, policy 重裁一次, 不一致落红
qh:policy:shadow:*) → 观察数日零分歧 → enforce 切换(内联闸替换为 policy 调用)。
本模块自身零 I/O(不碰 redis/db/桥), 全部输入由调用方提供 — 可离线 parity 模糊测试。

已知路径分歧(原样保留, PROFILES 里可见):
  D1 手动开仓无 run_window / market_closed 闸(休市点开仓靠券商拒单10018兜底)
  D2 保证金/预算闸读账户失败: auto=fail-open(静默放行) vs manual=fail-closed(502拒)
  D3 对冲腿保证金检查: manual 要求 hedge 腿存在才查, auto 只看 _rh>0
  (出场侧: 手动平仓无休市/维护闸=有意设计"休市可手平"; ENG.auto_exit_decision 本已统一)
"""
import engine as ENG

# ---------------- Profile 声明(闸顺序=真实内联执行顺序) ----------------
PROFILES = {
    "entry.auto": {
        "gates": ["run_window", "entry_window", "market_closed", "quote_stale",
                  "spread", "fluctuation", "margin_budget"],
        "margin_fail_closed": False,     # D2: 读账户失败静默放行
        "hedge_requires_leg": False,     # D3: 只看 _rh>0
    },
    "entry.manual": {
        "gates": ["entry_window", "quote_stale", "fluctuation", "margin_budget", "spread"],
        "margin_fail_closed": True,      # D2: 读账户失败 502 拒开
        "hedge_requires_leg": True,      # D3: hedge 腿存在才查
        # D1: 无 run_window / market_closed
    },
    "exit.auto_loop": {
        "gates": ["auto_close", "run_window", "market_closed"],
        # 坑级判定=ENG.auto_exit_decision(已统一, 本模块 exit_slot_decision 直通)
    },
}

# ---------------- 基础纯函数(逐比特提取自 app.py) ----------------

def in_window(start, end, now_min):
    """app._in_window 逐比特副本(now_min 必传保持纯函数)。
       空/未设→True; 跨零点支持; start==end→True。"""
    def _p(s):
        try:
            s = (s or "").strip()
            if not s or ":" not in s: return None
            h, m = s.split(":", 1); return int(h)*60 + int(m)
        except Exception: return None
    a = _p(start); b = _p(end)
    if a is None or b is None: return True
    if a == b: return True
    if a < b: return a <= now_min < b
    return now_min >= a or now_min < b

def gate_entry_spread(ov, gthr, cur_sp, fee_pts=0.0):
    """app._entry_gate 逐比特副本(enforce 阶段 app 将改调本函数)。
       返回 (通过?, 有效下限或None)。"""
    if ov is not None and ("buy_point" in ov):
        bp = ov.get("buy_point")
        lb = None if bp is None else float(bp)
    else:
        lb = gthr if (gthr and gthr > 0) else None
    if lb is None:
        return True, None
    lb_eff = lb + (fee_pts or 0.0)
    if cur_sp is None:
        return True, lb_eff
    return (float(cur_sp) >= lb_eff), lb_eff

# ---------------- 闸函数(输入=模板行 t + 调用方已取好的数据) ----------------

def gate_window(t, which, now_min):
    """which: 'run'|'entry'。blocked=True 表示拦。"""
    if which == "run":
        ok = in_window(t.get("run_win_start"), t.get("run_win_end"), now_min)
    else:
        ok = in_window(t.get("entry_win_start"), t.get("entry_win_end"), now_min)
    return (not ok), ("%s_window" % which)

def gate_market_closed(t):
    closed, why = ENG.market_closed(weekend_guard=t.get("weekend_guard", True),
                                    weekend_sat=t.get("weekend_sat"), weekend_sun=t.get("weekend_sun"))
    return bool(closed), why

def gate_quote_stale(stq):
    """stq=调用方 _quote_stale 结果(None=新鲜)。"""
    return bool(stq), (stq or "fresh")

def gate_fluctuation(t, hist_spreads):
    """hist_spreads=近 match_count 条 fs 列表(调用方从 spread:hist 取)。"""
    _mc = int(t.get("match_count") or 0); _bd = float(t.get("fluctuation_band") or 0)
    if not (_bd > 0 and _mc >= 2):
        return False, "off"
    fl = ENG.fluctuation_guard(hist_spreads, _mc, _bd)
    return bool(fl[0]), (fl[2] if len(fl) > 2 else "fluct")

def gate_margin_budget(t, accs, fail_closed, hedge_requires_leg=False, hedge_exists=True):
    """保证金预留 + 智能预判预算(批33)合并闸(与内联同块序: main→hedge→predict)。
       accs=both_accounts 结果(None/Exception=读失败)。"""
    _rm = float(t.get("margin_reserve_main") or 0)
    _rh = float(t.get("margin_reserve_hedge") or 0)
    _pb = float(t.get("predict_budget") or 0)
    if not (_rm > 0 or _rh > 0 or _pb > 0):
        return False, "off"
    if fail_closed:
        # manual 内联: `if _accs is None or isinstance(_accs,Exception): raise 502`
        if accs is None or isinstance(accs, Exception):
            return True, "margin_read_fail_closed"
    else:
        # auto 内联: `if accs:` 真值判断(None/空dict 都静默放行) — D2 fail-open 逐比特复刻
        if not accs:
            return False, "margin_read_fail_open"
    if _rm > 0:
        ok_m, why_m = ENG.margin_sufficient((accs.get("main") or {}).get("margin_free"), _rm, "main")
        if not ok_m: return True, why_m
    if _rh > 0 and ((not hedge_requires_leg) or hedge_exists):
        ok_h, why_h = ENG.margin_sufficient((accs.get("hedge") or {}).get("margin_free"), _rh, "hedge")
        if not ok_h: return True, why_h
    if _pb > 0:
        eq = (accs.get("main") or {}).get("equity")
        if eq and 0 < float(eq) < _pb:
            return True, "predict_budget(净值%.2f<预算%.2f)" % (float(eq), _pb)
    return False, "ok"

# ---------------- 组合裁决 ----------------

def entry_verdict(profile, t, ov, cur_sp, fee_pts, hist, accs, now_min,
                  quote_stale=None, hedge_exists=True):
    """单坑入场裁决: 按 profile 闸序逐一评估, 首个拦截即返回。
       返回 (blocked, gate_name, why)。"""
    p = PROFILES[profile]
    for g in p["gates"]:
        if g == "run_window":
            b, w = gate_window(t, "run", now_min)
        elif g == "entry_window":
            b, w = gate_window(t, "entry", now_min)
        elif g == "market_closed":
            b, w = gate_market_closed(t)
        elif g == "quote_stale":
            b, w = gate_quote_stale(quote_stale)
        elif g == "spread":
            gthr = float(t.get("entry_spread") or 0)
            ok, lb = gate_entry_spread(ov, gthr, cur_sp, fee_pts)
            b, w = (not ok), ("spread<下限%s" % lb if not ok else "ok")
        elif g == "fluctuation":
            b, w = gate_fluctuation(t, hist)
        elif g == "margin_budget":
            b, w = gate_margin_budget(t, accs, p["margin_fail_closed"],
                                      p.get("hedge_requires_leg", False), hedge_exists)
        else:
            continue
        if b:
            return True, g, w
    return False, None, "pass"

def exit_loop_verdict(t, now_min):
    """auto_exit 循环级闸裁决(auto_close→run_window→market_closed)。
       返回 (blocked, gate_name, why)。坑级判定另走 exit_slot_decision。"""
    if not t.get("auto_close"):
        return True, "auto_close", "master_off"
    b, w = gate_window(t, "run", now_min)
    if b: return True, "run_window", w
    b, w = gate_market_closed(t)
    if b: return True, "market_closed", w
    return False, None, "pass"

# 坑级出场判定: 已统一在 engine(唯一消费点), 直通导出供 enforce 阶段统一入口
exit_slot_decision = ENG.auto_exit_decision
