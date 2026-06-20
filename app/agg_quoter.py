"""聚合器买入腿报价(KyberSwap,免key,多链)—— 只读,绝不发交易。

为什么用聚合器:各链波动币深流动性散在不同 DEX(Slipstream CL/Pancake/Uniswap…),
聚合器按链 slug 自动找最优跨源多跳路由,一次调用即给【真实可成交价】+成本+按链真实 gas,
比手写每链每 DEX 的 quoter 省太多,且就是实盘会用的成交价。

按 market.chain 取链配置(slug + 计价稳定币)。routeSummary:amountOut、
amountInUsd/amountOutUsd(算买入总成本=费+冲击)、gasUsd(该链该路由真实 L1+L2 gas)。
"""
from __future__ import annotations

import threading
import time

import requests

from .chains import chain_of
from .dex_quoter import DexQuote
from .markets import Market

KYBER_BASE = "https://aggregator-api.kyberswap.com"


class AggQuoter:
    def __init__(self, client_id: str = "crossarb", min_interval: float = 0.12):
        self._s = requests.Session()
        self._s.headers.update({
            "accept": "application/json",
            "User-Agent": "crossarb/1.0",
            "x-client-id": client_id or "crossarb",
        })
        ad = requests.adapters.HTTPAdapter(pool_maxsize=16)
        self._s.mount("https://", ad)
        # 全局节流:并发线程池会把多市场一齐打向 KyberSwap 公共端点触发 429。
        # 用一把锁 + 最小间隔把请求摊开(~8 req/s),消除突发尖峰。
        self._gate = threading.Lock()
        self._next_at = 0.0
        self._min_interval = min_interval

    def _pace(self):
        with self._gate:
            now = time.time()
            wait = self._next_at - now
            if wait > 0:
                time.sleep(wait)
                now = time.time()
            self._next_at = now + self._min_interval

    def _route(self, slug: str, token_in: str, token_out: str, amount_in: int) -> dict:
        url = f"{KYBER_BASE}/{slug}/api/v1/routes"
        last = None
        tries = 4
        for i in range(tries):
            try:
                self._pace()
                r = self._s.get(url, params={"tokenIn": token_in, "tokenOut": token_out,
                                             "amountIn": str(amount_in)}, timeout=6)
                if r.status_code == 429:
                    # 429 单独处理:撞限频窗口,退避更久(1.5/3/4.5s)再试,而非立刻再撞
                    if i < tries - 1:
                        time.sleep(1.5 * (i + 1))
                    raise RuntimeError("kyber 429 rate-limited")
                r.raise_for_status()
                d = r.json()
                if d.get("code") != 0:
                    raise RuntimeError(f"kyber code={d.get('code')} {d.get('message')}")
                return d.get("data", {}).get("routeSummary", {})
            except RuntimeError as e:
                last = e
                if "429" in str(e):
                    continue  # 已在上面退避过,直接进下一次重试
                if i < tries - 1:
                    time.sleep(0.5 * (i + 1))
            except Exception as e:  # noqa: BLE001
                last = e
                if i < tries - 1:
                    time.sleep(0.5 * (i + 1))
        raise last

    def quote_buy(self, m: Market, notional_usd: float) -> DexQuote:
        """稳定币 -> base 经聚合器最优路由(按 market.chain)。eff/slippage/gas 全来自一次报价。"""
        ch = chain_of(m.chain)
        amt = int(round(notional_usd * (10 ** ch.stable_decimals)))
        rs = self._route(ch.kyber_slug, ch.stable, m.base_token, amt)
        out = int(rs.get("amountOut", 0))
        if out <= 0:
            raise RuntimeError(f"{m.key}: kyber amountOut=0")
        base_out = out / (10 ** m.base_decimals)
        eff = notional_usd / base_out
        in_usd = float(rs.get("amountInUsd") or 0)
        out_usd = float(rs.get("amountOutUsd") or 0)
        if in_usd > 0 and out_usd > 0:
            slip = max((in_usd - out_usd) / in_usd, 0.0)
            mid = eff / (1 + slip) if slip > 0 else eff
        else:
            # 缺 USD 定价:绝不把退出成本当 0(会虚高 net 误报机会),用小额报价反推 mid
            small = int(round(25 * (10 ** ch.stable_decimals)))
            rs2 = self._route(ch.kyber_slug, ch.stable, m.base_token, small)
            o2 = int(rs2.get("amountOut", 0))
            if o2 <= 0:
                raise RuntimeError(f"{m.key}: kyber 无USD定价且小额报价失败,丢弃该拍")
            mid = 25 / (o2 / (10 ** m.base_decimals))
            slip = max((eff - mid) / mid, 0.0) if mid > 0 else 0.0
        slippage_bps = slip * 1e4
        gas_usd = float(rs.get("gasUsd") or 0) or None  # 按链真实 gas;0/缺失则留空走共享
        return DexQuote(eff_price=eff, mid_price=mid, base_out=base_out,
                        slippage_bps=slippage_bps, pool="kyberswap", gas_usd=gas_usd)
