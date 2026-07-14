"""跨引擎同币仲裁 · E 值数据契约 v1(coin 借币点差 vs dcm 双永续费差)。

背景:高点差币与高费差币高度重叠(都是长尾),路由互斥从二值"先到先得"升级为
"期望值仲裁"——两个引擎对同一 symbol 各自出价,统一口径 **e_daily_pct:
对名义额的净期望收益,%/天**,仲裁按出价高者分配路由。
本模块只定义契约与换算(数据契约先行);裁决器(decision 层)下一阶段接入。

── 口径归一(命门:两边原生单位不同,必须在发布端换算) ──
coin 借币点差(原生 = E USDT/一次往返):
    引擎 E 闸(engine/trading/order_executor._compute_net_expect)产出
    E(USDT,已含利息/4腿手续费/tick摩擦) + notional_usdt + hold_hours。
    e_daily_pct = E / notional × (24 / max(1, hold_hours)) × 100
    (持有≥1h 下限与币安按小时计息口径一致)
    出价为**事件驱动**:coin 引擎只在真实评估开仓时发布 neteval(60s TTL),
    没有出价 = coin 对该币当下无意愿,carry 无对手即胜——语义正确,勿补假出价。

dcm carry(原生 = 费差 edge %/天 + 引擎全 E bps/HORIZON天):
    advisor 出价(全宇宙覆盖)用扁平成本近似:
    e_daily_pct = edge_daily_pct − CARRY_FLAT_COST_DAILY_PCT
    (4腿×~5bps=20bps 往返费按 HORIZON=5 天摊销 ≈ 0.04%/d;
     引擎侧全 E(含入场价差/冲击)只对已路由币计算,升级点:路由后用引擎 E 覆写)

── 存储契约 ──
Redis hash(A 机总线):
    KEY_COIN_E  = dcm:arb:coin_e    field=统一符号(BTCUSDT)  value=bid JSON
    KEY_CARRY_E = dcm:arb:carry_e   同上
bid JSON: {"v":1, "src":"coin"|"carry", "sym":..., "e_daily_pct":float,
           "raw":{原生口径字段}, "ts":unix秒}
超龄 STALE_SEC 视为无出价(读端过滤);写端每轮全量刷新自己的出价并清理超龄字段。

── 仲裁滞回(裁决器规则,先定契约) ──
挑战者换手条件:e_daily_pct > 现任 × HYST_RATIO 且 绝对领先 ≥ HYST_ABS_PCT。
防两侧估值抖动来回倒仓(倒仓=双边真实往返成本)。
"""
import json
import time

VERSION = 1
KEY_COIN_E = "dcm:arb:coin_e"
KEY_CARRY_E = "dcm:arb:carry_e"
STALE_SEC = 900                 # 出价保鲜期(秒)
HYST_RATIO = 1.2                # 挑战者须超现任 20%
HYST_ABS_PCT = 0.05             # 且绝对领先 ≥0.05%/天
CARRY_FLAT_COST_DAILY_PCT = 0.04  # carry 扁平成本近似(20bps往返/5天)


def coin_daily_net_pct(e_usdt, notional_usdt, hold_hours):
    """coin 借币 E(USDT/往返) → %/天。notional 无效返回 None(不出价)。"""
    n = float(notional_usdt or 0)
    if n <= 0:
        return None
    return float(e_usdt) / n * (24.0 / max(1.0, float(hold_hours or 1))) * 100.0


def carry_daily_net_pct(edge_daily_pct, flat_cost_daily_pct=CARRY_FLAT_COST_DAILY_PCT):
    """carry 费差 edge(%/天) → 净 %/天(扁平成本近似)。"""
    return float(edge_daily_pct) - float(flat_cost_daily_pct)


def o1_signed_cashflow_daily_pct(legs):
    """O1 现金流优化器共享原语(V4.0 §7.3)——逐腿带符号日现金流合计(%/天),**禁 abs(funding)**。
    leg = {side, daily_pct(永续腿,已归一日化%), apr(理财/借息年化%)}
      perp_long  : -daily_pct  (多腿正费率=付出)
      perp_short : +daily_pct  (空腿正费率=收入)
      spot_earn  : +apr/365    (现货腿理财;须真实可存入,调用方保证)
      borrow     : -apr/365    (借息成本)
    2 腿 carry(long 低费率所 + short 高费率所)结果 = hi−lo = edge(与旧口径一致,通用支持借币/理财)。"""
    net = 0.0
    for lg in legs or []:
        side = lg.get("side")
        if side == "perp_long":
            net += -float(lg.get("daily_pct") or 0)
        elif side == "perp_short":
            net += float(lg.get("daily_pct") or 0)
        elif side == "spot_earn":
            net += float(lg.get("apr") or 0) / 365.0
        elif side == "borrow":
            net += -float(lg.get("apr") or 0) / 365.0
    return net


def carry_daily_net_pct_from_engine_e(e_bps, horizon_days):
    """升级口径:引擎全 E(bps, horizon 摊销) → %/天。"""
    return float(e_bps) / 100.0 / max(0.001, float(horizon_days))


def bid(src, sym, e_daily_pct, raw=None, ts=None):
    """构造出价 JSON 串。"""
    return json.dumps({
        "v": VERSION, "src": src, "sym": sym,
        "e_daily_pct": round(float(e_daily_pct), 5),
        "raw": raw or {}, "ts": int(ts or time.time()),
    }, ensure_ascii=False)


def parse_bids(mapping, now=None):
    """hgetall 结果 → {sym: bid_dict},过滤超龄/坏行。"""
    now = now or time.time()
    out = {}
    for sym, s in (mapping or {}).items():
        try:
            b = json.loads(s)
            if now - b.get("ts", 0) <= STALE_SEC and b.get("e_daily_pct") is not None:
                out[sym] = b
        except Exception:
            continue
    return out


def challenger_wins(challenger_pct, incumbent_pct,
                    ratio=HYST_RATIO, abs_pct=HYST_ABS_PCT):
    """滞回裁决:挑战者是否足以换手。"""
    c, i = float(challenger_pct), float(incumbent_pct)
    return c > i * ratio and (c - i) >= abs_pct
