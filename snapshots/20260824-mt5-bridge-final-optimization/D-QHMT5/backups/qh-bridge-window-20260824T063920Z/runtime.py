import json
import hashlib
import importlib
import multiprocessing
import os
import queue
import sqlite3
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass
from itertools import count
from multiprocessing.connection import wait as wait_connections
from typing import Callable, Dict, Optional


# UNKNOWN is terminal from the execution coordinator's perspective: the
# broker dispatch outcome cannot be safely retried, even though reconciliation
# still has to establish whether the order was filled.  Keeping it out of this
# set made /order-status report terminal=false for a durable UNKNOWN row and
# caused clients to poll (or, worse, submit a duplicate) indefinitely.
TERMINAL_STATES = frozenset(("DONE", "FAILED", "UNKNOWN"))
WORKER_RESULT_STATES = frozenset(("DONE", "FAILED", "UNKNOWN"))
PRE_DISPATCH_STATES = frozenset(("ADMITTED", "PENDING", "CLAIMED"))

# Keep the durable account writer serialized, but let an urgent risk-reducing
# command pass work that is still queued.  This mirrors the proven MT4 actor:
# an already-running broker call is never interrupted, while a queued close
# does not wait behind several queued opens.
EXECUTION_PRIORITY_CLOSE = 0
EXECUTION_PRIORITY_CANCEL = 1
EXECUTION_PRIORITY_OPEN = 10

_NATIVE_RECORD_TAG = "__qh_mt5_record__"
_NATIVE_TUPLE_TAG = "__qh_mt5_tuple__"
_NATIVE_DICT_TAG = "__qh_mt5_dict__"


def _wal_fallback_poll_ms():
    try:
        configured = float(os.getenv("MT5_WAL_FALLBACK_POLL_MS", "50"))
    except (TypeError, ValueError):
        configured = 50.0
    return max(5, min(1000, int(configured)))


class NativeRecord:
    """Attribute-compatible copy of an MT5 namedtuple returned over RPC."""

    def __init__(self, values):
        self.__dict__.update(dict(values or {}))

    def _asdict(self):
        return dict(self.__dict__)

    def __repr__(self):
        fields = ", ".join(
            "%s=%r" % item for item in sorted(self.__dict__.items())
        )
        return "NativeRecord(%s)" % fields


def _encode_native_value(value):
    """Convert extension-owned records into deterministic queue-safe values."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    asdict = getattr(value, "_asdict", None)
    if callable(asdict):
        return {
            _NATIVE_RECORD_TAG: {
                str(key): _encode_native_value(item)
                for key, item in asdict().items()
            }
        }
    if isinstance(value, tuple):
        return {_NATIVE_TUPLE_TAG: [_encode_native_value(item) for item in value]}
    if isinstance(value, list):
        return [_encode_native_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _NATIVE_DICT_TAG: [
                (_encode_native_value(key), _encode_native_value(item))
                for key, item in value.items()
            ]
        }
    raise TypeError(
        "unsupported native RPC result type: %s" % type(value).__name__
    )


def _decode_native_value(value):
    if isinstance(value, list):
        return [_decode_native_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {_NATIVE_RECORD_TAG}:
        return NativeRecord({
            key: _decode_native_value(item)
            for key, item in value[_NATIVE_RECORD_TAG].items()
        })
    if set(value) == {_NATIVE_TUPLE_TAG}:
        return tuple(
            _decode_native_value(item)
            for item in value[_NATIVE_TUPLE_TAG]
        )
    if set(value) == {_NATIVE_DICT_TAG}:
        return {
            _decode_native_value(key): _decode_native_value(item)
            for key, item in value[_NATIVE_DICT_TAG]
        }
    raise ValueError("invalid native RPC result envelope")


class _ExclusiveProcessFileLock:
    """Small cross-platform process fence held by an open file descriptor."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.handle = None

    def acquire(self, timeout=0.0):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        handle = open(self.path, "a+b", buffering=0)
        if os.path.getsize(self.path) == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + max(0.0, float(timeout or 0.0))
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.handle = handle
                return self
            except (OSError, IOError):
                if time.monotonic() >= deadline:
                    handle.close()
                    raise ExecutionBusy("execution process lock is already owned")
                time.sleep(0.05)

    def release(self):
        handle = self.handle
        self.handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _account_fence_paths(db_path, fence_key):
    if not fence_key:
        return (db_path + ".owner.lock", db_path + ".worker.lock", None)
    lock_root = os.path.abspath(os.getenv(
        "MT5_EXECUTION_LOCK_DIR",
        os.path.join(tempfile.gettempdir(), "qh-mt5-execution-locks"),
    ))
    digest = hashlib.sha256(str(fence_key).encode("utf-8")).hexdigest()
    prefix = os.path.join(lock_root, "account-" + digest)
    return prefix + ".owner.lock", prefix + ".worker.lock", prefix + ".db-path"


def _bind_account_database(binding_path, db_path):
    """Keep one durable WAL identity behind an account-scoped process lock."""
    if not binding_path:
        return
    os.makedirs(os.path.dirname(binding_path), exist_ok=True)
    canonical = os.path.normcase(os.path.realpath(os.path.abspath(db_path)))
    try:
        with open(binding_path, "r", encoding="utf-8") as handle:
            raw_existing = handle.read().strip()
            existing = (
                os.path.normcase(os.path.realpath(raw_existing))
                if raw_existing else ""
            )
    except FileNotFoundError:
        existing = ""
    if existing and existing != canonical:
        raise ExecutionBusy(
            "execution account is bound to another durable database"
        )
    if existing:
        return
    temporary = "%s.tmp.%s.%s" % (binding_path, os.getpid(), uuid.uuid4().hex)
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(os.path.abspath(db_path))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, binding_path)
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass


