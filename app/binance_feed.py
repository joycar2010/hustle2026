"""币安合约只读行情 —— 公共端点,无需 API key。

多市场一次性批量拉【全部】 bookTicker(无 symbol 参数返回数组),按 symbol 索引,
无论监控几个标的,每拍只一次请求,IP 权重恒定。做空腿成交价≈ bid。
实盘/测试网下单腿才需要 key,P0 不涉及。
"""
from __future__ import annotations

import requests


class BinanceFutFeed:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self._s = requests.Session()

    def all_book_tickers(self) -> dict[str, dict]:
        """返回 {symbol: {bid, ask, ts}}(全市场,一次请求)。"""
        r = self._s.get(f"{self.base}/fapi/v1/ticker/bookTicker", timeout=8)
        r.raise_for_status()
        out: dict[str, dict] = {}
        for d in r.json():
            out[d["symbol"]] = {
                "bid": float(d["bidPrice"]),
                "ask": float(d["askPrice"]),
                "ts": int(d.get("time", 0)),
            }
        return out
