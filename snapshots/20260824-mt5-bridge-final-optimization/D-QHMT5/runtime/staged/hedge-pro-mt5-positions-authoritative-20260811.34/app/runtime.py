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


class TradeAdmissionGate:
    """Keep ordinary broker reads out of a terminal trade burst.

    MetaTrader5 exposes one account-scoped native session.  A queued trade
    must therefore reserve the session before a background ``positions_get``
    is admitted.  The gate does not interrupt a read which already owns the
    native worker; the executor's priority queue handles that unavoidable
    handoff safely.
    """

    def __init__(self, clock=None):
        self._condition = threading.Condition()
        self._clock = clock or time.monotonic
        self._pending_trades = 0
        self._active_reads = 0
        self._last_trade_activity_at = None

    def reserve_trade(self):
        with self._condition:
            self._pending_trades += 1
            self._last_trade_activity_at = self._clock()
            self._condition.notify_all()
            return self._pending_trades

    def release_trade(self):
        with self._condition:
            self._pending_trades = max(0, self._pending_trades - 1)
            self._last_trade_activity_at = self._clock()
            self._condition.notify_all()
            return self._pending_trades

    def _quiet_remaining_locked(self, quiet_seconds):
        quiet_seconds = max(0.0, float(quiet_seconds or 0.0))
        if not quiet_seconds or self._last_trade_activity_at is None:
            return 0.0
        return max(
            0.0,
            quiet_seconds - (self._clock() - self._last_trade_activity_at),
        )

    def quiet_remaining(self, quiet_seconds):
        with self._condition:
            return self._quiet_remaining_locked(quiet_seconds)

    def trade_activity(self, quiet_seconds=0.0):
        """Include the short gap between commands in one terminal burst."""
        with self._condition:
            return bool(
                self._pending_trades
                or self._quiet_remaining_locked(quiet_seconds) > 0
            )

    def begin_read(self, timeout=None, quiet_seconds=0.0):
        """Wait for both admitted trades and the post-trade quiet window."""
        with self._condition:
            deadline = (
                None
                if timeout is None
                else self._clock() + max(0.0, timeout)
            )
            while True:
                quiet_remaining = self._quiet_remaining_locked(quiet_seconds)
                if not self._pending_trades and quiet_remaining <= 0:
                    break
                if deadline is None:
                    wait_for = quiet_remaining if not self._pending_trades else None
                else:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        raise TimeoutError("trade admission gate is busy")
                    wait_for = remaining
                    if not self._pending_trades and quiet_remaining > 0:
                        wait_for = min(wait_for, quiet_remaining)
                self._condition.wait(wait_for)
            self._active_reads += 1

    def end_read(self):
        with self._condition:
            self._active_reads = max(0, self._active_reads - 1)
            self._condition.notify_all()

    def pending_trades(self):
        with self._condition:
            return self._pending_trades

    def metrics(self):
        with self._condition:
            return {
                "pending_trades": self._pending_trades,
                "active_reads": self._active_reads,
            }


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
        self._last_timing = None
        self._timing_by_name = {}
        self._worker = threading.Thread(
            target=self._run,
            name=thread_name_prefix,
            daemon=True,
        )
        self._worker.start()

    def submit(self, fn, *args, priority=10, metric_name=None, **kwargs):
        future = Future()
        submitted_mono_ns = time.perf_counter_ns()
        submitted_wall_ns = time.time_ns()
        name = str(metric_name or getattr(fn, "__name__", "native_call"))
        with self._state_lock:
            if self._shutdown:
                raise RuntimeError("cannot schedule new futures after shutdown")
            self._queued += 1
            queue_depth = self._queued
            self._queue.put((int(priority), next(self._sequence), future,
                             fn, args, kwargs, name, queue_depth,
                             submitted_mono_ns, submitted_wall_ns))
        return future

    def _run(self):
        while True:
            (priority, sequence, future, fn, args, kwargs, name, queue_depth,
             submitted_mono_ns, submitted_wall_ns) = self._queue.get()
            try:
                if fn is None:
                    return
                with self._state_lock:
                    self._queued = max(0, self._queued - 1)
                    self._running = True
                if future.cancelled():
                    continue
                started_mono_ns = time.perf_counter_ns()
                started_wall_ns = time.time_ns()
                try:
                    result = fn(*args, **kwargs)
                except BaseException as exc:
                    ended_mono_ns = time.perf_counter_ns()
                    timing = self._publish_timing(
                        name, priority, queue_depth, submitted_mono_ns,
                        submitted_wall_ns, started_mono_ns, started_wall_ns,
                        ended_mono_ns, time.time_ns(), False,
                    )
                    future.native_timing = timing
                    if not future.cancelled():
                        future.set_exception(exc)
                else:
                    ended_mono_ns = time.perf_counter_ns()
                    timing = self._publish_timing(
                        name, priority, queue_depth, submitted_mono_ns,
                        submitted_wall_ns, started_mono_ns, started_wall_ns,
                        ended_mono_ns, time.time_ns(), True,
                    )
                    future.native_timing = timing
                    if not future.cancelled():
                        future.set_result(result)
            finally:
                with self._state_lock:
                    self._running = False
                self._queue.task_done()

    def _publish_timing(self, name, priority, queue_depth,
                        submitted_mono_ns, submitted_wall_ns,
                        started_mono_ns, started_wall_ns,
                        ended_mono_ns, ended_wall_ns, success):
        timing = {
            "name": name,
            "priority": int(priority),
            "queue_depth_at_submit": int(queue_depth),
            "queued_at_ns": int(submitted_wall_ns),
            "started_at_ns": int(started_wall_ns),
            "ended_at_ns": int(ended_wall_ns),
            "queue_ms": round(max(0, started_mono_ns - submitted_mono_ns) / 1_000_000, 3),
            "run_ms": round(max(0, ended_mono_ns - started_mono_ns) / 1_000_000, 3),
            "total_ms": round(max(0, ended_mono_ns - submitted_mono_ns) / 1_000_000, 3),
            "success": bool(success),
        }
        with self._state_lock:
            stats = self._timing_by_name.setdefault(name, {
                "count": 0,
                "failures": 0,
                "max_queue_ms": 0.0,
                "max_run_ms": 0.0,
                "max_total_ms": 0.0,
            })
            stats["count"] += 1
            if not success:
                stats["failures"] += 1
            stats["last_queue_ms"] = timing["queue_ms"]
            stats["last_run_ms"] = timing["run_ms"]
            stats["last_total_ms"] = timing["total_ms"]
            stats["max_queue_ms"] = max(stats["max_queue_ms"], timing["queue_ms"])
            stats["max_run_ms"] = max(stats["max_run_ms"], timing["run_ms"])
            stats["max_total_ms"] = max(stats["max_total_ms"], timing["total_ms"])
            self._last_timing = dict(timing)
        return timing

    def metrics(self):
        with self._state_lock:
            return {
                "queued": self._queued,
                "running": self._running,
                "single_thread": True,
                "last_call": (dict(self._last_timing)
                              if self._last_timing is not None else None),
                "calls": {name: dict(values)
                          for name, values in self._timing_by_name.items()},
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
                            queued_call = self._queue.get_nowait()
                        except queue.Empty:
                            break
                        future = queued_call[2]
                        future.cancel()
                        self._queued = max(0, self._queued - 1)
                        self._queue.task_done()
                self._queue.put((10**9, next(self._sequence), None, None, (), {},
                                 "shutdown", 0, time.perf_counter_ns(), time.time_ns()))
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

    def metadata(self):
        """Return the last published version without scheduling broker I/O.

        Trade responses use this to tell QH that the broker command is
        terminal while the coalesced positions snapshot is still pending.
        Reading the metadata never waits on the native MT5 worker.
        """
        with self._lock:
            age_ms = ((time.monotonic() - self._refreshed_at) * 1000
                      if self._refreshed_at else float("inf"))
            return {
                "snapshot_boot": self.boot,
                "snapshot_seq": self._seq,
                "snapshot_ts": self._snapshot_ts,
                "snapshot_ts_ms": self._snapshot_ts_ms,
                "snapshot_age_ms": (round(max(0.0, age_ms), 3)
                                     if age_ms != float("inf") else None),
                "snapshot_pending": bool(self._invalidated or self._refreshing),
            }

    def get_cached(self):
        """Return bounded cached truth without scheduling broker I/O."""
        with self._lock:
            if self._positions is None or not self._refreshed_at:
                return None
            age_ms = (time.monotonic() - self._refreshed_at) * 1000
            if age_ms > self.stale_max_ms:
                return None
            stale = bool(
                self._invalidated
                or self._refreshing
                or age_ms >= self.ttl_ms
            )
            return self._snapshot(
                age_ms,
                stale,
                "cache" if stale else "broker",
            )

    def peek_ticket(self, ticket):
        """Return a recent ticket from the last broker snapshot without I/O.

        A close command already carries an exact broker ticket.  During a
        burst, doing a fresh ``positions_get(ticket=...)`` before every close
        adds one native round trip per slot and recreates the queue gap that
        the MT4 command burst avoids.  The caller still sends the exact ticket
        to MT5; a stale/missing ticket simply falls back to an authoritative
        broker read.
        """
        try:
            wanted = int(ticket)
        except (TypeError, ValueError):
            return None
        with self._lock:
            if self._positions is None or not self._refreshed_at:
                return None
            age_ms = (time.monotonic() - self._refreshed_at) * 1000
            if age_ms > self.stale_max_ms:
                return None
            for position in self._positions:
                try:
                    if int(position.get("ticket")) == wanted:
                        return dict(position)
                except (AttributeError, TypeError, ValueError):
                    continue
        return None

    def get(self, authoritative=False, fetcher=None):
        """Return a bounded snapshot, coalescing concurrent broker refreshes.

        Refresh I/O intentionally happens outside ``_lock``.  An order that
        invalidates the cache therefore never waits for a slow positions read,
        while callers with a usable snapshot can continue to receive bounded
        stale data during the one in-flight refresh.  Authoritative callers
        instead wait for a broker generation started after their request and
        never fall back to stale data.
        """
        required_seq = None
        if authoritative:
            with self._lock:
                required_seq = self._seq + 1
        while True:
            with self._lock:
                now = time.monotonic()
                age_ms = ((now - self._refreshed_at) * 1000
                          if self._refreshed_at else float("inf"))
                if (
                    authoritative
                    and self._positions is not None
                    and self._seq >= required_seq
                    and not self._invalidated
                    and not self._refreshing
                ):
                    return self._snapshot(age_ms, False, "broker")
                should_refresh = (
                    authoritative
                    or self._positions is None
                    or self._invalidated
                    or age_ms >= self.ttl_ms
                )
                if not should_refresh:
                    return self._snapshot(age_ms, False, "broker")

                if self._refreshing:
                    if authoritative:
                        self._refresh_done.wait()
                        continue
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
                raw = (fetcher or self.fetcher)()
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
                    if authoritative:
                        raise
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
                if authoritative and self._invalidated:
                    continue
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
                 max_pending=None, on_admit: Optional[Callable] = None,
                 on_complete: Optional[Callable] = None):
        self.db_path = os.path.abspath(db_path)
        self.executor_fn = executor_fn
        self._db_lock = threading.Lock()
        self._admission_lock = threading.Lock()
        self.max_pending = max(1, int(max_pending if max_pending is not None
                                      else os.getenv("MAX_PENDING_EXECUTIONS", "32")))
        self.on_admit = on_admit
        self.on_complete = on_complete
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
                if self.on_admit is not None:
                    self.on_admit(request_id, operation)
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
            if self.on_admit is not None:
                self.on_admit(request_id, op)
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
            if self.on_complete is not None:
                try:
                    self.on_complete(request_id, op)
                except Exception:
                    # Admission accounting must never change the durable
                    # outcome of a broker command.
                    pass

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
