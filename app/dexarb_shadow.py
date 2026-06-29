"""DEX-DEX 同链原子套利 —— P0 只读影子测量器(不写合约/不签名/不碰真金)。

回答唯一关键问题:对"轮询型后来者",BSC DEX-DEX 套利一天能抓到几个
【扣成本为正 且 没被专业搜索者抢跑】的机会?

方法:
1. 每 poll_sec 秒,Multicall/逐池取多个 DEX 同交易对的 getReserves
2. 两两组合算"借A池买→B池卖"双向净利(严格对齐 V2 定价 + 各 DEX 真实手续费)
3. 净利>min_profit_bps 即记一个"理论机会",并记下当前区块
4. 【抢跑判定】N 个区块后回查同两池储备:若价差已塌缩(机会消失)=被别人吃了/自然回归;
   结合该池这 N 块内是否有大额 swap,粗判"是否本可捕获"
5. 全部写 dexarb_shadow.csv,聚合出: 机会频率 / 存活区块数 / 扣成本后净利分布

绝不上链。纯 eth_call 只读 + 历史区块回查。
用法: python3 -m app.dexarb_shadow
"""
from __future__ import annotations

import csv
import os
import time
import threading
from dataclasses import dataclass

from .chain_rpc import ChainRpc, _enc_addr
from .config import cfg

# ---- BSC 常量 ----
BSC_RPC = "https://bsc-dataseed.binance.org"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
USDT = "0x55d398326f99059fF775485246999027B3197955"
USDC = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"
BTCB = "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c"
ETH = "0x2170Ed0880ac9A755fd29B2688956BD959F933F8"
CAKE = "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82"

# 各 DEX V2 工厂 + 手续费(bps,买入端单边)。fee=25→0.25%, biswap=10→0.1%
DEXES = [
    {"name": "Pancake", "factory": "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73", "fee_bps": 25},
    {"name": "Biswap",  "factory": "0x858E3312ed3A876947EA49d572A7C42DE08af7EE", "fee_bps": 10},
    {"name": "Apeswap", "factory": "0x0841BD0B734E4F5853f0dD8d7Ea041c241fb0Da6", "fee_bps": 20},
]

# 测量的交易对(base/quote,quote=USDT)
PAIRS = [
    {"key": "WBNB/USDT", "base": WBNB, "quote": USDT},
    {"key": "ETH/USDT",  "base": ETH,  "quote": USDT},
    {"key": "BTCB/USDT", "base": BTCB, "quote": USDT},
    {"key": "CAKE/USDT", "base": CAKE, "quote": USDT},
    {"key": "USDC/USDT", "base": USDC, "quote": USDT},
]

SEL_GETRESERVES = "0x0902f1ac"
SEL_TOKEN0 = "0x0dfe1681"
SEL_GETPAIR = "0xe6a43905"

NOTIONALS = [1000, 3000, 5000]        # 本金档位($),取最优
MIN_NET_BPS = 5.0                      # 扣成本后净利>此值记为"理论机会"(放低门槛多收数据)
GAS_USD_PER_ARB = 0.0005 * 600         # BSC 一笔原子套利 gas ~0.0005 BNB × $600 ≈ $0.3
RECHECK_BLOCKS = 3                     # N 个区块后回查机会是否还在(抢跑判定)
LOG = "./data/dexarb_shadow.csv"
COLS = ["ts", "block", "pair", "buy_dex", "sell_dex", "notional", "spread_bps",
        "gross_bps", "net_bps", "survive_blocks", "outcome"]


@dataclass
class Pool:
    dex: str
    addr: str
    fee_bps: int
    token0: str


def _amount_out(amount_in: float, reserve_in: float, reserve_out: float, fee_bps: int) -> float:
    """V2 恒定乘积 + 该 DEX 真实手续费(各 DEX 不同:Pancake25/Biswap10)。"""
    f = (10000 - fee_bps) / 10000.0
    ain = amount_in * f
    return ain * reserve_out / (reserve_in + ain)


