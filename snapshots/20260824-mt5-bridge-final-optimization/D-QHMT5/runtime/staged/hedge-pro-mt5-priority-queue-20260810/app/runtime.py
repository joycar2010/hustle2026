import json
import os
import queue
import sqlite3
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from itertools import count
from typing import Callable, Dict, Optional


TERMINAL_STATES = frozenset(("DONE", "FAILED"))

# Keep the durable account writer serialized, but let an urgent risk-reducing
# command pass work that is still queued.  This mirrors the proven MT4 actor:
# an already-running broker call is never interrupted, while a queued close
# does not wait behind several queued opens.
EXECUTION_PRIORITY_CLOSE = 0
EXECUTION_PRIORITY_CANCEL = 1
EXECUTION_PRIORITY_OPEN = 10


def execution_priority(op):
    op = str(op or "order").lower()
    if op in ("close", "close_all"):
        return EXECUTION_PRIORITY_CLOSE
    if op == "cancel_all":
        return EXECUTION_PRIORITY_CANCEL
    return EXECUTION_PRIORITY_OPEN


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


class PrioritizedSingleThreadExecutor:
    """Run calls on one native-safe thread while prioritising urgent work.

    The MetaTrader5 Python extension is not safe to call concurrently for one
    terminal.  A normal ``ThreadPoolExecutor(max_workers=1)`` preserves that
    safety but lets a burst of background reads delay an order indefinitely.
    This small executor keeps the one-worker guarantee and orders queued work
    by ``priority`` (lower values run first).  The sequence number preserves
    FIFO ordering for calls with the same priority.
    """

    def __init__(self, thread_name_prefix="mt5-api"):
        self._queue = queue.PriorityQueue()
        self._sequence = count()
        self._state_lock = threading.Lock()
        self._shutdown = False
        self._queued = 0
        self._running = False
        self._worker = threading.Thread(
            target=self._run,
            name=thread_name_prefix,
            daemon=True,
        )
        self._worker.start()

    def submit(self, fn, *args, priority=10, **kwargs):
        future = Future()
        with self._state_lock:
            if self._shutdown:
                raise RuntimeError("cannot schedule new futures after shutdown")
            self._queued += 1
            self._queue.put((int(priority), next(self._sequence), future,
                             fn, args, kwargs))
        return future

    def _run(self):
        while True:
            priority, sequence, future, fn, args, kwargs = self._queue.get()
            try:
                if fn is None:
                    return
                with self._state_lock:
                    self._queued = max(0, self._queued - 1)
                    self._running = True
                if future.cancelled():
                    continue
                try:
                    future.set_result(fn(*args, **kwargs))
                except BaseException as exc:
                    future.set_exception(exc)
            finally:
                with self._state_lock:
                    self._running = False
                self._queue.task_done()

    def metrics(self):
        with self._state_lock:
            return {
                "queued": self._queued,
                "running": self._running,
                "single_thread": True,
            }

    def shutdown(self, wait=True, cancel_futures=False):
        with self._state_lock:
            if self._shutdown:
                worker = self._worker
            else:
                self._shutdown = True
                if cancel_futures:
                    # Futures already pulled by the worker cannot be cancelled;
                    # drain only the calls still waiting in the priority queue.
                    while True:
                        try:
                            _priority, _sequence, future, _fn, _args, _kwargs = self._queue.get_nowait()
                        except queue.Empty:
                            break
                        future.cancel()
                        self._queued = max(0, self._queued - 1)
                        self._queue.task_done()
                self._queue.put((10**9, next(self._sequence), None, None, (), {}))
                worker = self._worker
        if wait:
            worker.join()


