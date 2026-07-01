# Quant Hedge 服务端引擎 (P1) — 移植自 testgo，按 MT↔MT 锁仓配对重写
# 单进程 asyncio 管全部用户对；从 param_templates 热重载参数；读 bridge 行情；写 hedge_positions/deals
import datetime as dt
from zoneinfo import ZoneInfo

# ---------------- 1) 点差闸 (直接复用 testgo 点差阈值检测) ----------------
def spread_gate(main_ask, main_bid, hedge_ask, hedge_bid, entry_spread_thr):
    """返回 (可入场?, 当前点差, 原因)。锁仓对差 = 主BID - 对冲ASK（卖主买对冲口径之一）"""
    if None in (main_ask, main_bid, hedge_ask, hedge_bid):
        return False, None, "quote_missing"
    spread = round(abs(main_bid - hedge_ask), 5)
    if spread > entry_spread_thr:
        return False, spread, "spread_too_wide(%.5f>%.2f)" % (spread, entry_spread_thr)
    return True, spread, "ok"

# ---------------- 2) 休市闸 (复用 testgo CME黄金日历 + 周末) ----------------
# CME 贵金属：周日17:00 - 周五16:00 (美中部时间 CT)，每日 16:00-17:00 维护
_CME_HOLIDAYS_2026 = {"2026-01-01","2026-01-19","2026-02-16","2026-04-03",
                      "2026-05-25","2026-07-03","2026-09-07","2026-11-26","2026-12-25"}
def market_closed(now_utc=None, weekend_guard=True, weekend_sat=None, weekend_sun=None):
    """返回 (是否休市, 原因)。trade_mode 会撒谎，故用日历闸为准（testgo 教训）。
       weekend_sat/weekend_sun: True=该日允许交易(不休市)。给定时优先于 weekend_guard;
       未给定(None)时回落旧 weekend_guard 行为(周末整段休市)。"""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    ct = now.astimezone(ZoneInfo("America/Chicago"))
    wd = ct.weekday()  # 0=Mon..6=Sun
    if ct.strftime("%Y-%m-%d") in _CME_HOLIDAYS_2026:
        return True, "cme_holiday"
    # 周末双开关(开=可交易); 任一为 None 视为该侧未配置→回落 weekend_guard
    sat_ok = bool(weekend_sat) if weekend_sat is not None else False
    sun_ok = bool(weekend_sun) if weekend_sun is not None else False
    use_split = (weekend_sat is not None) or (weekend_sun is not None)
    if use_split:
        if wd == 5 and not sat_ok:   return True, "weekend_sat_off"
        if wd == 6 and not sun_ok:   return True, "weekend_sun_off"
        # Fri 收盘 / Sun 预开 闸仅在该日未开启交易时生效
        if wd == 4 and ct.hour >= 16 and not sat_ok: return True, "weekend_fri_close"
    elif weekend_guard:
        if wd == 5:  return True, "weekend_sat"
        if wd == 4 and ct.hour >= 16:  return True, "weekend_fri_close"
        if wd == 6 and ct.hour < 17:   return True, "weekend_sun_preopen"
    if ct.hour == 16:  # 每日维护窗 16:00-17:00 CT
        return True, "daily_maintenance"
    return False, "open"

# ---------------- 数据波动闸 (移植 testgo 行情波动护栏: 近N条价差波动过大→软暂停入场) ----------------
def fluctuation_guard(recent_spreads, match_count, band):
    """recent_spreads: 最近若干条点差(时间升序)。取最近 match_count 条, 若 (max-min) > band 则波动过大暂停入场。
       band<=0 或 match_count<2 → 闸关闭(放行)。数据不足 → fail-closed 暂停(防盲开)。
       返回 (暂停?, 波动幅度|None, 原因)。"""
    mc = _fin(match_count); bd = _fin(band)
    if bd is None or bd <= 0 or mc is None or mc < 2:
        return False, None, "off"
    mc = int(round(mc))
    vals = [_fin(x) for x in (recent_spreads or [])]
    vals = [v for v in vals if v is not None]
    if len(vals) < mc:
        return True, None, "insufficient_data(%d<%d)" % (len(vals), mc)
    window = vals[-mc:]
    amp = round(max(window) - min(window), 5)
    if amp > bd:
        return True, amp, "fluctuation_too_wide(%.5f>%.2f)" % (amp, bd)
    return False, amp, "ok"


