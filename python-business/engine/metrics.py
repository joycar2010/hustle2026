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
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

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