def _pid_exists(pid):
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def execution_priority(op):
    op = str(op or "order").lower()
    # All close forms share one urgent risk-reducing lane.  ``close_batch``
    # is normally lowered to ``close`` by the HTTP adapter, but keeping it in
    # this canonical mapping prevents a nested coordinator or recovery tool
    # from accidentally treating a batch close as an open-priority request.
    if op in ("close", "close_all", "close_batch"):
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
    admitted_at_ns: int = 0

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
        self._execution_event = None

    def _sync_execution_event_locked(self):
        event = self._execution_event
        if event is None:
            return
        if self._active_reads:
            event.clear()
        else:
            event.set()

    def bind_execution_event(self, event):
        """Fence an isolated worker while an already-admitted read drains."""
        with self._condition:
            self._execution_event = event
            self._sync_execution_event_locked()

    def reserve_trade(self):
        with self._condition:
            # Register the writer before waiting on anything. New readers now
            # stop at begin_read, while an isolated worker uses the bound
            # execution event to wait for the one read that already owns the
            # terminal. This call stays non-blocking on the HTTP/WAL path.
            self._pending_trades += 1
            self._last_trade_activity_at = self._clock()
            self._condition.notify_all()
            return self._pending_trades

    def wait_for_no_active_reads(self, timeout=None):
        """Wait for readers admitted before reserve_trade(); new reads stay fenced."""
        with self._condition:
            deadline = (
                None
                if timeout is None
                else self._clock() + max(0.0, float(timeout))
            )
            while self._active_reads:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise TimeoutError("active MT5 control read did not drain")
                self._condition.wait(remaining)
            return True

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
                # Condition.wait() may oversleep on Windows. This invocation
                # was blocked when it entered the wait, so enforce its absolute
                # budget before accepting a quiet window that expired while
                # the thread was descheduled. An idle timeout=0 call still
                # succeeds above without entering this waited branch.
                if deadline is not None and self._clock() >= deadline:
                    raise TimeoutError("trade admission gate is busy")
            self._active_reads += 1
            self._sync_execution_event_locked()

    def end_read(self):
        with self._condition:
            self._active_reads = max(0, self._active_reads - 1)
            self._sync_execution_event_locked()
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

    def get_admission(self, max_age_ms):
        """Return a narrowly fresh broker snapshot without scheduling I/O.

        This is intentionally stricter than the ordinary display cache and
        intentionally weaker than ``get(authoritative=True)``.  It exists for
        a command that already owns the QH account/slot admission lease and
        needs a very recent versioned position view before dispatch.  A cache
        miss must be handled by the caller's normal authoritative fallback;
        this method must never enqueue ``positions_get`` ahead of an order.
        """
        try:
            max_age_ms = max(0.0, float(max_age_ms))
        except (TypeError, ValueError):
            return None
        with self._lock:
            if (self._positions is None or not self._refreshed_at or
                    self._invalidated or self._refreshing):
                return None
            age_ms = (time.monotonic() - self._refreshed_at) * 1000
            if age_ms < 0 or age_ms > max_age_ms:
                return None
            # The source stays broker: the cached generation was published by
            # a completed native positions_get and has not been invalidated.
            # ``snapshot_stale`` is false relative to this endpoint's explicit
            # admission age budget, not the shorter UI refresh TTL.
            return self._snapshot(age_ms, False, "broker")

    def peek_ticket(self, ticket):
        """Compatibility alias with the current fail-closed semantics.

        Older bridge code called ``peek_ticket`` and accepted a row from the
        stale-max window.  That is unsafe for a close request because a cache
        can be invalidated by an earlier fill or belong to a previous worker
        generation.  Keep the public name for old callers, but route it
        through the generation-aware implementation so no caller can
        accidentally reintroduce the legacy trust window.
        """
        return self.peek_fresh_ticket(ticket)

    def peek_fresh_ticket(self, ticket):
        """Return a ticket only from the current, non-invalidated generation.

        Admission may safely carry this row across the isolated execution RPC.
        Once a trade invalidates the cache, callers must use an authoritative
        broker read rather than reusing a stale volume or side.
        """
        try:
            wanted = int(ticket)
        except (TypeError, ValueError):
            return None
        with self._lock:
            if (self._positions is None or not self._refreshed_at
                    or self._invalidated):
                return None
            age_ms = (time.monotonic() - self._refreshed_at) * 1000
            if age_ms >= self.ttl_ms:
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
                "created_at REAL, updated_at REAL, op TEXT, intent_hash TEXT, payload TEXT,"
                "admitted_at_ns INTEGER, claimed_at_ns INTEGER, started_at_ns INTEGER,"
                "completed_at_ns INTEGER,"
                "worker_pid INTEGER,owner_id TEXT,worker_generation TEXT)"
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(order_requests)")}
            if "op" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN op TEXT")
            if "intent_hash" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN intent_hash TEXT")
            if "payload" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN payload TEXT")
            if "admitted_at_ns" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN admitted_at_ns INTEGER")
            if "started_at_ns" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN started_at_ns INTEGER")
            if "completed_at_ns" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN completed_at_ns INTEGER")
            if "worker_pid" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN worker_pid INTEGER")
            if "claimed_at_ns" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN claimed_at_ns INTEGER")
            if "owner_id" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN owner_id TEXT")
            if "worker_generation" not in columns:
                conn.execute("ALTER TABLE order_requests ADD COLUMN worker_generation TEXT")
            conn.commit()

    def _recover_pending(self):
        """Resume WAL-reserved work in FIFO order with its original request id."""
        with self._admission_lock:
            with self._db_lock:
                connection = self._connection()
                sending = connection.execute(
                    "SELECT request_id,result FROM order_requests WHERE state='SENDING'"
                ).fetchall()
                for request_id, encoded_previous in sending:
                    try:
                        result = json.loads(encoded_previous) if encoded_previous else {}
                    except (TypeError, ValueError):
                        result = {}
                    if not isinstance(result, dict):
                        result = {}
                    result.update({
                        "success": False,
                        "unknown": True,
                        "request_id": request_id,
                        "error": "bridge restart found a broker dispatch in progress",
                    })
                    connection.execute(
                        "UPDATE order_requests SET state='UNKNOWN',result=?,updated_at=?,"
                        "completed_at_ns=? WHERE request_id=? AND state='SENDING'",
                        (json.dumps(result, separators=(",", ":"), ensure_ascii=True),
                         time.time(), time.time_ns(), request_id),
                    )
                rows = connection.execute(
                    "SELECT request_id,op,payload FROM order_requests "
                    "WHERE state IN ('ADMITTED','PENDING','CLAIMED') ORDER BY created_at"
                ).fetchall()
                connection.execute(
                    "UPDATE order_requests SET state='PENDING',claimed_at_ns=NULL,"
                    "started_at_ns=NULL,worker_pid=NULL,worker_generation=NULL "
                    "WHERE state IN ('ADMITTED','PENDING','CLAIMED')"
                )
                connection.commit()
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
            "SELECT state,result,op,intent_hash,created_at,updated_at,payload,"
            "admitted_at_ns,started_at_ns,completed_at_ns,worker_pid "
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
            "admitted_at_ns": int(row[7] or 0),
            "started_at_ns": int(row[8] or 0),
            "completed_at_ns": int(row[9] or 0),
            "worker_pid": int(row[10] or 0),
        }

    def get(self, request_id):
        with self._db_lock:
            return self._get_locked(request_id)

    def prove_absent(self, request_id):
        """Create an atomic tombstone when an intent was never admitted.

        A late POST with the same request id will replay this tombstone instead
        of reaching the broker. This makes a status-side ABSENT proof safe even
        when the original client connection was delayed rather than rejected.
        """
        request_id = str(request_id or "")
        if not request_id:
            return None
        with self._admission_lock:
            with self._db_lock:
                existing = self._get_locked(request_id)
                if existing is not None:
                    return existing
                now = time.time()
                now_ns = time.time_ns()
                result = {
                    "success": False,
                    "failed": True,
                    "not_sent": True,
                    "not_filled": True,
                    "dispatch_durable": False,
                    "certainty": "NOT_FILLED",
                    "truth_confirmed": "not_filled",
                    "request_id": request_id,
                    "error": "request was not admitted to the bridge WAL",
                }
                self._connection().execute(
                    "INSERT INTO order_requests "
                    "(request_id,state,result,created_at,updated_at,op,intent_hash,payload,"
                    "admitted_at_ns,completed_at_ns) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (request_id, "ABSENT",
                     json.dumps(result, separators=(",", ":"), ensure_ascii=True),
                     now, now, None, None, None, 0, now_ns),
                )
                self._connection().commit()
                return self._get_locked(request_id)

    def _write_state(self, request_id, state, result=None):
        now = time.time()
        now_ns = time.time_ns()
        encoded = json.dumps(result, separators=(",", ":"), ensure_ascii=True) if result is not None else None
        with self._db_lock:
            if state == "SENDING":
                self._connection().execute(
                    "UPDATE order_requests SET state=?,result=?,updated_at=?,"
                    "started_at_ns=COALESCE(started_at_ns,?),worker_pid=? WHERE request_id=?",
                    (state, encoded, now, now_ns, os.getpid(), request_id),
                )
            elif state in WORKER_RESULT_STATES:
                self._connection().execute(
                    "UPDATE order_requests SET state=?,result=?,updated_at=?,"
                    "completed_at_ns=? WHERE request_id=?",
                    (state, encoded, now, now_ns, request_id),
                )
            else:
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
                admitted_at_ns = time.time_ns()
                self._connection().execute(
                    "INSERT INTO order_requests "
                    "(request_id,state,result,created_at,updated_at,op,intent_hash,payload,"
                    "admitted_at_ns) VALUES (?,?,?,?,?,?,?,?,?)",
                    (request_id, "PENDING", None, now, now, op, intent_hash,
                     json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
                     admitted_at_ns),
                )
                self._connection().commit()
                self._active_request_ids.add(request_id)
            if self.on_admit is not None:
                self.on_admit(request_id, op)
            future = self._executor.submit(
                self._run, request_id, op, payload,
                priority=execution_priority(op),
            )
            return Submission(request_id=request_id, future=future,
                              admitted_at_ns=admitted_at_ns)

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

    def status(self, request_id, prove_absent=False):
        record = self.prove_absent(request_id) if prove_absent else self.get(request_id)
        if not record:
            return None
        return {
            "request_id": request_id,
            "state": record["state"],
            "terminal": record["state"] in TERMINAL_STATES or record["state"] == "ABSENT",
            "result": record.get("result"),
            "admitted": record["state"] != "ABSENT",
            "trace": {
                "agent_wal_durable_ns": int(record.get("admitted_at_ns") or 0),
                "agent_worker_claimed_ns": int(record.get("claimed_at_ns") or 0),
                "agent_execution_started_ns": int(record.get("started_at_ns") or 0),
                "agent_execution_completed_ns": int(record.get("completed_at_ns") or 0),
                "agent_worker_pid": int(record.get("worker_pid") or 0),
            },
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
                "owner_serial": True,
                "native_owner_concurrency": 1,
                "queue_lane": "trade",
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


def _isolated_worker_connection(db_path):
    # The broker write itself runs on the bridge's native API thread. That
    # thread records DISPATCHING while the worker main thread is synchronously
    # waiting for it, so there is no concurrent SQLite use despite this flag.
    connection = sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


_ISOLATED_DISPATCH_CONTEXT_LOCK = threading.Lock()
_ISOLATED_DISPATCH_CONTEXT = None


def _set_isolated_dispatch_context(context):
    global _ISOLATED_DISPATCH_CONTEXT
    with _ISOLATED_DISPATCH_CONTEXT_LOCK:
        _ISOLATED_DISPATCH_CONTEXT = context


def mark_execution_dispatching():
    """Move the active isolated request to SENDING before native order_send."""
    with _ISOLATED_DISPATCH_CONTEXT_LOCK:
        context = _ISOLATED_DISPATCH_CONTEXT
    if context is None:
        return False
    connection, request_id, owner_id, worker_generation = context
    return _isolated_mark_dispatching(
        connection, request_id, owner_id, worker_generation,
    )


def record_execution_progress(progress):
    """Persist a bounded per-child batch projection for the active request.

    The outer WAL row remains the idempotency boundary.  A close-all worker
    can additionally checkpoint each exact ticket while the row is SENDING so
    a restart reports which tickets were already sent without replaying any
    broker request.  This is deliberately best-effort for non-isolated test
    coordinators; the isolated native owner is the production path.
    """
    if not isinstance(progress, dict):
        return False
    with _ISOLATED_DISPATCH_CONTEXT_LOCK:
        context = _ISOLATED_DISPATCH_CONTEXT
    if context is None:
        return False
    connection, request_id, owner_id, worker_generation = context
    return _isolated_record_progress(
        connection, request_id, owner_id, worker_generation, progress,
    )


def _isolated_record_progress(connection, request_id, owner_id,
                              worker_generation, progress):
    """Merge a compact batch progress object into the SENDING WAL result."""
    encoded_progress = json.dumps(
        progress, separators=(",", ":"), ensure_ascii=True,
    )
    for _attempt in range(20):
        try:
            row = connection.execute(
                "SELECT state,result,owner_id,worker_generation "
                "FROM order_requests WHERE request_id=?", (request_id,),
            ).fetchone()
            if not row or row[2] != owner_id or row[3] != worker_generation:
                return False
            if row[0] not in ("CLAIMED", "SENDING"):
                return False
            try:
                current = json.loads(row[1]) if row[1] else {}
            except (TypeError, ValueError):
                current = {}
            if not isinstance(current, dict):
                current = {}
            current["batch_progress"] = json.loads(encoded_progress)
            updated = connection.execute(
                "UPDATE order_requests SET result=?,updated_at=? "
                "WHERE request_id=? AND state IN ('CLAIMED','SENDING') "
                "AND owner_id=? AND worker_generation=?",
                (json.dumps(current, separators=(",", ":"), ensure_ascii=True),
                 time.time(), request_id, owner_id, worker_generation),
            ).rowcount
            connection.commit()
            return updated == 1
        except sqlite3.OperationalError:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            time.sleep(0.005)
    return False


def _isolated_claim_next(connection, owner_id, worker_generation):
    """Atomically claim one durable intent without implying broker dispatch."""
    for _attempt in range(20):
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_id,op,payload FROM order_requests "
                "WHERE state='PENDING' AND owner_id=? "
                "ORDER BY CASE "
                "WHEN op IN ('close','close_all','close_batch') THEN 0 "
                "WHEN op='cancel_all' THEN 1 ELSE 10 END, created_at, request_id LIMIT 1",
                (owner_id,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            claimed_at_ns = time.time_ns()
            updated = connection.execute(
                "UPDATE order_requests SET state='CLAIMED',updated_at=?,claimed_at_ns=?,"
                "worker_pid=?,worker_generation=? WHERE request_id=? AND state='PENDING' "
                "AND owner_id=?",
                (time.time(), claimed_at_ns, os.getpid(), worker_generation,
                 row[0], owner_id),
            ).rowcount
            connection.commit()
            if updated:
                try:
                    payload = json.loads(row[2]) if row[2] else None
                except (TypeError, ValueError):
                    payload = None
                return row[0], row[1] or "order", payload
        except sqlite3.OperationalError:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            time.sleep(0.005)
    return None


def _isolated_mark_dispatching(connection, request_id, owner_id,
                               worker_generation):
    """Fence the exact point immediately before the first broker write."""
    for _attempt in range(20):
        try:
            updated = connection.execute(
                "UPDATE order_requests SET state='SENDING',updated_at=?,started_at_ns=? "
                "WHERE request_id=? AND state='CLAIMED' AND owner_id=? "
                "AND worker_generation=?",
                (time.time(), time.time_ns(), request_id, owner_id,
                 worker_generation),
            ).rowcount
            connection.commit()
            if updated == 1:
                return True
            row = connection.execute(
                "SELECT state,owner_id,worker_generation FROM order_requests "
                "WHERE request_id=?", (request_id,),
            ).fetchone()
            if row == ("SENDING", owner_id, worker_generation):
                return True
            raise RuntimeError(
                "isolated dispatch lost its CLAIMED ownership: %s" % request_id
            )
        except sqlite3.OperationalError:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            time.sleep(0.005)
    raise RuntimeError("could not persist isolated broker dispatch")


def _isolated_store_outcome(connection, request_id, outcome, owner_id,
                            worker_generation):
    state = getattr(outcome, "state", "UNKNOWN")
    result = getattr(outcome, "result", None)
    if state not in WORKER_RESULT_STATES or not isinstance(result, dict):
        state = "UNKNOWN"
        result = {
            "success": False,
            "unknown": True,
            "request_id": request_id,
            "error": "isolated executor returned an invalid outcome",
        }
    ownership = connection.execute(
        "SELECT state,owner_id,worker_generation FROM order_requests "
        "WHERE request_id=?", (request_id,),
    ).fetchone()
    if (ownership == ("CLAIMED", owner_id, worker_generation)
            and state in ("FAILED", "UNKNOWN")):
        # The dispatch marker is committed synchronously before order_send.
        # A preflight failure while still CLAIMED is therefore authoritative
        # no-fill proof and must not create a false single-leg review.
        state = "FAILED"
        result = dict(result or {})
        result.update({
            "success": False,
            "failed": True,
            "unknown": False,
            "not_sent": True,
            "not_filled": True,
            "dispatch_durable": False,
            "certainty": "NOT_FILLED",
            "truth_confirmed": "not_filled",
        })
    encoded = json.dumps(result, separators=(",", ":"), ensure_ascii=True)
    for _attempt in range(20):
        try:
            updated = connection.execute(
                "UPDATE order_requests SET state=?,result=?,updated_at=?,completed_at_ns=? "
                "WHERE request_id=? AND state IN ('CLAIMED','SENDING') AND owner_id=? "
                "AND worker_generation=?",
                (state, encoded, time.time(), time.time_ns(), request_id,
                 owner_id, worker_generation),
            ).rowcount
            connection.commit()
            if updated == 1:
                return
            raise RuntimeError(
                "isolated outcome lost its SENDING ownership: %s" % request_id
            )
        except sqlite3.OperationalError:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            time.sleep(0.005)
    raise RuntimeError("could not persist isolated execution outcome")


def _isolated_run_native_rpc(native_rpc, request, response_connection,
                             worker_generation):
    (request_generation, request_id, method, args, kwargs,
     expires_at_ns) = request
    if request_generation != worker_generation:
        response_connection.send((
            worker_generation, request_id, False, None,
            "native RPC belongs to a retired worker generation",
        ))
        return
    if int(expires_at_ns or 0) and time.time_ns() >= int(expires_at_ns):
        response_connection.send((
            worker_generation, request_id, False, None,
            "native RPC expired before execution",
        ))
        return
    try:
        if not callable(native_rpc):
            raise RuntimeError("isolated worker does not expose native RPC")
        result = native_rpc(str(method), tuple(args or ()), dict(kwargs or {}))
        encoded = _encode_native_value(result)
    except Exception as exc:
        response_connection.send((
            worker_generation, request_id, False, None,
            "%s: %s" % (exc.__class__.__name__, exc),
        ))
    else:
        response_connection.send((
            worker_generation, request_id, True, encoded, None,
        ))


def _drain_execution_wake(wake_connection):
    """Drain coalesced wake bytes without assigning truth to the transport."""
    while wake_connection.poll(0):
        wake_connection.recv_bytes()


def _isolated_worker_entry(db_path, executor_ref, stop_event, ready_event,
                           native_connection, execution_wake_connection,
                           worker_lock_path, parent_pid, owner_id,
                           worker_generation):
    """Process entry point and sole owner of the terminal's native MT5 IPC."""
    worker_lock = _ExclusiveProcessFileLock(worker_lock_path).acquire(timeout=10.0)
    connection = None
    shutdown = None
    try:
        os.environ["MT5_EXECUTION_CHILD"] = "1"
        # The parent includes this generation in any admission-time position
        # hint.  A WAL row that survives a worker restart must not reuse the
        # old terminal snapshot; the child imports app.main only after this
        # value is installed, so both sides can fence the hint consistently.
        os.environ["MT5_EXECUTION_WORKER_GENERATION"] = str(worker_generation)
        module_name, function_name = executor_ref.split(":", 1)
        module = importlib.import_module(module_name)
        executor_fn = getattr(module, function_name)
        startup = getattr(module, "_execution_worker_startup", None)
        shutdown = getattr(module, "_execution_worker_shutdown", None)
        native_rpc = getattr(module, "_execution_worker_native_call", None)
        connection = _isolated_worker_connection(db_path)
        if callable(startup):
            startup()
        ready_event.set()
        parent = multiprocessing.parent_process()
        fallback_poll_seconds = _wal_fallback_poll_ms() / 1000.0
        wake_connection = execution_wake_connection
        while not stop_event.is_set():
            parent_alive = (
                parent.is_alive()
                if parent is not None and parent.pid == parent_pid
                else _pid_exists(parent_pid)
            )
            if not parent_alive:
                break
            claimed = _isolated_claim_next(
                connection, owner_id, worker_generation,
            )
            if claimed is None:
                try:
                    waitables = [native_connection]
                    if wake_connection is not None:
                        waitables.append(wake_connection)
                    ready = wait_connections(
                        waitables, timeout=fallback_poll_seconds,
                    )
                    if wake_connection is not None and wake_connection in ready:
                        try:
                            _drain_execution_wake(wake_connection)
                        except (EOFError, OSError):
                            try:
                                wake_connection.close()
                            except (OSError, ValueError):
                                pass
                            wake_connection = None
                        # A wake is only a scheduling hint. Re-read the WAL and
                        # atomically claim its highest-priority durable row.
                        continue
                    if native_connection not in ready:
                        continue
                    # Admission commits PENDING before the parent sends its
                    # wake byte. A native RPC can become readable inside that
                    # tiny interval, so consult the WAL once more before
                    # consuming the read envelope. This keeps a durable trade
                    # ahead even if a caller bypasses the parent read gate.
                    claimed = _isolated_claim_next(
                        connection, owner_id, worker_generation,
                    )
                    if claimed is not None:
                        native_request = None
                    else:
                        native_request = native_connection.recv()
                except (EOFError, OSError, ValueError):
                    break
                if claimed is None:
                    if native_request is None:
                        continue
                    _isolated_run_native_rpc(
                        native_rpc, native_request, native_connection,
                        worker_generation,
                    )
                    continue
            request_id, operation, payload = claimed
            if not isinstance(payload, dict):
                outcome = ExecutionOutcome("FAILED", {
                    "success": False,
                    "failed": True,
                    "not_sent": True,
                    "not_filled": True,
                    "dispatch_durable": False,
                    "certainty": "NOT_FILLED",
                    "request_id": request_id,
                    "error": "durable intent payload is missing or invalid",
                })
            else:
                _set_isolated_dispatch_context(
                    (connection, request_id, owner_id, worker_generation)
                )
                try:
                    try:
                        outcome = executor_fn(operation, payload)
                    except Exception as exc:
                        outcome = ExecutionOutcome("UNKNOWN", {
                            "success": False,
                            "unknown": True,
                            "request_id": request_id,
                            "error": "isolated execution exception: %s" % exc,
                        })
                finally:
                    _set_isolated_dispatch_context(None)
            _isolated_store_outcome(
                connection, request_id, outcome, owner_id, worker_generation,
            )
    finally:
        ready_event.clear()
        if callable(shutdown):
            try:
                shutdown()
            except Exception:
                pass
        if connection is not None:
            connection.close()
        try:
            native_connection.close()
        except (AttributeError, OSError):
            pass
        if execution_wake_connection is not None:
            try:
                execution_wake_connection.close()
            except (AttributeError, OSError, ValueError):
                pass
        worker_lock.release()


class ProcessIsolatedExecutionCoordinator:
    """Durable admission in FastAPI, native MT5 execution in another process.

    MetaTrader5's ``order_send`` holds the Python GIL on Windows. Keeping it in
    this coordinator's child process lets the HTTP process durably ACK an
    entire slot burst while the terminal serially executes broker commands.
    """

    def __init__(self, db_path, executor_ref, max_pending=None, on_admit=None,
                 on_complete=None, admission_gate=None, owner_fence_key=None):
        self.db_path = os.path.abspath(db_path)
        self.executor_ref = str(executor_ref)
        self.max_pending = max(1, int(max_pending if max_pending is not None
                                      else os.getenv("MAX_PENDING_EXECUTIONS", "32")))
        self.on_admit = on_admit
        self.on_complete = on_complete
        self._admission_gate = admission_gate
        self._owner_id = uuid.uuid4().hex
        owner_lock_path, worker_lock_path, binding_path = _account_fence_paths(
            self.db_path, owner_fence_key,
        )
        self._owner_process_lock = _ExclusiveProcessFileLock(
            owner_lock_path
        ).acquire(timeout=0.0)
        self._worker_process_lock_path = worker_lock_path
        self._db_lock = threading.Lock()
        self._admission_lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False
        self._conn = None
        self._active_request_ids = set()
        self._futures = {}
        self._shutdown_event = threading.Event()
        self._promotion_wake = threading.Event()
        self._ctx = multiprocessing.get_context("spawn")
        self._worker_stop = None
        self._worker_ready = None
        self._worker_wake_connection = None
        self._worker_wake_lock = threading.Lock()
        self._worker_wake_signals = 0
        self._worker_wake_failures = 0
        self._native_parent_connection = None
        self._native_rpc_lock = threading.Lock()
        self._native_stats_lock = threading.Lock()
        self._native_rpc_calls = 0
        self._native_rpc_failures = 0
        self._native_rpc_running = False
        self._native_rpc_last = None
        self._process = None
        self._process_generation = None
        self._worker_restarts = 0
        self._last_worker_start = 0.0
        self._promoter_error = None
        self._monitor_error = None
        try:
            _bind_account_database(binding_path, self.db_path)
            self._ensure_schema()
            self._fence_previous_worker_and_recover()
            self._start_worker()
        except Exception:
            self._owner_process_lock.release()
            raise
        self._promoter = threading.Thread(
            target=self._promotion_loop,
            name="mt5-isolated-admission-promoter",
            daemon=True,
        )
        self._promoter.start()
        self._monitor = threading.Thread(
            target=self._monitor_loop,
            name="mt5-isolated-result-monitor",
            daemon=True,
        )
        self._monitor.start()
        self._promotion_wake.set()

    def _fence_previous_worker_and_recover(self):
        # A force-killed HTTP parent can leave its spawned native worker alive
        # until the current broker call returns. Wait for that process-held
        # lock before classifying any surviving SENDING row.
        timeout = max(1.0, float(os.getenv("MT5_WORKER_FENCE_WAIT_SEC", "120")))
        fence = _ExclusiveProcessFileLock(
            self._worker_process_lock_path
        ).acquire(timeout=timeout)
        try:
            self._recover_previous_process()
        finally:
            fence.release()

    def _connection(self):
        if self._conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False,
                                         timeout=5.0)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def _ensure_schema(self):
        with self._db_lock:
            connection = self._connection()
            connection.execute(
                "CREATE TABLE IF NOT EXISTS order_requests ("
                "request_id TEXT PRIMARY KEY, state TEXT, result TEXT,"
                "created_at REAL, updated_at REAL, op TEXT, intent_hash TEXT, payload TEXT,"
                "admitted_at_ns INTEGER, claimed_at_ns INTEGER, started_at_ns INTEGER,"
                "completed_at_ns INTEGER,"
                "worker_pid INTEGER)"
            )
            columns = {row[1] for row in connection.execute(
                "PRAGMA table_info(order_requests)"
            )}
            for name, declaration in (
                ("op", "TEXT"), ("intent_hash", "TEXT"), ("payload", "TEXT"),
                ("admitted_at_ns", "INTEGER"), ("claimed_at_ns", "INTEGER"),
                ("started_at_ns", "INTEGER"),
                ("completed_at_ns", "INTEGER"), ("worker_pid", "INTEGER"),
                ("owner_id", "TEXT"), ("worker_generation", "TEXT"),
            ):
                if name not in columns:
                    connection.execute(
                        "ALTER TABLE order_requests ADD COLUMN %s %s" % (name, declaration)
                    )
            connection.commit()

    @staticmethod
    def _decode_row(request_id, row):
        if row is None:
            return None
        return {
            "request_id": request_id,
            "state": row[0],
            "result": json.loads(row[1]) if row[1] else None,
            "op": row[2],
            "intent_hash": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "payload": json.loads(row[6]) if row[6] else None,
            "admitted_at_ns": int(row[7] or 0),
            "claimed_at_ns": int(row[8] or 0),
            "started_at_ns": int(row[9] or 0),
            "completed_at_ns": int(row[10] or 0),
            "worker_pid": int(row[11] or 0),
            "owner_id": row[12],
            "worker_generation": row[13],
        }

    def _get_locked(self, request_id):
        row = self._connection().execute(
            "SELECT state,result,op,intent_hash,created_at,updated_at,payload,"
            "admitted_at_ns,claimed_at_ns,started_at_ns,completed_at_ns,worker_pid,"
            "owner_id,worker_generation "
            "FROM order_requests WHERE request_id=?",
            (request_id,),
        ).fetchone()
        return self._decode_row(request_id, row)

    def get(self, request_id):
        with self._db_lock:
            return self._get_locked(str(request_id))

    def _recover_previous_process(self):
        with self._admission_lock:
            with self._db_lock:
                connection = self._connection()
                sending = connection.execute(
                    "SELECT request_id,result FROM order_requests WHERE state='SENDING'"
                ).fetchall()
                for request_id, encoded_previous in sending:
                    try:
                        result = json.loads(encoded_previous) if encoded_previous else {}
                    except (TypeError, ValueError):
                        result = {}
                    if not isinstance(result, dict):
                        result = {}
                    result.update({
                        "success": False,
                        "unknown": True,
                        "request_id": request_id,
                        "error": "execution worker restarted after broker dispatch began",
                    })
                    connection.execute(
                        "UPDATE order_requests SET state='UNKNOWN',result=?,updated_at=?,"
                        "completed_at_ns=? WHERE request_id=? AND state='SENDING'",
                        (json.dumps(result, separators=(",", ":"), ensure_ascii=True),
                         time.time(), time.time_ns(), request_id),
                    )
                connection.execute(
                    "UPDATE order_requests SET state='ADMITTED',owner_id=?,"
                    "worker_generation=NULL,worker_pid=NULL,claimed_at_ns=NULL,"
                    "started_at_ns=NULL WHERE state IN ('ADMITTED','PENDING','CLAIMED')",
                    (self._owner_id,),
                )
                pending = connection.execute(
                    "SELECT request_id,op,state FROM order_requests "
                    "WHERE state='ADMITTED' AND owner_id=?",
                    (self._owner_id,),
                ).fetchall()
                connection.commit()
            for request_id, operation, _state in pending:
                self._active_request_ids.add(request_id)
                if self.on_admit is not None:
                    self.on_admit(request_id, operation or "order")

    def _promote_admitted(self):
        with self._db_lock:
            waiting = self._connection().execute(
                "SELECT 1 FROM order_requests WHERE state='ADMITTED' "
                "AND owner_id=? LIMIT 1",
                (self._owner_id,),
            ).fetchone()
        if waiting is None:
            return False
        if self._admission_gate is not None:
            self._admission_gate.wait_for_no_active_reads(timeout=0.05)
        with self._db_lock:
            connection = self._connection()
            promoted = connection.execute(
                "UPDATE order_requests SET state='PENDING',updated_at=? "
                "WHERE state='ADMITTED' AND owner_id=?",
                (time.time(), self._owner_id),
            ).rowcount
            connection.commit()
        if promoted:
            self._signal_worker()
            return True
        return bool(promoted)

    def _signal_worker(self):
        """Wake the current worker after a PENDING row is durably committed.

        The byte stream deliberately carries no request identity. SQLite WAL
        remains authoritative, and the worker's bounded fallback poll covers
        a closed or lost generation-specific notification pipe.
        """
        with self._worker_lock:
            wake_connection = self._worker_wake_connection
        if wake_connection is None:
            return False
        try:
            with self._worker_wake_lock:
                wake_connection.send_bytes(b"\x01")
            with self._native_stats_lock:
                self._worker_wake_signals += 1
            return True
        except (BrokenPipeError, EOFError, OSError, ValueError):
            with self._native_stats_lock:
                self._worker_wake_failures += 1
            return False

    def _promotion_loop(self):
        backoff = 0.01
        while not self._shutdown_event.is_set():
            self._promotion_wake.wait(0.05)
            self._promotion_wake.clear()
            if self._shutdown_event.is_set():
                break
            try:
                self._promote_admitted()
                self._promoter_error = None
                backoff = 0.01
            except TimeoutError:
                self._promotion_wake.set()
                self._shutdown_event.wait(0.01)
            except Exception as exc:
                self._promoter_error = "%s: %s" % (
                    exc.__class__.__name__, exc,
                )
                if not self._shutdown_event.is_set():
                    self._promotion_wake.set()
                    self._shutdown_event.wait(backoff)
                    backoff = min(0.5, backoff * 2.0)

    def _start_worker(self):
        # Keep transport replacement serialized with native_call.  A worker
        # generation never inherits a pipe that a force-killed predecessor
        # may have left half-written.
        with self._native_rpc_lock:
            with self._worker_lock:
                if self._shutdown_event.is_set():
                    return
                if self._process is not None:
                    return
                worker_generation = uuid.uuid4().hex
                worker_stop = self._ctx.Event()
                worker_ready = self._ctx.Event()
                stale_connection = self._native_parent_connection
                self._native_parent_connection = None
                stale_wake_connection = self._worker_wake_connection
                self._worker_wake_connection = None
                if stale_connection is not None:
                    try:
                        stale_connection.close()
                    except (OSError, ValueError):
                        pass
                if stale_wake_connection is not None:
                    try:
                        with self._worker_wake_lock:
                            stale_wake_connection.close()
                    except (OSError, ValueError):
                        pass
                parent_connection, child_connection = self._ctx.Pipe(duplex=True)
                wake_receiver, wake_sender = self._ctx.Pipe(duplex=False)
                process = self._ctx.Process(
                    target=_isolated_worker_entry,
                    args=(self.db_path, self.executor_ref, worker_stop,
                          worker_ready, child_connection, wake_receiver,
                          self._worker_process_lock_path, os.getpid(),
                          self._owner_id, worker_generation),
                    name="mt5-native-execution",
                    daemon=True,
                )
                try:
                    process.start()
                except Exception:
                    parent_connection.close()
                    child_connection.close()
                    wake_receiver.close()
                    wake_sender.close()
                    raise
                child_connection.close()
                wake_receiver.close()
                self._process = process
                self._native_parent_connection = parent_connection
                self._worker_wake_connection = wake_sender
                self._process_generation = worker_generation
                self._worker_stop = worker_stop
                self._worker_ready = worker_ready
                self._worker_restarts += 1
                self._last_worker_start = time.monotonic()

    def wait_ready(self, timeout=20.0):
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            with self._worker_lock:
                process = self._process
                worker_ready = self._worker_ready
            try:
                process_alive = bool(process is not None and process.is_alive())
            except (AssertionError, OSError, ValueError):
                process_alive = False
            if process is not None and not process_alive:
                return False
            if worker_ready is None:
                self._shutdown_event.wait(
                    min(0.01, max(0.0, deadline - time.monotonic()))
                )
                continue
            if worker_ready.wait(min(0.05, max(0.0, deadline - time.monotonic()))):
                with self._worker_lock:
                    process = self._process
                    try:
                        return bool(process is not None and process.is_alive())
                    except (AssertionError, OSError, ValueError):
                        return False
        return False

    def native_call(self, method, args=(), kwargs=None, timeout=None):
        """Execute a read/control call in the process that owns MT5 IPC."""
        method = str(method or "")
        if not method or method in ("order_send", "order_check"):
            raise ExecutionBusy(
                "broker writes must enter through the durable execution WAL"
            )
        kwargs = dict(kwargs or {})
        if timeout is None:
            timeout = max(
                1.0, float(os.getenv("MT5_NATIVE_RPC_TIMEOUT_SEC", "30"))
            )
            native_timeout_ms = kwargs.get("timeout")
            if method in ("initialize", "login") and native_timeout_ms:
                try:
                    timeout = max(timeout, float(native_timeout_ms) / 1000.0 + 5.0)
                except (TypeError, ValueError):
                    pass
        # An explicit caller timeout is an end-to-end budget, including time
        # spent waiting behind another serialized native RPC.
        deadline = time.monotonic() + max(0.0, float(timeout))
        request_id = uuid.uuid4().hex
        success = False
        error = None
        rpc_tracked = False
        started = time.perf_counter()
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._native_rpc_lock.acquire(timeout=remaining):
            elapsed_ms = round(
                max(0.0, time.perf_counter() - started) * 1000, 3
            )
            error = "TimeoutError: native MT5 owner RPC lock timed out: %s" % method
            with self._native_stats_lock:
                self._native_rpc_calls += 1
                self._native_rpc_failures += 1
                self._native_rpc_last = {
                    "method": method,
                    "success": False,
                    "elapsed_ms": elapsed_ms,
                    "error": error,
                }
            raise TimeoutError(error.split(": ", 1)[1])
        try:
            if self._shutdown_event.is_set():
                raise ExecutionBusy("execution coordinator is shutting down")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "native MT5 owner RPC timed out before enqueue: %s" % method
                )
            with self._worker_lock:
                process = self._process
                worker_generation = self._process_generation
                native_connection = self._native_parent_connection
                worker_ready = self._worker_ready
                try:
                    alive = bool(process is not None and process.is_alive())
                except (AssertionError, OSError, ValueError):
                    alive = False
            if (not alive or not worker_generation or native_connection is None
                    or worker_ready is None or not worker_ready.is_set()):
                raise ExecutionBusy("native MT5 owner is not ready")
            with self._native_stats_lock:
                self._native_rpc_calls += 1
                self._native_rpc_running = True
                rpc_tracked = True
            try:
                expires_at_ns = time.time_ns() + int(max(
                    0.0, deadline - time.monotonic()
                ) * 1_000_000_000)
                native_connection.send((
                    worker_generation, request_id, method, tuple(args or ()), kwargs,
                    expires_at_ns,
                ))
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            "native MT5 owner RPC timed out: %s" % method
                        )
                    with self._worker_lock:
                        current_process = self._process
                        current_generation = self._process_generation
                        try:
                            current_alive = bool(
                                current_process is not None
                                and current_process.is_alive()
                            )
                        except (AssertionError, OSError, ValueError):
                            current_alive = False
                    if (not current_alive
                            or current_generation != worker_generation):
                        raise RuntimeError(
                            "native MT5 owner exited during RPC: %s" % method
                        )
                    try:
                        if not native_connection.poll(min(0.05, remaining)):
                            continue
                        response = native_connection.recv()
                    except (EOFError, OSError, ValueError) as exc:
                        raise RuntimeError(
                            "native MT5 owner exited during RPC: %s" % method
                        ) from exc
                    if response is None:
                        continue
                    (response_generation, response_id, response_ok,
                     encoded, response_error) = response
                    if (response_generation != worker_generation
                            or response_id != request_id):
                        # A caller may time out immediately before its response
                        # arrives. Discard that stale generation/call envelope;
                        # native RPCs are serialized so no live caller owns it.
                        continue
                    if not response_ok:
                        raise RuntimeError(
                            response_error or "native MT5 owner RPC failed"
                        )
                    result = _decode_native_value(encoded)
                    success = True
                    return result
            except Exception as exc:
                error = "%s: %s" % (exc.__class__.__name__, exc)
                with self._native_stats_lock:
                    self._native_rpc_failures += 1
                raise
            finally:
                elapsed_ms = round(
                    max(0.0, time.perf_counter() - started) * 1000, 3
                )
                with self._native_stats_lock:
                    self._native_rpc_running = False
                    self._native_rpc_last = {
                        "method": method,
                        "success": success,
                        "elapsed_ms": elapsed_ms,
                        "error": error,
                    }
        except Exception as exc:
            # Failures raised before the RPC enters its tracked section still
            # belong to this invocation (shutdown, expired deadline, no owner).
            with self._native_stats_lock:
                if not rpc_tracked:
                    self._native_rpc_calls += 1
                    self._native_rpc_failures += 1
                    self._native_rpc_last = {
                        "method": method,
                        "success": False,
                        "elapsed_ms": round(
                            max(0.0, time.perf_counter() - started) * 1000, 3
                        ),
                        "error": "%s: %s" % (exc.__class__.__name__, exc),
                    }
            raise
        finally:
            self._native_rpc_lock.release()

    def _mark_dead_worker_unknown(self, worker_generation):
        completed = []
        requeued = False
        with self._db_lock:
            connection = self._connection()
            claimed = connection.execute(
                "SELECT request_id FROM order_requests WHERE state='CLAIMED' "
                "AND owner_id=? AND worker_generation=?",
                (self._owner_id, worker_generation),
            ).fetchall()
            if claimed:
                connection.execute(
                    "UPDATE order_requests SET state='ADMITTED',updated_at=?,"
                    "claimed_at_ns=NULL,started_at_ns=NULL,worker_pid=NULL,"
                    "worker_generation=NULL WHERE state='CLAIMED' AND owner_id=? "
                    "AND worker_generation=?",
                    (time.time(), self._owner_id, worker_generation),
                )
                requeued = True
            rows = connection.execute(
                "SELECT request_id,result FROM order_requests WHERE state='SENDING' "
                "AND owner_id=? AND worker_generation=?",
                (self._owner_id, worker_generation),
            ).fetchall()
            for request_id, encoded_previous in rows:
                try:
                    result = json.loads(encoded_previous) if encoded_previous else {}
                except (TypeError, ValueError):
                    result = {}
                if not isinstance(result, dict):
                    result = {}
                result.update({
                    "success": False,
                    "unknown": True,
                    "request_id": request_id,
                    "error": "execution worker exited during broker dispatch",
                })
                connection.execute(
                    "UPDATE order_requests SET state='UNKNOWN',result=?,updated_at=?,"
                    "completed_at_ns=? WHERE request_id=? AND state='SENDING' "
                    "AND owner_id=? AND worker_generation=?",
                    (json.dumps(result, separators=(",", ":"), ensure_ascii=True),
                     time.time(), time.time_ns(), request_id, self._owner_id,
                     worker_generation),
                )
                completed.append(request_id)
            connection.commit()
        if requeued:
            self._promotion_wake.set()
        for request_id in completed:
            self._complete_request(request_id)

    def _fence_dead_worker(self, process, worker_generation):
        try:
            fence = _ExclusiveProcessFileLock(
                self._worker_process_lock_path
            ).acquire(timeout=0.2)
        except ExecutionBusy:
            return False
        try:
            self._mark_dead_worker_unknown(worker_generation)
        finally:
            fence.release()
        native_connection = None
        wake_connection = None
        with self._worker_lock:
            if self._process is process:
                self._process = None
                self._process_generation = None
                native_connection = self._native_parent_connection
                self._native_parent_connection = None
                wake_connection = self._worker_wake_connection
                self._worker_wake_connection = None
                self._worker_stop = None
                self._worker_ready = None
        if native_connection is not None:
            # A native caller holding this lock observes the detached
            # generation within one poll interval and fails before we close.
            with self._native_rpc_lock:
                try:
                    native_connection.close()
                except (OSError, ValueError):
                    pass
        if wake_connection is not None:
            try:
                with self._worker_wake_lock:
                    wake_connection.close()
            except (OSError, ValueError):
                pass
        try:
            process.join(timeout=0)
            process.close()
        except (AssertionError, OSError, ValueError):
            pass
        return True

    def _complete_request(self, request_id):
        record = self.get(request_id)
        if record is None or record.get("state") not in WORKER_RESULT_STATES:
            return
        future = None
        was_active = False
        with self._admission_lock:
            future = self._futures.pop(request_id, None)
            if request_id in self._active_request_ids:
                self._active_request_ids.discard(request_id)
                was_active = True
        if future is not None and not future.done():
            future.set_result(ExecutionOutcome(record["state"], record.get("result") or {}))
        if was_active and self.on_complete is not None:
            try:
                self.on_complete(request_id, record.get("op") or "order")
            except Exception:
                pass

    def _sweep_completed(self):
        with self._admission_lock:
            request_ids = tuple(self._active_request_ids)
        for request_id in request_ids:
            record = self.get(request_id)
            if record is not None and record.get("state") in WORKER_RESULT_STATES:
                self._complete_request(request_id)

    def _monitor_loop(self):
        backoff = 0.01
        while not self._shutdown_event.is_set():
            iteration_error = None
            try:
                self._sweep_completed()
                with self._worker_lock:
                    process = self._process
                    worker_generation = self._process_generation
                    try:
                        process_alive = bool(
                            process is not None and process.is_alive()
                        )
                    except (AssertionError, OSError, ValueError):
                        process_alive = False
                if process is not None and not process_alive:
                    self._fence_dead_worker(process, worker_generation)
                with self._worker_lock:
                    worker_missing = self._process is None
                if (worker_missing and
                        time.monotonic() - self._last_worker_start >= 1.0
                        and not self._shutdown_event.is_set()):
                    self._start_worker()
            except Exception as exc:
                iteration_error = exc
            if iteration_error is None:
                self._monitor_error = None
                backoff = 0.01
                self._shutdown_event.wait(0.01)
            else:
                self._monitor_error = "%s: %s" % (
                    iteration_error.__class__.__name__, iteration_error,
                )
                self._shutdown_event.wait(backoff)
                backoff = min(0.5, backoff * 2.0)

    def submit(self, request_id, op, intent_hash, payload):
        request_id = str(request_id)
        if self._shutdown_event.is_set():
            raise ExecutionBusy("execution coordinator is shutting down")
        initially_pending = False
        with self._admission_lock:
            with self._db_lock:
                existing = self._get_locked(request_id)
                if existing is not None:
                    previous_hash = existing.get("intent_hash")
                    if previous_hash and previous_hash != intent_hash:
                        raise IntentConflict("request_id reused with a different intent")
                    return Submission(request_id=request_id, record=existing)
                if len(self._active_request_ids) >= self.max_pending:
                    raise ExecutionBusy(next(iter(self._active_request_ids), None))
                now = time.time()
                admitted_at_ns = time.time_ns()
                self._connection().execute(
                    "INSERT INTO order_requests "
                    "(request_id,state,result,created_at,updated_at,op,intent_hash,payload,"
                    "admitted_at_ns,owner_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (request_id, "ADMITTED", None, now, now, op, intent_hash,
                      json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
                     admitted_at_ns, self._owner_id),
                )
                try:
                    if self.on_admit is not None:
                        self.on_admit(request_id, op)
                    # reserve_trade() has already fenced new readers. If no
                    # previously admitted native read remains, publish the WAL
                    # row as PENDING in this same FULL-sync transaction and
                    # avoid a promoter scheduling hop on the hot path.
                    if self._admission_gate is None:
                        initially_pending = True
                    else:
                        try:
                            self._admission_gate.wait_for_no_active_reads(
                                timeout=0.0,
                            )
                            initially_pending = True
                        except TimeoutError:
                            initially_pending = False
                    if initially_pending:
                        self._connection().execute(
                            "UPDATE order_requests SET state='PENDING',updated_at=? "
                            "WHERE request_id=? AND state='ADMITTED' AND owner_id=?",
                            (time.time(), request_id, self._owner_id),
                        )
                    self._connection().commit()
                except Exception:
                    self._connection().rollback()
                    if self.on_complete is not None:
                        try:
                            self.on_complete(request_id, op)
                        except Exception:
                            pass
                    raise
                self._active_request_ids.add(request_id)
            future = Future()
            self._futures[request_id] = future
        if initially_pending:
            self._signal_worker()
        else:
            self._promotion_wake.set()
        return Submission(request_id=request_id, future=future,
                          admitted_at_ns=admitted_at_ns)

    def prove_absent(self, request_id):
        request_id = str(request_id or "")
        if not request_id:
            return None
        with self._admission_lock:
            with self._db_lock:
                existing = self._get_locked(request_id)
                if existing is not None:
                    return existing
                now = time.time()
                now_ns = time.time_ns()
                result = {
                    "success": False,
                    "failed": True,
                    "not_sent": True,
                    "not_filled": True,
                    "dispatch_durable": False,
                    "certainty": "NOT_FILLED",
                    "truth_confirmed": "not_filled",
                    "request_id": request_id,
                    "error": "request was not admitted to the bridge WAL",
                }
                self._connection().execute(
                    "INSERT INTO order_requests "
                    "(request_id,state,result,created_at,updated_at,op,intent_hash,payload,"
                    "admitted_at_ns,completed_at_ns) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (request_id, "ABSENT",
                     json.dumps(result, separators=(",", ":"), ensure_ascii=True),
                     now, now, None, None, None, 0, now_ns),
                )
                self._connection().commit()
                return self._get_locked(request_id)

    @staticmethod
    def _status_payload(record):
        state = record["state"]
        return {
            "request_id": record["request_id"],
            "state": state,
            "terminal": state in TERMINAL_STATES or state == "ABSENT",
            "admitted": state != "ABSENT",
            "result": record.get("result"),
            "trace": {
                "agent_wal_durable_ns": int(record.get("admitted_at_ns") or 0),
                "agent_worker_claimed_ns": int(record.get("claimed_at_ns") or 0),
                "agent_execution_started_ns": int(record.get("started_at_ns") or 0),
                "agent_execution_completed_ns": int(record.get("completed_at_ns") or 0),
                "agent_worker_pid": int(record.get("worker_pid") or 0),
            },
        }

    def status(self, request_id, prove_absent=False):
        record = self.prove_absent(request_id) if prove_absent else self.get(request_id)
        return None if record is None else self._status_payload(record)

    def execution_probe_health(self):
        """Return fail-closed execution health without durable or native I/O."""
        with self._worker_lock:
            process = self._process
            worker_ready = self._worker_ready
            worker_stop = self._worker_stop
            process_generation = self._process_generation
            result_connection = self._native_parent_connection
            try:
                process_pid = process.pid if process is not None else None
                process_alive = bool(process is not None and process.is_alive())
            except (AssertionError, OSError, ValueError):
                process_pid = None
                process_alive = False
            try:
                worker_ready_set = bool(
                    worker_ready is not None and worker_ready.is_set()
                )
            except (OSError, ValueError):
                worker_ready_set = False
            try:
                worker_stop_requested = bool(
                    worker_stop is None or worker_stop.is_set()
                )
            except (OSError, ValueError):
                worker_stop_requested = True
            try:
                result_transport_ready = bool(
                    result_connection is not None and not result_connection.closed
                )
            except (OSError, ValueError):
                result_transport_ready = False

        promoter_alive = bool(
            hasattr(self, "_promoter") and self._promoter.is_alive()
        )
        monitor_alive = bool(
            hasattr(self, "_monitor") and self._monitor.is_alive()
        )
        owner_handle = getattr(self._owner_process_lock, "handle", None)
        owner_lock_held = bool(
            owner_handle is not None and not getattr(owner_handle, "closed", True)
        )
        shutdown_requested = bool(
            self._shutdown_complete or self._shutdown_event.is_set()
        )
        process_ready = bool(
            process_alive and worker_ready_set and not worker_stop_requested
        )
        single_owner_ready = bool(
            owner_lock_held
            and process_pid is not None
            and int(process_pid) > 0
            and int(process_pid) != os.getpid()
            and process_generation
            and result_transport_ready
        )
        coordinator_healthy = bool(
            process_ready
            and single_owner_ready
            and promoter_alive
            and monitor_alive
            and self._promoter_error is None
            and self._monitor_error is None
            and not shutdown_requested
        )
        return {
            "coordinator_healthy": coordinator_healthy,
            "process_isolated": True,
            "http_process_pid": os.getpid(),
            "execution_process_pid": process_pid,
            "execution_process_alive": process_alive,
            "execution_process_ready": process_ready,
            "native_owner_process_pid": process_pid,
            "native_owner_mode": "single_process_read_write_rpc",
            "single_owner_ready": single_owner_ready,
            "owner_lock_held": owner_lock_held,
            "worker_generation_ready": bool(process_generation),
            "result_transport_ready": result_transport_ready,
            "promoter_alive": promoter_alive,
            "monitor_alive": monitor_alive,
            "promoter_error": self._promoter_error,
            "monitor_error": self._monitor_error,
            "shutdown_requested": shutdown_requested,
            "source": "memory",
        }

    def metrics(self):
        memory_health = self.execution_probe_health()
        with self._admission_lock:
            pending = len(self._active_request_ids)
        with self._db_lock:
            admitted = self._connection().execute(
                "SELECT COUNT(*) FROM order_requests WHERE state='ADMITTED' "
                "AND owner_id=?", (self._owner_id,),
            ).fetchone()[0]
            queued = self._connection().execute(
                "SELECT COUNT(*) FROM order_requests WHERE state='PENDING' "
                "AND owner_id=?", (self._owner_id,),
            ).fetchone()[0]
            running = self._connection().execute(
                "SELECT COUNT(*) FROM order_requests WHERE state='SENDING' "
                "AND owner_id=?", (self._owner_id,),
            ).fetchone()[0]
            claimed = self._connection().execute(
                "SELECT COUNT(*) FROM order_requests WHERE state='CLAIMED' "
                "AND owner_id=?", (self._owner_id,),
            ).fetchone()[0]
        with self._native_stats_lock:
            native_rpc = {
                "calls": int(self._native_rpc_calls),
                "failures": int(self._native_rpc_failures),
                "running": bool(self._native_rpc_running),
                "last": (dict(self._native_rpc_last)
                         if self._native_rpc_last is not None else None),
            }
            wal_wakeup = {
                "mode": "generation_pipe_with_durable_poll_fallback",
                "signals": int(self._worker_wake_signals),
                "failures": int(self._worker_wake_failures),
                "fallback_poll_ms": _wal_fallback_poll_ms(),
            }
        return {
            "pending_executions": pending,
            "max_pending_executions": self.max_pending,
            "admitted_waiting": int(admitted),
            "queued": int(queued),
            "claimed": int(claimed),
            "running": int(running),
            # The HTTP coordinator and the spawned process are two processes,
            # but the account still has exactly one native MT5 owner/worker.
            # Expose the owner semantics rather than the implementation detail
            # so health gates and operators agree across both modes.
            "single_thread": True,
            "owner_serial": True,
            "native_owner_concurrency": 1,
            "process_isolated": True,
            "http_process_pid": memory_health["http_process_pid"],
            "owner_process_pid": memory_health["execution_process_pid"],
            "execution_process_pid": memory_health["execution_process_pid"],
            "execution_process_alive": memory_health["execution_process_alive"],
            "execution_process_ready": memory_health["execution_process_ready"],
            "execution_process_starts": self._worker_restarts,
            "native_owner_process_pid": memory_health["native_owner_process_pid"],
            "native_owner_mode": memory_health["native_owner_mode"],
            "native_rpc": native_rpc,
            "native_rpc_scope": "parent_control_rpc",
            "wal_wakeup": wal_wakeup,
            "promoter_alive": memory_health["promoter_alive"],
            "monitor_alive": memory_health["monitor_alive"],
            "promoter_error": self._promoter_error,
            "monitor_error": self._monitor_error,
            "coordinator_healthy": memory_health["coordinator_healthy"],
            "execution_gate_open": bool(
                self._admission_gate is None
                or self._admission_gate.metrics()["active_reads"] == 0
            ),
            "policy": "close_priority_terminal_serial_single_native_owner",
            "priorities": {
                "close": EXECUTION_PRIORITY_CLOSE,
                "cancel": EXECUTION_PRIORITY_CANCEL,
                "open": EXECUTION_PRIORITY_OPEN,
            },
        }

    def shutdown(self):
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._shutdown_event.set()
            self._promotion_wake.set()
            with self._worker_lock:
                worker_stop = self._worker_stop
                process = self._process
                try:
                    worker_alive_before_stop = bool(
                        process is not None and process.is_alive()
                    )
                except (AssertionError, OSError, ValueError):
                    worker_alive_before_stop = False
            if worker_alive_before_stop:
                if worker_stop is not None:
                    worker_stop.set()

            thread_timeout = max(2.0, float(os.getenv(
                "MT5_COORDINATOR_THREAD_SHUTDOWN_SEC", "10"
            )))
            current_thread = threading.current_thread()
            for thread in (self._promoter, self._monitor):
                if thread is not current_thread and thread.is_alive():
                    thread.join(timeout=thread_timeout)
            surviving_threads = [
                thread.name for thread in (self._promoter, self._monitor)
                if thread is not current_thread and thread.is_alive()
            ]
            if surviving_threads:
                raise RuntimeError(
                    "execution coordinator threads did not stop: %s" %
                    ", ".join(surviving_threads)
                )

            with self._worker_lock:
                process = self._process
                native_connection = self._native_parent_connection
                wake_connection = self._worker_wake_connection
                worker_generation = self._process_generation
                self._process = None
                self._native_parent_connection = None
                self._worker_wake_connection = None
                self._process_generation = None
                self._worker_stop = None
                self._worker_ready = None

            # Wake any in-flight RPC by retiring its generation, then close
            # the parent endpoint without racing another recv/poll.
            with self._native_rpc_lock:
                if native_connection is not None:
                    try:
                        native_connection.close()
                    except (OSError, ValueError):
                        pass
            if wake_connection is not None:
                try:
                    with self._worker_wake_lock:
                        wake_connection.close()
                except (OSError, ValueError):
                    pass

            worker_alive = False
            if process is not None:
                shutdown_timeout = max(1.0, float(os.getenv(
                    "MT5_EXECUTION_SHUTDOWN_SEC", "15"
                )))
                try:
                    process.join(timeout=shutdown_timeout)
                except (AssertionError, OSError, ValueError):
                    pass
                try:
                    worker_alive = process.is_alive()
                except (AssertionError, OSError, ValueError):
                    worker_alive = False
                if worker_alive:
                    try:
                        process.terminate()
                    except (AssertionError, OSError, ValueError):
                        pass
                    try:
                        process.join(timeout=5.0)
                    except (AssertionError, OSError, ValueError):
                        pass
                    try:
                        worker_alive = process.is_alive()
                    except (AssertionError, OSError, ValueError):
                        worker_alive = False
                if worker_alive and callable(getattr(process, "kill", None)):
                    try:
                        process.kill()
                        process.join(timeout=5.0)
                    except (AssertionError, OSError, ValueError):
                        pass
                    try:
                        worker_alive = process.is_alive()
                    except (AssertionError, OSError, ValueError):
                        worker_alive = False

            if worker_alive:
                # Retain the account owner fence.  A later shutdown call can
                # retry termination, but no second HTTP owner may start while
                # this native owner can still reach the broker.
                with self._worker_lock:
                    self._process = process
                    self._process_generation = worker_generation
                raise RuntimeError("native execution worker did not stop")

            if process is not None:
                try:
                    process.close()
                except (AssertionError, OSError, ValueError):
                    pass
            with self._db_lock:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
            self._owner_process_lock.release()
            self._shutdown_complete = True
