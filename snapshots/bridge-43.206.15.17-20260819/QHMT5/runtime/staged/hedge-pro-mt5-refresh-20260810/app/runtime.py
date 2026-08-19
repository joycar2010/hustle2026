import json
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Dict, Optional


TERMINAL_STATES = frozenset(("DONE", "FAILED"))


@dataclass(frozen=True)
class ExecutionOutcome:
    state: str
    result: Dict

    def __post_init__(self):
        if self.state not in ("DONE", "FAILED", "UNKNOWN"):
            raise ValueError("invalid execution state: %s" % self.state)


@dataclass(frozen=True)
class Submission:
    request_id: str
    record: Optional[Dict] = None
    future: object = None

    @property
    def replayed(self):
        return self.record is not None


class ExecutionBusy(RuntimeError):
    pass


class IntentConflict(RuntimeError):
    pass


class PositionSnapshotCache:
    def __init__(self, fetcher: Callable, serializer: Callable, ttl_ms=150,
                 stale_max_ms=2000, boot=None):
        self.fetcher = fetcher
        self.serializer = serializer
        self.ttl_ms = max(0, int(ttl_ms))
        self.stale_max_ms = max(self.ttl_ms, int(stale_max_ms))
        self.boot = int(boot if boot is not None else time.time_ns() // 1_000_000)
        self._lock = threading.Lock()
        self._positions = None
        self._refreshed_at = 0.0
        self._snapshot_ts = 0
        self._snapshot_ts_ms = 0
        self._seq = 0
        self._invalidated = True

    def invalidate(self):
        with self._lock:
            self._invalidated = True

    def get(self):
        with self._lock:
            now = time.monotonic()
            age_ms = (now - self._refreshed_at) * 1000 if self._refreshed_at else float("inf")
            should_refresh = self._positions is None or self._invalidated or age_ms >= self.ttl_ms
            snapshot_stale = False
            snapshot_source = "broker"
            if should_refresh:
                try:
                    raw = self.fetcher()
                    if raw is None:
                        raise RuntimeError("positions_get returned None")
                    positions = [self.serializer(position) for position in raw]
                except Exception:
                    if self._positions is None or age_ms > self.stale_max_ms:
                        raise
                    snapshot_stale = True
                    snapshot_source = "cache"
                else:
                    now = time.monotonic()
                    self._positions = positions
                    self._refreshed_at = now
                    self._snapshot_ts_ms = time.time_ns() // 1_000_000
                    self._snapshot_ts = self._snapshot_ts_ms // 1000
                    self._seq += 1
                    self._invalidated = False
                    age_ms = 0.0
            return {
                "positions": self._positions,
                "snapshot_boot": self.boot,
                "snapshot_seq": self._seq,
                "snapshot_ts": self._snapshot_ts,
                "snapshot_ts_ms": self._snapshot_ts_ms,
                "snapshot_age_ms": round(max(0.0, age_ms), 3),
                "snapshot_stale": snapshot_stale,
                "snapshot_source": snapshot_source,
            }


class DurableExecutionCoordinator:
    def __init__(self, db_path: str, executor_fn: Callable[[str, Dict], ExecutionOutcome],
                 max_pending=None):
        self.db_path = os.path.abspath(db_path)
        self.executor_fn = executor_fn
        self._db_lock = threading.Lock()
        self._admission_lock = threading.Lock()
        self.max_pending = max(1, int(max_pending if max_pending is not None
                                      else os.getenv("MAX_PENDING_EXECUTIONS", "32")))
        self._active_request_ids = set()
        self._conn = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5-execution")
        self._ensure_schema()
        self._recover_pending()

    def _connection(self):
        if self._conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
        return self._conn

    def _ensure_schema(self):
        with self._db_lock:
            conn = self._connection()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS order_requests ("
                "request_id TEXT PRIMARY KEY, state TEXT, result TEXT,"
                "created_at REAL, updated_at REAL, op TEXT, intent_hash TEXT, payload TEXT)"
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(order_requests)")}
            if "op" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN op TEXT")
            if "intent_hash" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN intent_hash TEXT")
            if "payload" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN payload TEXT")
            conn.commit()

    def _recover_pending(self):
        """Resume WAL-reserved work in FIFO order with its original request id."""
        with self._admission_lock:
            with self._db_lock:
                rows = self._connection().execute(
                    "SELECT request_id,op,payload FROM order_requests "
                    "WHERE state IN ('PENDING','SENDING') ORDER BY created_at"
                ).fetchall()
            for request_id, op, encoded in rows:
                try:
                    payload = json.loads(encoded) if encoded else None
                except (TypeError, ValueError):
                    payload = None
                if not isinstance(payload, dict):
                    self._write_state(request_id, "UNKNOWN", {
                        "success": False,
                        "unknown": True,
                        "request_id": request_id,
                        "error": "MT5 bridge restart found a legacy pending row without payload",
                    })
                    continue
                self._active_request_ids.add(request_id)
                self._executor.submit(self._run, request_id, op or "order", payload)

    def _get_locked(self, request_id):
        row = self._connection().execute(
            "SELECT state,result,op,intent_hash,created_at,updated_at,payload "
            "FROM order_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        if not row:
            return None
        result = json.loads(row[1]) if row[1] else None
        return {
            "request_id": request_id,
            "state": row[0],
            "result": result,
            "op": row[2],
            "intent_hash": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "payload": json.loads(row[6]) if row[6] else None,
        }

    def get(self, request_id):
        with self._db_lock:
            return self._get_locked(request_id)

    def _write_state(self, request_id, state, result=None):
        now = time.time()
        encoded = json.dumps(result, separators=(",", ":"), ensure_ascii=True) if result is not None else None
        with self._db_lock:
            self._connection().execute(
                "UPDATE order_requests SET state=?,result=?,updated_at=? WHERE request_id=?",
                (state, encoded, now, request_id),
            )
            self._connection().commit()

    def submit(self, request_id: str, op: str, intent_hash: str, payload: Dict):
        with self._admission_lock:
            with self._db_lock:
                existing = self._get_locked(request_id)
                if existing:
                    previous_hash = existing.get("intent_hash")
                    if previous_hash and previous_hash != intent_hash:
                        raise IntentConflict("request_id reused with a different intent")
                    return Submission(request_id=request_id, record=existing)
                if len(self._active_request_ids) >= self.max_pending:
                    raise ExecutionBusy(next(iter(self._active_request_ids), None))
                now = time.time()
                self._connection().execute(
                    "INSERT INTO order_requests "
                    "(request_id,state,result,created_at,updated_at,op,intent_hash,payload) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (request_id, "PENDING", None, now, now, op, intent_hash,
                     json.dumps(payload, separators=(",", ":"), ensure_ascii=True)),
                )
                self._connection().commit()
                self._active_request_ids.add(request_id)
            future = self._executor.submit(self._run, request_id, op, payload)
            return Submission(request_id=request_id, future=future)

    def _run(self, request_id, op, payload):
        try:
            self._write_state(request_id, "SENDING")
            try:
                outcome = self.executor_fn(op, payload)
                if not isinstance(outcome, ExecutionOutcome):
                    raise TypeError("executor_fn must return ExecutionOutcome")
            except Exception as exc:
                outcome = ExecutionOutcome("UNKNOWN", {
                    "success": False,
                    "unknown": True,
                    "request_id": request_id,
                    "error": "execution exception: %s" % exc,
                })
            self._write_state(request_id, outcome.state, outcome.result)
            return outcome
        finally:
            with self._admission_lock:
                self._active_request_ids.discard(request_id)

    def status(self, request_id):
        record = self.get(request_id)
        if not record:
            return None
        return {
            "request_id": request_id,
            "state": record["state"],
            "terminal": record["state"] in TERMINAL_STATES,
            "result": record.get("result"),
        }

    def metrics(self):
        with self._admission_lock:
            return {"pending_executions": len(self._active_request_ids),
                    "max_pending_executions": self.max_pending}

    def shutdown(self):
        self._executor.shutdown(wait=True, cancel_futures=False)
        with self._db_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