# ---------------- 3) 单腿守卫 (按 MT↔MT 配对重写) ----------------
# testgo 是 MT5↔加密所；这里两腿都是 MT。判定：配对应两腿都有持仓，否则单腿暴露。
def single_leg_check(pair, min_lot=0.001, min_gap_lot=0.01, ratio=1.0):
    """pair: {main_lots, hedge_lots, main_order, hedge_order}
       ratio = 对冲/主 手数比 (hedge_lot_mult/main_lot_mult)。第二批起手数倍率真正参与
       平衡判定：平衡态 hedge≈main*ratio，缺口用比例校正 |hedge - main*ratio|，
       非 1:1 对冲比下不再误判单腿。ratio 非法→保守回落 1:1（绝不放大误判）。
       返回 (是否单腿, 缺口手数, 缺哪条腿)。碎单地板过滤(testgo 噪音过滤教训)"""
    m = float(pair.get("main_lots", 0) or 0)
    h = float(pair.get("hedge_lots", 0) or 0)
    rr = _fin(ratio)
    if rr is None or rr <= 0:
        rr = 1.0
    expected_h = m * rr
    gap = round(abs(h - expected_h), 4)
    # 两腿都极小 = 已平/无持仓，非单腿
    if m < min_lot and h < min_lot:
        return False, 0.0, None
    # 一腿有一腿无（地板过滤碎单/残留偏移）
    if m >= min_lot and h < min_lot and m >= min_gap_lot:
        return True, m, "hedge_missing"
    if h >= min_lot and m < min_lot and h >= min_gap_lot:
        return True, h, "main_missing"
    # 两腿都有但(比例校正后)手数不齐
    if gap >= min_gap_lot:
        return True, gap, "lots_mismatch"
    return False, gap, None

# ---------------- 4) PnL 逐笔口径 (按配对：两腿合计) ----------------
def pair_pnl(main_deals, hedge_deals):
    """逐笔口径：主腿+对冲腿 的 profit+swap+commission 合计（净额）。
       testgo income_deals_based 思路，但锁仓对是两腿相加。"""
    def leg_sum(deals):
        return sum(float(d.get("profit",0) or 0)+float(d.get("swap",0) or 0)
                   +float(d.get("commission",0) or 0) for d in (deals or []) if d.get("is_trade",True))
    m = leg_sum(main_deals); h = leg_sum(hedge_deals)
    return {"main_pnl": round(m,2), "hedge_pnl": round(h,2), "net_pnl": round(m+h,2)}

# ---------------- 阶梯定位 (复用 testgo 顺序填充：按持仓段严格定位) ----------------
def ladder_slot(current_lots, ladders, lot_step):
    """按当前持仓严格定位下一阶梯（不跳阶）。返回应入场的阶梯序号(1..ladders)或None(满)"""
    filled = int(round(current_lots / lot_step)) if lot_step else 0
    if filled >= ladders:
        return None
    return filled + 1

# ============================================================================
#  第一批护栏 (移植 testgo, 对抗式审查后全 fail-closed 加固, 23 单测通过)
# ============================================================================
import math as _math
def _fin(x):
    try:
        v=float(x); return v if _math.isfinite(v) else None
    except (TypeError,ValueError): return None

def slippage_guard(expected, filled, slippage_tol, point, is_pending=False, slippage_pause_min=2, side=None):
    try: pm=int(float(slippage_pause_min)); pm=pm if pm>0 else 2
    except (TypeError,ValueError): pm=2
    ex=_fin(expected); fi=_fin(filled); tol=_fin(slippage_tol); pt=_fin(point)
    if is_pending:
        if ex is None or fi is None or tol is None or pt is None or pt<=0 or fi<=0:
            return False,None,"ok"
    else:
        if pt is None or pt<=0: return True,None,"pause_invalid"
        if fi is None or fi<=0 or ex is None: return True,None,"pause_invalid"
        if tol is None or tol<0: return True,None,"pause_invalid"
    raw=abs(fi-ex)/pt; slip_pts=round(raw,1)
    adverse=True
    if side in ("buy","sell"):
        adverse = (fi>ex) if side=="buy" else (fi<ex)
    over=(raw>tol) and adverse
    if not over: return False,slip_pts,"ok"
    return (True,slip_pts,"cancel") if is_pending else (True,slip_pts,"pause:%dmin"%pm)

