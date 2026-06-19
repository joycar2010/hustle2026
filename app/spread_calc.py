"""CrossArb 净基差核心算法(P0 的灵魂)。

策略方向(规格定义):在 DEX 大池【买入】base(做多现货)+ 在币安【做空】永续。
只有当 DEX 价 < 币安合约价(即 DEX 更便宜)时才是机会。

各项口径(全部以 bps = 万分之一 表示):
- gross_bps      原始基差 = (fut_bid - dex_eff_price) / dex_eff_price * 1e4
                 fut_bid:做空腿卖入买一价;dex_eff_price:已含 DEX 费+滑点的真实买价。
                 注意:DEX【入场】费+滑点已内含在 dex_eff_price 里,故已计入 gross。
- taker_bps      币安合约单边 taker 费。
- gas_bps        一次链上 swap 的 gas 成本(L2执行+实时L1)/ 名义额。gas_usd 由上层
                 用 ETH/USD(非本市场 base 价)折算后传入,避免 BTC/VIRTUAL 市场折错。
- exit_dex_bps   现货卖回 DEX 的【退出】池费+价格冲击,用入场滑点对称近似。
- recycle_bps    资金回收(跨链桥/提币)摊销成本,默认 0,可配。

两个净值:
- net_entry_bps   入场净基差 = gross - taker - gas - recycle(仅信息参考,易高估)。
- net_bps         【往返净基差,主指标,驱动 is_opportunity】
                  = gross - 2*taker(开+平) - 2*gas(入场+退出两次 swap)
                    - exit_dex_bps(现货卖回) - recycle
                  这才是"真正能兑现的利润"口径。资金费为持仓期另算现金流,不在此。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class SpreadResult:
    market: str
    binance_symbol: str
    ts: int
    base_price: float         # base 参考价(DEX 中间价 ≈ USD)
    dex_eff_price: float      # DEX 真实买价(含费+滑点)
    dex_mid_price: float
    fut_bid: float
    fut_ask: float
    notional_usd: float
    base_out: float
    slippage_bps: float       # DEX 本笔隐含滑点(含池费)
    gas_usd: float            # 一次 swap 的 gas(L2+L1)
    gross_bps: float
    taker_bps: float
    gas_bps: float
    exit_dex_bps: float
    recycle_bps: float
    net_entry_bps: float
    net_bps: float            # 往返净基差(主指标)
    is_opportunity: bool

    def as_dict(self) -> dict:
        return asdict(self)


def compute_spread(
    *,
    market: str,
    binance_symbol: str,
    ts: int,
    dex_eff_price: float,
    dex_mid_price: float,
    base_out: float,
    slippage_bps: float,
    gas_usd: float,
    fut_bid: float,
    fut_ask: float,
    notional_usd: float,
    taker_fee_bps: float,
    recycle_bps: float,
    min_net_bps: float,
) -> SpreadResult:
    base_price = dex_mid_price if dex_mid_price > 0 else dex_eff_price

    gross_bps = (fut_bid - dex_eff_price) / dex_eff_price * 1e4
    gas_bps = gas_usd / notional_usd * 1e4 if notional_usd > 0 else 0.0
    exit_dex_bps = max(slippage_bps, 0.0)

    net_entry_bps = gross_bps - taker_fee_bps - gas_bps - recycle_bps
    net_bps = gross_bps - 2 * taker_fee_bps - 2 * gas_bps - exit_dex_bps - recycle_bps

    return SpreadResult(
        market=market,
        binance_symbol=binance_symbol,
        ts=ts,
        base_price=round(base_price, 6),
        dex_eff_price=round(dex_eff_price, 6),
        dex_mid_price=round(dex_mid_price, 6),
        fut_bid=fut_bid,
        fut_ask=fut_ask,
        notional_usd=notional_usd,
        base_out=round(base_out, 8),
        slippage_bps=round(slippage_bps, 3),
        gas_usd=round(gas_usd, 5),
        gross_bps=round(gross_bps, 3),
        taker_bps=taker_fee_bps,
        gas_bps=round(gas_bps, 4),
        exit_dex_bps=round(exit_dex_bps, 3),
        recycle_bps=recycle_bps,
        net_entry_bps=round(net_entry_bps, 3),
        net_bps=round(net_bps, 3),
        is_opportunity=net_bps > min_net_bps,
    )