class PositionSnapshotCache:
    def __init__(self, fetcher: Callable, serializer: Callable, ttl_ms=150,
                 stale_max_ms=2000, boot=None):
        self.fetcher = fetcher
        self.serializer = serializer
        self.ttl_ms = max(0, int(ttl_ms))
        self.stale_max_ms = max(self.ttl_ms, int(stale_max_ms))
        self.boot = int(boot if boot is not None else time.time_ns() // 1_000_000)
        self._lock = threading.RLock()
        self._refresh_done = threading.Condition(self._lock)
        self._positions = None
        self._refreshed_at = 0.0
        self._snapshot_ts = 0
        self._snapshot_ts_ms = 0
        self._seq = 0
        self._invalidated = True
        self._invalidation_seq = 0
        self._refreshing = False

    def invalidate(self):
        with self._lock:
            self._invalidated = True
            self._invalidation_seq += 1

    def get(self):
        """Return a bounded snapshot, coalescing concurrent broker refreshes.

        Refresh I/O intentionally happens outside ``_lock``.  An order that
        invalidates the cache therefore never waits for a slow positions read,
        while callers with a usable snapshot can continue to receive bounded
        stale data during the one in-flight refresh.  A caller without any
        snapshot waits for that first refresh to finish.
        """
        while True:
            with self._lock:
                now = time.monotonic()
                age_ms = ((now - self._refreshed_at) * 1000
                          if self._refreshed_at else float("inf"))
                should_refresh = (
                    self._positions is None
                    or self._invalidated
                    or age_ms >= self.ttl_ms
                )
                if not should_refresh:
                    return self._snapshot(age_ms, False, "broker")

                if self._refreshing:
                    # Do not enqueue another positions_get for every UI poll.
                    # Once the bounded stale window expires, wait for the
                    # existing refresh rather than serving unbounded staleness.
                    if self._positions is not None and age_ms <= self.stale_max_ms:
                        return self._snapshot(age_ms, True, "cache")
                    self._refresh_done.wait()
                    continue

                self._refreshing = True
                refresh_seq = self._invalidation_seq

            try:
                raw = self.fetcher()
                if raw is None:
                    raise RuntimeError("positions_get returned None")
                positions = [self.serializer(position) for position in raw]
            except Exception:
                with self._lock:
                    self._refreshing = False
                    self._refresh_done.notify_all()
                    now = time.monotonic()
                    age_ms = ((now - self._refreshed_at) * 1000
                              if self._refreshed_at else float("inf"))
                    if self._positions is None or age_ms > self.stale_max_ms:
                        raise
                    return self._snapshot(age_ms, True, "cache")

            with self._lock:
                now = time.monotonic()
                self._positions = positions
                self._refreshed_at = now
                self._snapshot_ts_ms = time.time_ns() // 1_000_000
                self._snapshot_ts = self._snapshot_ts_ms // 1000
                self._seq += 1
                # Keep an invalidation that arrived while I/O was in flight.
                self._invalidated = self._invalidation_seq != refresh_seq
                self._refreshing = False
                self._refresh_done.notify_all()
                return self._snapshot(0.0, False, "broker")

    def _snapshot(self, age_ms, snapshot_stale, snapshot_source):
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
        self._executor = PrioritizedSingleThreadExecutor(thread_name_prefix="mt5-execution")
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
                operation = op or "order"
                self._executor.submit(
                    self._run, request_id, operation, payload,
                    priority=execution_priority(operation),
                )

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
            future = self._executor.submit(
                self._run, request_id, op, payload,
                priority=execution_priority(op),
            )
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
            metrics = self._executor.metrics()
            return {
                "pending_executions": len(self._active_request_ids),
                "max_pending_executions": self.max_pending,
                "queued": metrics["queued"],
                "running": metrics["running"],
                "single_thread": metrics["single_thread"],
                "policy": "close_priority_terminal_serial",
                "priorities": {
                    "close": EXECUTION_PRIORITY_CLOSE,
                    "cancel": EXECUTION_PRIORITY_CANCEL,
                    "open": EXECUTION_PRIORITY_OPEN,
                },
            }

    def shutdown(self):
        self._executor.shutdown(wait=True, cancel_futures=False)
        with self._db_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
