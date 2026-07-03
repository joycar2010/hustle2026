"""CEX-DEX 价差存活窗口测量器 —— P0 只读(不下单/不签名/不碰真金)。

回答:DEX-CEX + MEV 对"轮询型后来者"有没有空间?
核心问题不是"有没有价差",而是"当价差因波动张开到>成本时,这缝隙能存活多久"。
- 若缝隙秒内(<1-2区块)闭合 → 被专业玩家(co-lo+mempool+builder)同块吃掉,轮询型碰不到 → KILL
- 若缝隙能存活数秒/数区块 → 意外有空间,值得深究

方法:
1. 每 ~1s 同时取 币安BNB现货中间价 + Pancake WBNB/USDT 池价
2. 算价差bps。|价差|>ENTER_BPS(成本线) 记一个"缝隙",记下时间戳+价差+区块
3. 每个缝隙持续跟踪:直到 |价差|回落到<EXIT_BPS(闭合)。记录存活秒数+存活区块数
4. 聚合:缝隙频率 / 存活时间分布 / >成本缝隙的可捕获性

纯 eth_call + 币安公共 REST 只读。用法: python3 -m app.cexdex_shadow
"""
from __future__ import annotations

import csv
import json
import os
import time
import threading
import urllib.request

from .chain_rpc import ChainRpc

BSC_RPC = "https://bsc-dataseed.binance.org"
PANCAKE_WBNB_USDT = "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"
WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
CEX_SYMBOL = "BNBUSDT"

ROUNDTRIP_COST_BPS = 38.0   # DEX手续费25 + CEX taker~7.5 + gas ~ 一次往返成本
ENTER_BPS = ROUNDTRIP_COST_BPS   # |价差|>此值 = 张开一个"理论可套缝隙"
EXIT_BPS = ROUNDTRIP_COST_BPS * 0.5   # 回落到此值以下 = 缝隙闭合
POLL_SEC = 1.0
LOG = "./data/cexdex_shadow.csv"
COLS = ["open_ts", "close_ts", "open_block", "close_block", "peak_bps", "open_bps",
        "survive_sec", "survive_blocks", "samples_over", "outcome"]


class CexDexShadow(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.rpc = ChainRpc(BSC_RPC, 56, timeout=8)
        self._stop = threading.Event()
        self._gap = None          # 当前张开的缝隙(dict)或 None
        self._t0_token0 = None
        self._samples = 0
        self._over_samples = 0    # |价差|>ENTER 的累计采样(算张开占比)
        self._init_log()

    def _init_log(self):
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        if not os.path.exists(LOG) or os.path.getsize(LOG) == 0:
            with open(LOG, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(COLS)

    def _log(self, row: dict):
        with open(LOG, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([row.get(c, "") for c in COLS])

    def _dex_price(self) -> float:
        r = self.rpc.call(PANCAKE_WBNB_USDT, "0x0902f1ac")
        r0 = int(r[2:66], 16); r1 = int(r[66:130], 16)
        if self._t0_token0 is None:
            self._t0_token0 = ("0x" + self.rpc.call(PANCAKE_WBNB_USDT, "0x0dfe1681")[26:66]).lower()
        # USDT储备/WBNB储备 = WBNB价
        return (r0 / r1) if self._t0_token0 != WBNB else (r1 / r0)

    def _cex_price(self) -> float:
        d = json.load(urllib.request.urlopen(
            f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={CEX_SYMBOL}", timeout=5))
        return (float(d["bidPrice"]) + float(d["askPrice"])) / 2

    def _block(self) -> int:
        return int(self.rpc._call("eth_blockNumber", []), 16)

    def run(self):
        print(f"[cexdex] CEX-DEX 价差存活测量启动 | 张开>{ENTER_BPS}bps 闭合<{EXIT_BPS}bps | poll {POLL_SEC}s")
        last_stat = time.time()
        while not self._stop.is_set():
            t = time.time()
            try:
                c = self._cex_price(); dx = self._dex_price()
                blk = self._block()
                diff = abs((dx - c) / c * 1e4)
                self._samples += 1
                if diff > ENTER_BPS:
                    self._over_samples += 1
                    if self._gap is None:
                        # 新缝隙张开
                        self._gap = {"open_ts": int(t * 1000), "open_block": blk,
                                     "open_bps": round(diff, 1), "peak_bps": diff,
                                     "samples_over": 1}
                        print(f"[缝隙张开] {diff:.1f}bps @blk{blk}")
                    else:
                        self._gap["peak_bps"] = max(self._gap["peak_bps"], diff)
                        self._gap["samples_over"] += 1
                elif self._gap is not None and diff < EXIT_BPS:
                    # 缝隙闭合
                    g = self._gap
                    surv_sec = (int(t * 1000) - g["open_ts"]) / 1000
                    surv_blk = blk - g["open_block"]
                    # 存活判定:能撑过≥2区块(~6s BSC)=轮询型有机会;秒内闭合=被抢
                    outcome = "SURVIVED" if surv_blk >= 2 else "SNIPED"
                    self._log({**g, "close_ts": int(t * 1000), "close_block": blk,
                               "peak_bps": round(g["peak_bps"], 1),
                               "survive_sec": round(surv_sec, 1), "survive_blocks": surv_blk,
                               "outcome": outcome})
                    print(f"[缝隙闭合] peak{g['peak_bps']:.0f}bps 存活{surv_sec:.1f}s/{surv_blk}块 {outcome}")
                    self._gap = None
                # 每 5 分钟打一次张开占比统计
                if t - last_stat > 300:
                    pct = self._over_samples / self._samples * 100 if self._samples else 0
                    print(f"[stat] {self._samples}采样 张开占比{pct:.2f}%")
                    last_stat = t
            except Exception as e:  # noqa: BLE001
                pass
            self._stop.wait(max(0.0, POLL_SEC - (time.time() - t)))

    def stop(self):
        self._stop.set()


def main():
    s = CexDexShadow()
    s.start()
    try:
        while s.is_alive():
            s.join(1)
    except KeyboardInterrupt:
        s.stop()


if __name__ == "__main__":
    main()
