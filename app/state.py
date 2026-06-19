"""共享状态(多市场):逐市场滚动统计 + 累计统计 + CSV落盘 + 可选 crossarb:* 发布。

线程安全(采集线程写,FastAPI 读)。统计就是 P0 的交付物——
逐市场回答"往返净基差 > 阈值的机会,以多大频率/规模真实存在"。
"""
from __future__ import annotations

import csv
import json
import os
import threading
import time
from collections import deque

from .spread_calc import SpreadResult

CSV_COLS = [
    "market", "binance_symbol", "ts", "base_price", "dex_eff_price", "dex_mid_price",
    "fut_bid", "fut_ask", "notional_usd", "base_out", "slippage_bps", "gas_usd",
    "gross_bps", "taker_bps", "gas_bps", "exit_dex_bps", "recycle_bps",
    "net_entry_bps", "net_bps", "is_opportunity",
]


class MarketStat:
    __slots__ = ("samples", "opp_count", "gross_pos_count", "net_max", "net_sum",
                 "gross_max", "last", "errors")

    def __init__(self):
        self.samples = 0
        self.opp_count = 0
        self.gross_pos_count = 0
        self.net_max = -1e9
        self.net_sum = 0.0
        self.gross_max = -1e9
        self.last: SpreadResult | None = None
        self.errors = 0

    def update(self, r: SpreadResult):
        self.samples += 1
        self.net_sum += r.net_bps
        self.net_max = max(self.net_max, r.net_bps)
        self.gross_max = max(self.gross_max, r.gross_bps)
        if r.gross_bps > 0:
            self.gross_pos_count += 1
        if r.is_opportunity:
            self.opp_count += 1
        self.last = r

    def view(self, key: str) -> dict:
        n = self.samples
        return {
            "market": key,
            "binance_symbol": self.last.binance_symbol if self.last else "",
            "samples": n,
            "errors": self.errors,
            "opp_count": self.opp_count,
            "opp_rate_pct": round(self.opp_count / n * 100, 3) if n else 0.0,
            "gross_pos_rate_pct": round(self.gross_pos_count / n * 100, 3) if n else 0.0,
            "net_bps_avg": round(self.net_sum / n, 3) if n else 0.0,
            "net_bps_max": round(self.net_max, 3) if n else None,
            "gross_bps_max": round(self.gross_max, 3) if n else None,
            "last": self.last.as_dict() if self.last else None,
        }


class State:
    def __init__(self, csv_path: str, redis_url: str = "", min_net_bps: float = 20.0,
                 window: int = 240):
        self.csv_path = csv_path
        self.min_net_bps = min_net_bps
        self._lock = threading.Lock()       # 保护统计结构
        self._io_lock = threading.Lock()    # 串行化落盘+发布,防多线程 CSV 交错/丢行
        self._stats: dict[str, MarketStat] = {}
        self._recent = deque(maxlen=window)   # 跨市场最近样本(看板表)
        self._depth: dict[str, dict] = {}     # market -> 最近一次深度探测结果
        self._last_error = ""
        self._started = time.time()

        self._redis = None
        if redis_url:
            try:
                import redis
                self._redis = redis.from_url(redis_url)
                self._redis.ping()
            except Exception as e:  # noqa: BLE001
                self._last_error = f"redis 连接失败(降级不发布): {e}"
                self._redis = None

        self._init_csv()

    def _init_csv(self):
        d = os.path.dirname(self.csv_path)
        if d:
            os.makedirs(d, exist_ok=True)
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(CSV_COLS)

    def record(self, r: SpreadResult):
        with self._lock:
            st = self._stats.setdefault(r.market, MarketStat())
            st.update(r)
            self._recent.append(r)

        d = r.as_dict()
        # 串行化落盘+发布:concurrency>=2 时多市场同时完成,无锁追加会交错/丢行(污染数据集)
        with self._io_lock:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([d[c] if c != "is_opportunity" else int(d[c]) for c in CSV_COLS])
            if self._redis is not None:
                try:
                    pipe = self._redis.pipeline()
                    pipe.hset("crossarb:spreads", r.market, json.dumps(d))
                    pipe.publish("crossarb:spread:updates", r.market)
                    pipe.execute()
                except Exception as e:  # noqa: BLE001
                    self._last_error = f"redis 发布失败: {e}"

    def record_error(self, market: str, msg: str):
        with self._lock:
            self._stats.setdefault(market, MarketStat()).errors += 1
            self._last_error = f"[{market}] {msg}"

    def record_depth(self, dr):
        with self._lock:
            self._depth[dr.market] = {
                "max_exec_usd": dr.max_exec_usd,
                "slip_tol_bps": dr.slip_tol_bps,
                "ladder": dr.ladder,
                "ts": dr.ts,
            }

    def snapshot(self) -> dict:
        with self._lock:
            markets = [self._stats[k].view(k) for k in sorted(self._stats)]
            for m in markets:
                m["depth"] = self._depth.get(m["market"])
            total_samples = sum(m["samples"] for m in markets)
            total_opp = sum(m["opp_count"] for m in markets)
            total_err = sum(m["errors"] for m in markets)
            return {
                "uptime_sec": round(time.time() - self._started, 1),
                "min_net_bps": self.min_net_bps,
                "redis_enabled": self._redis is not None,
                "last_error": self._last_error,
                "totals": {
                    "samples": total_samples,
                    "errors": total_err,
                    "opp_count": total_opp,
                    "opp_rate_pct": round(total_opp / total_samples * 100, 3) if total_samples else 0.0,
                },
                "markets": markets,
                "recent": [r.as_dict() for r in list(self._recent)[-80:][::-1]],
            }
