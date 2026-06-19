"""多市场并行采集线程。

每拍:
  1) 共享链上读(一次):ETH/USD 参考价、L2 gasPrice、实时 L1 data 费 → 每 swap gas_usd。
  2) 币安一次批量拉全部 bookTicker。
  3) 线程池并行对每个市场做 DEX 报价。
  4) 逐市场合成净基差并落盘。
全只读;任一市场/腿失败只记该市场 error,不影响其它市场与下一拍。
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .agg_quoter import AggQuoter
from .binance_feed import BinanceFutFeed
from .config import cfg
from .depth import probe_depth
from .dex_quoter import Quoter
from .markets import load_markets
from .spread_calc import compute_spread
from .state import State


class Collector(threading.Thread):
    def __init__(self, state: State):
        super().__init__(daemon=True)
        self.state = state
        self.markets = load_markets()
        self.quoter = Quoter(cfg.base_rpc)
        self.agg = AggQuoter(cfg.kyber_client_id, cfg.kyber_min_interval)
        self.feed = BinanceFutFeed(cfg.binance_fapi)
        self._stop = threading.Event()
        workers = min(cfg.rpc_concurrency, max(1, len(self.markets)))
        self._pool = ThreadPoolExecutor(max_workers=workers)
        # 按链缓存最近一次有效 gas_usd(KyberSwap 偶发不返回 gasUsd 时按链兜底,绝不跨链)
        self._gas_lock = threading.Lock()
        self._last_gas: dict[str, float] = {}
        # 深度探测:解析名义额阶梯 + 轮转游标(每拍只探测 1 个市场,避免限频)
        self._ladder = [float(x) for x in cfg.depth_ladder.split(",") if x.strip()]
        self._depth_cursor = 0

    def stop(self):
        self._stop.set()
        self._pool.shutdown(wait=False)

    def _gas_usd_per_swap(self) -> tuple[float, float]:
        """返回 (eth_usd, 每 swap gas_usd)。L1 取实时 oracle,失败回退固定缓冲。"""
        eth_usd = self.quoter.eth_usd_price()
        gas_price = self.quoter.gas_price_wei()
        l2_eth = cfg.gas_units * gas_price / 1e18
        try:
            l1_eth = self.quoter.l1_fee_wei() / 1e18
            gas_usd = (l2_eth + l1_eth) * eth_usd
        except Exception:  # noqa: BLE001
            gas_usd = l2_eth * eth_usd + cfg.l1_fee_usd  # 回退固定 L1 缓冲
        return eth_usd, gas_usd

    def _one_market(self, m, tickers, gas_usd, ts):
        sym = m.binance_symbol
        if sym not in tickers:
            self.state.record_error(m.key, f"币安无 {sym} 行情")
            return
        try:
            src = self.agg if m.source == "agg" else self.quoter
            q = src.quote_buy(m, m.notional_usd or cfg.notional_usd)
        except Exception as e:  # noqa: BLE001
            self.state.record_error(m.key, f"DEX报价失败 {type(e).__name__}: {e}")
            return
        t = tickers[sym]
        # 按链 gas:agg 源优先用 KyberSwap 路由自带 gasUsd(各链真实,ETH主网随拥堵变)。
        # 偶发缺失时按链兜底,绝不跨链用错 gas:
        #   - Base 链:有同链共享 oracle gas(gas_usd 参数),直接用;
        #   - 其他链:用该链最近一次有效 gasUsd 缓存;
        #   - 都没有(该链首拍就缺):才丢该拍。
        if m.source == "agg":
            if q.gas_usd is not None and q.gas_usd > 0:
                gas = q.gas_usd
                with self._gas_lock:
                    self._last_gas[m.chain] = gas
            else:
                with self._gas_lock:
                    cached = self._last_gas.get(m.chain)
                if m.chain == "BASE":
                    gas = gas_usd  # 同链共享 Base oracle,正确
                elif cached is not None:
                    gas = cached
                else:
                    self.state.record_error(m.key, f"kyber无gasUsd且{m.chain}无缓存gas,丢该拍")
                    return
        else:
            gas = gas_usd
        r = compute_spread(
            market=m.key, binance_symbol=sym, ts=ts,
            dex_eff_price=q.eff_price, dex_mid_price=q.mid_price,
            base_out=q.base_out, slippage_bps=q.slippage_bps,
            gas_usd=gas, fut_bid=t["bid"], fut_ask=t["ask"],
            notional_usd=m.notional_usd or cfg.notional_usd,
            taker_fee_bps=cfg.taker_fee_bps, recycle_bps=cfg.recycle_bps,
            min_net_bps=cfg.min_net_bps, exit_floor_bps=cfg.exit_floor_bps,
        )
        self.state.record(r)

    def run(self):
        self.quoter.prewarm(self.markets)  # 冷启动单线程预热池缓存
        while not self._stop.is_set():
            t0 = time.time()
            ts = int(t0 * 1000)
            try:
                _eth_usd, gas_usd = self._gas_usd_per_swap()
                tickers = self.feed.all_book_tickers()
            except Exception as e:  # noqa: BLE001
                self.state.record_error("_shared", f"共享读失败 {type(e).__name__}: {e}")
                self._stop.wait(cfg.poll_sec)
                continue

            futs = [self._pool.submit(self._one_market, m, tickers, gas_usd, ts) for m in self.markets]
            for f in futs:
                try:
                    f.result()
                except Exception:  # noqa: BLE001
                    pass  # _one_market 内部已记 error

            # 每拍轮转探测 1 个市场的深度(可执行最大额),避免一次性打爆 RPC/聚合器
            self._probe_one_depth(ts)

            elapsed = time.time() - t0
            self._stop.wait(max(0.0, cfg.poll_sec - elapsed))

    def _probe_one_depth(self, ts):
        if not self.markets or not self._ladder:
            return
        m = self.markets[self._depth_cursor % len(self.markets)]
        self._depth_cursor += 1
        try:
            src = self.agg if m.source == "agg" else self.quoter
            dr = probe_depth(src.quote_buy, m, self._ladder, cfg.depth_slip_tol_bps, ts)
            self.state.record_depth(dr)
        except Exception:  # noqa: BLE001
            pass  # 深度探测失败不影响主采集
