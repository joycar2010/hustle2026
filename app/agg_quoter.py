"""聚合器买入腿报价(KyberSwap,免key)—— 只读,绝不发交易。

为什么用聚合器:那批 Base 波动币的深流动性在 Slipstream CL 的 token/WETH 池里,
需要跨源+多跳最优路由。聚合器天生做这件事,一次调用即给【真实可成交价】+成本+gas,
比手写三套 DEX quoter + tick 数学省太多,且就是实盘会用的成交价。

routeSummary 字段:amountOut(到手币量)、amountInUsd/amountOutUsd(算买入总成本=费+冲击)、
gasUsd(真实L1+L2 gas)。返回与 UniV3 源同构的 DexQuote。
"""
from __future__ import annotations

import time

import requests

from .dex_quoter import DexQuote
from .markets import Market

KYBER_URL = "https://aggregator-api.kyberswap.com/base/api/v1/routes"


class AggQuoter:
    def __init__(self, client_id: str = "crossarb"):
        self._s = requests.Session()
        self._s.headers.update({
            "accept": "application/json",
            "User-Agent": "crossarb/1.0",
            "x-client-id": client_id or "crossarb",
        })
        # 连接池 >= 最大并发,避免跨线程争用
        ad = requests.adapters.HTTPAdapter(pool_maxsize=16)
        self._s.mount("https://", ad)

    def _route(self, token_in: str, token_out: str, amount_in: int) -> dict:
        # 收紧 timeout/重试,使单市场最坏耗时 < 轮询节拍,避免拖出采样空洞
        last = None
        for i in range(2):
            try:
                r = self._s.get(KYBER_URL, params={"tokenIn": token_in, "tokenOut": token_out,
                                                    "amountIn": str(amount_in)}, timeout=6)
                r.raise_for_status()
                d = r.json()
                if d.get("code") != 0:
                    raise RuntimeError(f"kyber code={d.get('code')} {d.get('message')}")
                return d.get("data", {}).get("routeSummary", {})
            except Exception as e:  # noqa: BLE001
                last = e
                if i < 1:
                    time.sleep(0.4)
        raise last

    def quote_buy(self, m: Market, notional_usd: float) -> DexQuote:
        """USDC -> base 经聚合器最优路由。eff/slippage/gas 全来自一次报价。"""
        amt = int(round(notional_usd * (10 ** m.quote_decimals)))
        rs = self._route(m.quote_token, m.base_token, amt)
        out = int(rs.get("amountOut", 0))
        if out <= 0:
            raise RuntimeError(f"{m.key}: kyber amountOut=0")
        base_out = out / (10 ** m.base_decimals)
        eff = notional_usd / base_out  # quote(USDC) per base,真实可成交价
        # 买入总成本(费+价格冲击)= (投入USD - 到手USD)/投入USD;作 mid 与 exit 对称成本
        in_usd = float(rs.get("amountInUsd") or 0)
        out_usd = float(rs.get("amountOutUsd") or 0)
        if in_usd > 0 and out_usd > 0:
            slip = max((in_usd - out_usd) / in_usd, 0.0)
            mid = eff / (1 + slip) if slip > 0 else eff
        else:
            # KyberSwap 缺 USD 定价(薄长尾币常见):绝不把退出成本当 0(会虚高 net、误报机会),
            # 改用一笔小额($25)报价反推 mid → 真实滑点;再失败则丢弃该拍(记 error,不出假数)。
            small = int(round(25 * (10 ** m.quote_decimals)))
            rs2 = self._route(m.quote_token, m.base_token, small)
            o2 = int(rs2.get("amountOut", 0))
            if o2 <= 0:
                raise RuntimeError(f"{m.key}: kyber 无USD定价且小额报价失败,丢弃该拍")
            mid = 25 / (o2 / (10 ** m.base_decimals))
            slip = max((eff - mid) / mid, 0.0) if mid > 0 else 0.0
        slippage_bps = slip * 1e4
        return DexQuote(eff_price=eff, mid_price=mid, base_out=base_out,
                        slippage_bps=slippage_bps, pool="kyberswap")
