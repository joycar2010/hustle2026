"""CEX-DEX 价差存活窗口测量器 —— P0 只读(不下单/不签名/不碰真金)。

加固版(2026-07-05):多交易对(WBNB/ETH/BTCB) × 多DEX池(Pancake主+Biswap+Apeswap取最优) ×
双门槛(38bps=你的散户成本线 / 25bps=专业玩家视角)。回答:DEX-CEX+MEV 对轮询型后来者有没有空间?

核心问题不是"有没有价差",而是"缝隙张开>成本后能存活多久":
- 秒内(<2区块)闭合 → 被专业玩家(co-lo+mempool+builder)同块吃掉,轮询碰不到 → KILL
- 撑过数秒/数区块 → 或有空间,值得深究

方法:每~1s 取 币安现货中间价 + 各对DEX最优池价,算|价差|bps;>门槛记缝隙,跟踪到回落<门槛/2闭合,
记存活秒/块 + 峰值。多对独立跟踪。纯 eth_call + 币安公共REST 只读。
用法: python3 -m app.cexdex_shadow
"""
from __future__ import annotations

import csv
import json
import os
import time
import threading
import urllib.request

from .chain_rpc import ChainRpc, _enc_addr

BSC_RPC = "https://bsc-dataseed.binance.org"
USDT = "0x55d398326f99059ff775485246999027b3197955"

# 各对: CEX符号 + base代币地址. DEX池经工厂查Pancake/Biswap/Apeswap取最优价
PAIRS = [
    {"key": "BNB", "cex": "BNBUSDT", "base": "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"},
    {"key": "ETH", "cex": "ETHUSDT", "base": "0x2170ed0880ac9a755fd29b2688956bd959f933f8"},
    {"key": "BTC", "cex": "BTCUSDT", "base": "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c"},  # BTCB
]
FACTORIES = [
    {"name": "Pancake", "addr": "0xca143ce32fe78f1f7019d7d551a6402fc5350c73"},
    {"name": "Biswap",  "addr": "0x858e3312ed3a876947ea49d572a7c42de08af7ee"},
    {"name": "Apeswap", "addr": "0x0841bd0b734e4f5853f0dd8d7ea041c241fb0da6"},
]

# 双门槛: 你的散户往返成本 vs 专业玩家(做市费率+co-lo)成本. 缝隙>门槛=对该视角有肉
COST_RETAIL = 38.0    # 散户: DEX25 + CEX taker7.5 + gas
COST_PRO = 25.0       # 专业: DEX25 但CEX maker~0 + 快速通道(乐观下界,看专业玩家钉宽在哪)
DEAD_POOL_BPS = 100.0 # 池对CEX偏离>此值=脱锚僵尸池(流动性枯竭),剔除不参与缝隙判定
EWMA_ALPHA = 0.002    # 滚动均值权重(~500样本半衰,追踪锚定折价慢漂移,不被瞬时缝隙带偏)
WARMUP_N = 300        # 预热样本数:EWMA收敛前不判缝隙(约5分钟)
POLL_SEC = 1.0
LOG = "./data/cexdex_shadow.csv"
COLS = ["pair", "threshold", "open_ts", "close_ts", "open_block", "close_block",
        "peak_bps", "open_bps", "survive_sec", "survive_blocks", "samples_over", "outcome"]

SEL_GETRESERVES = "0x0902f1ac"
SEL_TOKEN0 = "0x0dfe1681"
SEL_GETPAIR = "0xe6a43905"


