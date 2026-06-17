"""Lightweight in-memory API metrics for engine health monitoring."""
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class APIMetrics:
    total_calls: int = 0
    total_errors: int = 0
    rate_limited: int = 0
    last_error_time: float = 0
    last_error_msg: str = ""
    last_success_time: float = 0
    used_weight_1m: int = 0          # latest IP used weight (reads)
    weight_limit_1m: int = 6000      # applicable IP per-minute limit
    weight_time: float = 0           # when IP weight was observed
    used_uid_weight_1m: int = 0      # per-UID used weight (borrow/repay = 1500 each)
    uid_limit_1m: int = 180000       # per-UID per-minute limit
    uid_weight_time: float = 0       # when UID weight was observed
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_weight(self, w: int, limit: int = 6000):
        with self._lock:
            self.used_weight_1m = w
            self.weight_limit_1m = limit
            self.weight_time = time.time()

    def record_uid_weight(self, w: int, limit: int = 180000):
        with self._lock:
            self.used_uid_weight_1m = w
            self.uid_limit_1m = limit
            self.uid_weight_time = time.time()

    def record_success(self):
        with self._lock:
            self.total_calls += 1
            self.last_success_time = time.time()

    def record_error(self, msg: str = ""):
        with self._lock:
            self.total_calls += 1
            self.total_errors += 1
            self.last_error_time = time.time()
            self.last_error_msg = msg[:200]

    def record_skip(self):
        """业务状态码(如 -3045 无可借库存)——市场状态,非 API 故障。既不计调用也不计错误,
        把"正常无券探测"从健康指标里摘出去,避免 total_errors 被无券复查越刷越高。"""
        with self._lock:
            self.last_success_time = time.time()

    def record_rate_limit(self):
        with self._lock:
            self.rate_limited += 1

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            return {
                "total_calls": self.total_calls,
                "total_errors": self.total_errors,
                "rate_limited": self.rate_limited,
                "error_rate": round(self.total_errors / max(self.total_calls, 1) * 100, 2),
                "last_error_ago_sec": int(now - self.last_error_time) if self.last_error_time else None,
                "last_error_msg": self.last_error_msg or None,
                "last_success_ago_sec": int(now - self.last_success_time) if self.last_success_time else None,
            }


_metrics: dict[int, APIMetrics] = defaultdict(APIMetrics)


def get_metrics(sub_account_id: int = 0) -> APIMetrics:
    return _metrics[sub_account_id]


def all_metrics_snapshot() -> dict[str, dict]:
    return {str(k): v.snapshot() for k, v in _metrics.items()}


def global_weight_snapshot() -> dict:
    """Freshest IP-wide used weight across all client metrics in this process.
    IP weight is per-IP (shared), consumed by read endpoints."""
    best_t, best_w, best_lim = 0.0, 0, 6000
    for m in _metrics.values():
        if m.weight_time > best_t:
            best_t, best_w, best_lim = m.weight_time, m.used_weight_1m, m.weight_limit_1m
    return {"used_weight_1m": best_w, "weight_time": best_t, "limit": best_lim}


def max_uid_weight_snapshot() -> dict:
    """Busiest UID's used weight (borrow-rate dimension). UID weight is per
    sub-account; the account closest to its 180000 cap bounds borrow throughput."""
    best_w, best_lim, best_t = 0, 180000, 0.0
    for m in _metrics.values():
        if m.used_uid_weight_1m > best_w:
            best_w, best_lim, best_t = m.used_uid_weight_1m, m.uid_limit_1m, m.uid_weight_time
    return {"used_uid_weight_1m": best_w, "uid_limit": best_lim, "uid_weight_time": best_t}
