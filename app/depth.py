"""池深度探测(spec 3.3 / 5.1 第4步:估算当前流动性下可执行最大交易量 + 不造成严重滑点)。

不抄"TVL > X 百万"这种静态门槛——直接【测量】:沿名义额阶梯报价,找出
滑点 ≤ 容忍线(默认30bps)的最大可执行额。这才是"能安全吃多大单"的真实答案。
源无关:univ3 和 agg 市场都用同一个 quote_buy(m, notional) 跑阶梯。
深度变化慢,采集器每拍只轮转探测 1 个市场,避免打爆 RPC/聚合器限频。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DepthResult:
    market: str
    max_exec_usd: float       # 滑点≤容忍线的最大可执行名义额(USD)
    slip_tol_bps: float       # 容忍线
    ladder: list              # [(notional, slippage_bps), ...] 实测阶梯(供看板/审计)
    ts: int


def probe_depth(quote_buy, m, ladder_usd, slip_tol_bps: float, ts: int) -> DepthResult:
    """quote_buy: 取 (market, notional)->DexQuote 的可调用(univ3 或 agg 源的 quote_buy)。
    沿 ladder 逐档报价,记录每档滑点;max_exec = 滑点首次超过容忍线之前的最大额。"""
    ladder = []
    max_exec = 0.0
    for notional in ladder_usd:
        try:
            q = quote_buy(m, notional)
            slip = max(q.slippage_bps, 0.0)
        except Exception:  # noqa: BLE001
            break  # 该档报价失败(可能超池容量),停止上探
        ladder.append((notional, round(slip, 2)))
        if slip <= slip_tol_bps:
            max_exec = notional
        else:
            break  # 滑点超线,更大额只会更差,停止
    return DepthResult(market=m.key, max_exec_usd=max_exec, slip_tol_bps=slip_tol_bps,
                       ladder=ladder, ts=ts)