def divergence_guard(mb,ma,hb,ha,main_cap,hedge_cap,trip_thr=0.7,recover_thr=0.3,prev_tripped=False,basis_offset=0.0):
    vals=[_fin(mb),_fin(ma),_fin(hb),_fin(ha)]
    if any(v is None for v in vals): return True,None,None,"quote_invalid"
    mb,ma,hb,ha=vals
    if min(mb,ma,hb,ha)<=0: return True,None,None,"quote_nonpositive"
    if ma<mb or ha<hb: return True,None,None,"crossed_quote"
    main_spread=round(ma-mb,5); hedge_spread=round(ha-hb,5)
    mc=_fin(main_cap); hc=_fin(hedge_cap)
    if mc is not None and mc<0: return True,main_spread,hedge_spread,"bad_config"
    if hc is not None and hc<0: return True,main_spread,hedge_spread,"bad_config"
    if mc is not None and main_spread>mc: return True,main_spread,hedge_spread,"main_spread_cap(%.5f>%.2f)"%(main_spread,mc)
    if hc is not None and hedge_spread>hc: return True,main_spread,hedge_spread,"hedge_spread_cap(%.5f>%.2f)"%(hedge_spread,hc)
    trip=_fin(trip_thr); rec=_fin(recover_thr); bo=_fin(basis_offset) or 0.0
    if trip is None: return False,main_spread,hedge_spread,"ok"
    if rec is None or rec>trip: rec=min(rec,trip) if rec is not None else trip
    mid_main=(ma+mb)/2.0; mid_hedge=(ha+hb)/2.0
    divergence=abs(mid_main-mid_hedge-bo)
    if prev_tripped:
        if divergence>rec: return True,main_spread,hedge_spread,"still_diverged(%.5f>recover%.2f)"%(divergence,rec)
        return False,main_spread,hedge_spread,"recovered"
    if divergence>trip: return True,main_spread,hedge_spread,"diverged(%.5f>trip%.2f)"%(divergence,trip)
    return False,main_spread,hedge_spread,"ok"

def entry_throttle(last_entry_ts,now_ts,entry_interval_sec,inflight_count=0,max_inflight=3):
    if inflight_count is None or (isinstance(inflight_count,str) and inflight_count.strip()==""):
        ic=0
    else:
        icf=_fin(inflight_count)
        if icf is None: return False,None,0.0,"inflight_unknown"
        ic=int(round(icf))
    mi=_fin(max_inflight); mi=1 if mi is None else int(round(mi))
    if mi<=0: return False,None,0.0,"max_inflight_misconfig"
    if ic>=mi: return False,None,0.0,"inflight_full(%d>=%d)"%(ic,mi)
    iv=_fin(entry_interval_sec)
    if iv is None or iv<0: return False,None,0.0,"bad_interval"
    if iv==0: return True,None,0.0,"no_interval_limit"
    nt=_fin(now_ts)
    if nt is None: return False,None,0.0,"now_ts_invalid"
    lt=_fin(last_entry_ts)
    if lt is None: return False,None,0.0,"last_ts_invalid"
    if lt>nt+60: return True,None,0.0,"stale_future_ts_reset"
    elapsed=nt-lt
    if elapsed<0: return False,None,0.0,"clock_backwards"
    if elapsed>=iv: return True,round(elapsed,3),0.0,"ok"
    return False,round(elapsed,3),round(iv-elapsed,3),"interval_wait(%.1f<%.0f)"%(elapsed,iv)

def tp_sl_check(net_pnl_points, tp_points, sl_points):
    pnl=_fin(net_pnl_points)
    if pnl is None: return "hold","pnl_unknown"
    tp=_fin(tp_points); sl=_fin(sl_points)
    if sl is not None and sl>0 and pnl <= -abs(sl):
        return "stop_loss","触发止损(%.1f<=-%.1f)"%(pnl,abs(sl))
    if tp is not None and tp>0 and pnl >= tp:
        return "take_profit","触发止盈(%.1f>=%.1f)"%(pnl,tp)
    return "hold","ok"