class DexArbShadow(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.rpc = ChainRpc(BSC_RPC, 56, timeout=10)
        self._stop = threading.Event()
        self._pools: dict[str, list[Pool]] = {}   # pair_key -> [Pool...]
        self._pending: list[dict] = []            # 待回查的机会
        self._init_log()
        self._resolve_pools()

    def _init_log(self):
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        # 文件不存在或为空(被清空)都补表头,否则首行机会会被 DictReader 当表头
        if not os.path.exists(LOG) or os.path.getsize(LOG) == 0:
            with open(LOG, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(COLS)

    def _log(self, row: dict):
        with open(LOG, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([row.get(c, "") for c in COLS])

    def _getpair(self, factory: str, a: str, b: str) -> str | None:
        try:
            r = self.rpc.call(factory, SEL_GETPAIR + _enc_addr(a) + _enc_addr(b))
            addr = "0x" + r[26:66]
            return addr if int(addr, 16) != 0 else None
        except Exception:  # noqa: BLE001
            return None

    def _token0(self, pair: str) -> str:
        return ("0x" + self.rpc.call(pair, SEL_TOKEN0)[26:66]).lower()

    def _reserves(self, pair: str) -> tuple[int, int]:
        r = self.rpc.call(pair, SEL_GETRESERVES)
        return int(r[2:66], 16), int(r[66:130], 16)

    def _resolve_pools(self):
        """对每个交易对,在各 DEX 工厂查池地址 + token0 顺序。"""
        for p in PAIRS:
            pools = []
            for d in DEXES:
                addr = self._getpair(d["factory"], p["base"], p["quote"])
                if not addr:
                    continue
                try:
                    t0 = self._token0(addr)
                    pools.append(Pool(d["name"], addr, d["fee_bps"], t0))
                except Exception:  # noqa: BLE001
                    continue
            if len(pools) >= 2:
                self._pools[p["key"]] = pools
                print(f"[shadow] {p['key']}: {len(pools)}池 {[x.dex for x in pools]}")
            else:
                print(f"[shadow] {p['key']}: 池不足2个,跳过")

    def _price_and_reserves(self, pool: Pool):
        """返回 (base储备, quote储备)。token0 顺序归一化。"""
        r0, r1 = self._reserves(pool.addr)
        # base 是 token0 还是 token1
        # 我们不存 base 地址在 Pool 里,用 quote=USDT 判定:token0==USDT → quote=r0
        return r0, r1

    def _best_arb(self, pair_key: str, pools: list[Pool], block: int):
        """两两组合算双向净利,取最优;>MIN_NET_BPS 记机会 + 挂回查。"""
        # 取各池储备(base,quote)
        snaps = []
        for pool in pools:
            try:
                r0, r1 = self._reserves(pool.addr)
                if pool.token0 == USDT.lower():
                    q, b = r0, r1   # token0=USDT(quote), token1=base
                else:
                    b, q = r0, r1
                if b <= 0 or q <= 0:
                    continue
                snaps.append((pool, b / 1e18, q / 1e18))   # 储备转浮点(假设18位;USDT/CAKE/WBNB/ETH都是18)
            except Exception:  # noqa: BLE001
                continue
        if len(snaps) < 2:
            return
        best = None
        for i in range(len(snaps)):
            for j in range(len(snaps)):
                if i == j:
                    continue
                buy, bb, bq = snaps[i]   # 在 buy 池用 USDT 买 base
                sell, sb, sq = snaps[j]  # 在 sell 池把 base 卖回 USDT
                for N in NOTIONALS:
                    base_got = _amount_out(N, bq, bb, buy.fee_bps)       # USDT→base @buy
                    usdt_back = _amount_out(base_got, sb, sq, sell.fee_bps)  # base→USDT @sell
                    gross = usdt_back - N
                    net = gross - GAS_USD_PER_ARB
                    net_bps = net / N * 1e4
                    if best is None or net_bps > best["net_bps"]:
                        # 原始价差(无手续费,纯价格差)
                        buy_px = bq / bb; sell_px = sq / sb
                        spread_bps = (sell_px - buy_px) / buy_px * 1e4
                        best = {"pair": pair_key, "buy_dex": buy.dex, "sell_dex": sell.dex,
                                "notional": N, "spread_bps": round(spread_bps, 1),
                                "gross_bps": round(gross / N * 1e4, 1), "net_bps": round(net_bps, 1),
                                "buy_addr": buy.addr, "sell_addr": sell.addr,
                                "buy_t0": buy.token0, "sell_t0": sell.token0,
                                "buy_fee": buy.fee_bps, "sell_fee": sell.fee_bps}
        if best and best["net_bps"] > MIN_NET_BPS:
            best["block"] = block
            best["ts"] = int(time.time() * 1000)
            self._pending.append(best)
            print(f"[机会] {pair_key} {best['buy_dex']}→{best['sell_dex']} "
                  f"${best['notional']} net {best['net_bps']}bps @blk{block}")

    def _recheck_pending(self, cur_block: int):
        """对 N 区块前的机会回查:净利是否还在(没被吃=可捕获;塌缩=被抢/自然回归)。"""
        still = []
        for opp in self._pending:
            if cur_block - opp["block"] < RECHECK_BLOCKS:
                still.append(opp)
                continue
            # 回查:重算这两池当前净利
            try:
                def res(addr, t0):
                    r0, r1 = self._reserves(addr)
                    return (r1 / 1e18, r0 / 1e18) if t0 == USDT.lower() else (r0 / 1e18, r1 / 1e18)
                bb, bq = res(opp["buy_addr"], opp["buy_t0"])
                sb, sq = res(opp["sell_addr"], opp["sell_t0"])
                N = opp["notional"]
                base_got = _amount_out(N, bq, bb, opp["buy_fee"])
                usdt_back = _amount_out(base_got, sb, sq, opp["sell_fee"])
                net_now = (usdt_back - N - GAS_USD_PER_ARB) / N * 1e4
                survive = cur_block - opp["block"]
                # 判定:N块后净利仍>MIN = 机会存活(后来者本可捕获);否则=塌缩(被抢/回归)
                outcome = "SURVIVED" if net_now > MIN_NET_BPS else "DECAYED"
                self._log({**opp, "survive_blocks": survive, "outcome": outcome})
                print(f"[回查] {opp['pair']} 原{opp['net_bps']}→{round(net_now,1)}bps "
                      f"{survive}块后 {outcome}")
            except Exception as e:  # noqa: BLE001
                self._log({**opp, "outcome": f"RECHECK_ERR:{type(e).__name__}"})
        self._pending = still

    def run(self):
        print(f"[shadow] DEX-DEX 影子测量启动 | {len(self._pools)}对 | "
              f"min_net>{MIN_NET_BPS}bps | gas假设${GAS_USD_PER_ARB:.2f}/笔")
        while not self._stop.is_set():
            t0 = time.time()
            try:
                block = int(self.rpc._call("eth_blockNumber", []), 16)
                for pair_key, pools in self._pools.items():
                    self._best_arb(pair_key, pools, block)
                self._recheck_pending(block)
            except Exception as e:  # noqa: BLE001
                print(f"[shadow] tick异常: {type(e).__name__}: {str(e)[:60]}")
            self._stop.wait(max(0.0, 1.0 - (time.time() - t0)))   # ~1s/轮(后来者真实速度)

    def stop(self):
        self._stop.set()


def main():
    s = DexArbShadow()
    s.start()
    try:
        while s.is_alive():
            s.join(1)
    except KeyboardInterrupt:
        s.stop()


if __name__ == "__main__":
    main()