class CexDexShadow(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.rpc = ChainRpc(BSC_RPC, 56, timeout=8)
        self._stop = threading.Event()
        self._pools = {}   # pair_key -> [(addr, token0)...]
        self._gaps = {}    # (pair_key, threshold) -> gap dict
        self._samples = 0
        self._over = {"retail": 0, "pro": 0}
        self._ewma = {}    # pair_key -> 结构性锚定折价的滚动均值(EWMA)
        self._warmup = {}  # pair_key -> 已喂样本数(预热期不判缝隙)
        self._init_log()
        self._resolve_pools()

    def _init_log(self):
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        # 旧格式(10列无pair/threshold)不兼容→改名备份重建
        if os.path.exists(LOG) and os.path.getsize(LOG) > 0:
            with open(LOG, encoding="utf-8") as f:
                head = f.readline().strip()
            if not head.startswith("pair,threshold"):
                os.rename(LOG, LOG.replace(".csv", ".v1.csv"))
        if not os.path.exists(LOG) or os.path.getsize(LOG) == 0:
            with open(LOG, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(COLS)

    def _log(self, row: dict):
        with open(LOG, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([row.get(c, "") for c in COLS])

    def _getpair(self, factory, a, b):
        try:
            r = self.rpc.call(factory, SEL_GETPAIR + _enc_addr(a) + _enc_addr(b))
            addr = "0x" + r[26:66]
            return addr if int(addr, 16) != 0 else None
        except Exception:  # noqa: BLE001
            return None

    def _resolve_pools(self):
        for p in PAIRS:
            pools = []
            for fac in FACTORIES:
                addr = self._getpair(fac["addr"], p["base"], USDT)
                if not addr:
                    continue
                try:
                    t0 = ("0x" + self.rpc.call(addr, SEL_TOKEN0)[26:66]).lower()
                    pools.append((addr, t0, p["base"].lower()))
                except Exception:  # noqa: BLE001
                    continue
            if pools:
                self._pools[p["key"]] = pools
                print(f"[cexdex] {p['key']}: {len(pools)}池")

    def _pair_live_dev(self, pair_key, cex_px) -> float | None:
        """返回该对【最优活池对CEX的有符号偏差bps】(取|偏差|最小的活池=最紧跟CEX的主池)。
        修复1(死池): 剔除脱锚僵尸池(|偏离|>DEAD_POOL_BPS)。
        有符号(非绝对值): 供上层去锚——BTCB/ETH是跨链锚定币,对CEX有结构性折价(常态-25bps),
        必须减去滚动均值才是【可套利的瞬时偏离】。取最紧跟CEX的活池(主池),它才是套利腿会用的。"""
        best = None
        for addr, t0, base in self._pools.get(pair_key, []):
            try:
                r = self.rpc.call(addr, SEL_GETRESERVES)
                r0 = int(r[2:66], 16); r1 = int(r[66:130], 16)
                if r0 <= 0 or r1 <= 0:
                    continue
                px = (r1 / r0) if t0 == base else (r0 / r1)
                dev = (px - cex_px) / cex_px * 1e4
                if abs(dev) > DEAD_POOL_BPS:   # 死池,剔除
                    continue
                if best is None or abs(dev) < abs(best):
                    best = dev
            except Exception:  # noqa: BLE001
                continue
        return best

    def _cex_price(self, sym) -> float:
        d = json.load(urllib.request.urlopen(
            f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={sym}", timeout=5))
        return (float(d["bidPrice"]) + float(d["askPrice"])) / 2

    def _block(self) -> int:
        return int(self.rpc._call("eth_blockNumber", []), 16)

    def _track(self, pair_key, thr_name, thr_bps, diff, blk, t):
        key = (pair_key, thr_name)
        g = self._gaps.get(key)
        if diff > thr_bps:
            if g is None:
                self._gaps[key] = {"pair": pair_key, "threshold": thr_name,
                                   "open_ts": int(t * 1000), "open_block": blk,
                                   "open_bps": round(diff, 1), "peak_bps": diff, "samples_over": 1}
                print(f"[缝隙张开] {pair_key}/{thr_name} {diff:.1f}bps @blk{blk}")
            else:
                g["peak_bps"] = max(g["peak_bps"], diff)
                g["samples_over"] += 1
        elif g is not None and diff < thr_bps * 0.5:
            surv_sec = (int(t * 1000) - g["open_ts"]) / 1000
            surv_blk = blk - g["open_block"]
            outcome = "SURVIVED" if surv_blk >= 2 else "SNIPED"
            self._log({**g, "close_ts": int(t * 1000), "close_block": blk,
                       "peak_bps": round(g["peak_bps"], 1),
                       "survive_sec": round(surv_sec, 1), "survive_blocks": surv_blk,
                       "outcome": outcome})
            print(f"[缝隙闭合] {pair_key}/{thr_name} peak{g['peak_bps']:.0f}bps 存活{surv_sec:.1f}s/{surv_blk}块 {outcome}")
            del self._gaps[key]

    def run(self):
        print(f"[cexdex] 加固版启动 | {len(self._pools)}对 | 双门槛 retail>{COST_RETAIL} pro>{COST_PRO}bps | poll{POLL_SEC}s")
        last_stat = time.time()
        while not self._stop.is_set():
            t = time.time()
            try:
                blk = self._block()
                self._samples += 1
                for p in PAIRS:
                    pk = p["key"]
                    if pk not in self._pools:
                        continue
                    c = self._cex_price(p["cex"])
                    dev = self._pair_live_dev(pk, c)   # 有符号偏差(已剔死池)
                    if dev is None:
                        continue
                    # 去锚:更新滚动均值(结构性折价),缝隙=偏离均值的瞬时幅度(才是可套利的)
                    self._ewma[pk] = dev if pk not in self._ewma else \
                        (1 - EWMA_ALPHA) * self._ewma[pk] + EWMA_ALPHA * dev
                    self._warmup[pk] = self._warmup.get(pk, 0) + 1
                    if self._warmup[pk] < WARMUP_N:
                        continue   # 预热期不判缝隙
                    diff = abs(dev - self._ewma[pk])   # 去锚后的瞬时偏离
                    if diff > COST_RETAIL:
                        self._over["retail"] += 1
                    if diff > COST_PRO:
                        self._over["pro"] += 1
                    self._track(pk, "retail", COST_RETAIL, diff, blk, t)
                    self._track(pk, "pro", COST_PRO, diff, blk, t)
                if t - last_stat > 300:
                    s = self._samples
                    print(f"[stat] {s}轮 retail张开{self._over['retail']/max(s,1)*100:.3f}% "
                          f"pro张开{self._over['pro']/max(s,1)*100:.3f}%")
                    last_stat = t
            except Exception:  # noqa: BLE001
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