# ============================================================================
#  全自动出场 (逐对盈亏 + 逐坑出场判定; 纯函数, 只给"该不该平"建议, 真实平仓由带锁的循环执行)
# ============================================================================
def pair_pnl_live(main_pos, hedge_pos):
    """单个坑(配对)的实时净盈亏 = 主腿(profit+swap) + 对冲腿(profit+swap)。
       任一腿缺 → 用现有腿(残腿也算, 便于超时/止损覆盖)。返回 (净盈亏, 主盈亏, 对冲盈亏)。"""
    def _leg(p):
        if not p: return 0.0
        return float(p.get("profit",0) or 0)+float(p.get("swap",0) or 0)
    m=_leg(main_pos); h=_leg(hedge_pos)
    return round(m+h,2), round(m,2), round(h,2)

def auto_exit_decision(pair_net_pnl, cur_spread, hold_secs_elapsed,
                       tp_points, sl_points, hold_secs,
                       sell_point=0.0, exit_enabled=False, profit_first=False):
    """逐坑出场判定(优先级: 止损 > 卖出点位到点 > 止盈 > 超时)。
       pair_net_pnl=该坑净盈亏($, 逐对口径); cur_spread=该坑当前点差; hold_secs_elapsed=已持仓秒。
       sell_point>0 且 exit_enabled → 点差≤目标即平(套利收敛出场)。
       profit_first=True 时, 止盈/卖点/超时 仅在净盈亏>0 才放行; 止损永远放行(风控不可关)。
       返回 (是否平?, 原因)。全 fail-safe: 无效输入不误平。"""
    pnl=_fin(pair_net_pnl)
    # 1) 止损(最高优先, 不受 profit_first 限制)
    sl=_fin(sl_points)
    if pnl is not None and sl is not None and sl>0 and pnl <= -abs(sl):
        return True, "stop_loss(净%.2f<=-%.1f)"%(pnl,abs(sl))
    pos_ok = (pnl is not None and pnl>0)
    def _gated():  # profit_first 开时需盈利才放行
        return (not profit_first) or pos_ok
    # 2) 卖出点位到点(套利收敛: 当前点差降到目标)
    sp=_fin(sell_point); cs=_fin(cur_spread)
    if exit_enabled and sp is not None and sp>0 and cs is not None and cs<=sp and _gated():
        return True, "sell_point到点(点差%.4f<=%.2f)"%(cs,sp)
    # 3) 止盈
    tp=_fin(tp_points)
    if pnl is not None and tp is not None and tp>0 and pnl >= tp and _gated():
        return True, "take_profit(净%.2f>=%.1f)"%(pnl,tp)
    # 4) 超时(持仓时间到)
    hs=_fin(hold_secs); el=_fin(hold_secs_elapsed)
    if hs is not None and hs>0 and el is not None and el>=hs and _gated():
        return True, "hold_timeout(持仓%.0fs>=%.0fs)"%(el,hs)
    return False, "hold"


# ============================================================================
#  第二批：手数倍率参与下单量计算 + 品种映射 (纯函数, fail-safe, 不触发任何真实下单)
# ============================================================================
def map_hedge_symbol(main_symbol, hedge_symbol=None):
    """对冲腿符号解析：配了 hedge_symbol 用之(主≠对冲符号转换, 如 XAUUSD→XAUUSD.m)，
       否则回落主品种。去首尾空白；两者皆空返回空串(上游不会用空串拉行情)。"""
    hs = (hedge_symbol or "").strip()
    if hs:
        return hs
    return (main_symbol or "").strip()

def order_lots(base_lot, main_mult=1.0, hedge_mult=1.0, rungs=1):
    """每U手数(base_lot) × 腿倍率 → 下单量。主腿=base×主倍率, 对冲腿=base×对冲倍率。
       rungs=已/将填充阶梯数(累计目标手数)。
       fail-safe: base 非法/<=0 → 全 0 手(绝不以未知量下单)；倍率<0/非有限→回落 1.0。
       返回 {per_rung_main, per_rung_hedge, main_lots, hedge_lots, ratio, reason}。"""
    b = _fin(base_lot)
    if b is None or b <= 0:
        return {"per_rung_main":0.0,"per_rung_hedge":0.0,"main_lots":0.0,
                "hedge_lots":0.0,"ratio":None,"reason":"base_lot_invalid"}
    mm = _fin(main_mult);  mm = 1.0 if (mm is None or mm < 0) else mm
    hm = _fin(hedge_mult); hm = 1.0 if (hm is None or hm < 0) else hm
    n = _fin(rungs)
    n = 1 if (n is None or n < 1) else int(round(n))
    per_m = round(b * mm, 2); per_h = round(b * hm, 2)
    ratio = round(hm / mm, 4) if mm > 0 else None
    return {"per_rung_main":per_m,"per_rung_hedge":per_h,
            "main_lots":round(per_m * n, 2),"hedge_lots":round(per_h * n, 2),
            "ratio":ratio,"reason":"ok"}

# ---------------- 保证金预留闸 (开仓前查可用保证金须 >= 预留) ----------------
def margin_sufficient(free_margin, reserve, leg="main"):
    """free_margin=账户可用保证金(margin_free); reserve=预留下限。
       可用 < 预留 → 拒绝(留足风险垫,防爆仓)。reserve<=0 视为不限。
       fail-closed: free 无效 → 拒绝(读不到余额不盲开)。返回 (够?, 原因)。"""
    rv = _fin(reserve)
    if rv is None or rv <= 0:
        return True, "no_reserve"
    fm = _fin(free_margin)
    if fm is None:
        return False, "%s_free_unknown" % leg
    if fm < rv:
        return False, "%s_margin_below_reserve(%.2f<%.2f)" % (leg, fm, rv)
    return True, "ok"

# ---------------- 费用并入点差阈值 (每手费用折算成点, 收紧入场阈值) ----------------
def effective_spread_threshold(entry_spread_thr, fee_per_lot, point_value_per_lot, legs=2):
    """开仓阈值收紧: 有效阈值 = 名义阈值 − 费用折算点数。
       fee_per_lot=每手费用($); point_value_per_lot=每手每点价值($/点); legs=计费腿数(双腿=2)。
       费用越高→可接受点差越小(更严)。无效/缺省→回落原阈值(不动)。返回 (有效阈值, 费用点数)。"""
    thr = _fin(entry_spread_thr)
    if thr is None:
        return entry_spread_thr, 0.0
    fee = _fin(fee_per_lot); pv = _fin(point_value_per_lot)
    if fee is None or fee <= 0 or pv is None or pv <= 0:
        return round(thr, 5), 0.0
    lg = _fin(legs); lg = 2 if (lg is None or lg < 1) else lg
    fee_points = (fee * lg) / pv          # 双腿总费用折算成点
    eff = thr - fee_points
    if eff < 0: eff = 0.0                  # 阈值不为负(费用超过名义阈值→几乎不可入场)
    return round(eff, 5), round(fee_points, 5)

# ---------------- 强平价估算 (MT5 无原生逐仓强平价, 账户级按 margin_level<=so_so 反推) ----------------
def liq_estimate(equity, margin, so_so, net_lots, price, contract_size=100.0, so_mode=0):
    """账户级强平价【估算】(非交易所原生值)。
       原理: MT5 在 保证金率(equity/margin*100) ≤ 止损平仓线 so_so% 时强平。
       net_lots>0=账户净多, <0=净空, 0=无方向。仅对账户净方向给该方向强平价, 反向 None。
       so_mode: 0=百分比(so_so 为 %) 1=货币(so_so 为金额)。
       fail-closed: 任一输入非法/margin<=0/无净仓/缓冲<=0 → 该向 None(不臆造)。
       返回 {long, short, est:True, reason}。"""
    eq=_fin(equity); mg=_fin(margin); ss=_fin(so_so); nl=_fin(net_lots); px=_fin(price); cs=_fin(contract_size)
    out={"long":None,"short":None,"est":True,"reason":"ok"}
    if eq is None or mg is None or px is None or nl is None or cs is None or cs<=0:
        out["reason"]="input_invalid"; return out
    if mg<=0:
        out["reason"]="no_margin(无持仓或保证金为0)"; return out
    if abs(nl) < 1e-9:
        out["reason"]="flat(无净方向)"; return out
    # 止损平仓线对应的净值线
    if so_mode==1:
        stop_money = ss if ss is not None else 0.0
    else:
        ss = ss if ss is not None else 50.0   # 默认 50%
        stop_money = (ss/100.0)*mg
    buffer = eq - stop_money                   # 还能亏多少净值才触发强平
    if buffer <= 0:
        out["reason"]="already_below_stopout(已逼近/低于止损线)"; return out
    move = buffer/(abs(nl)*cs)                 # 可承受的价格反向移动
    if nl > 0:    # 净多: 价跌触发
        out["long"]=round(px - move, 2)
    else:         # 净空: 价涨触发
        out["short"]=round(px + move, 2)
    return out
