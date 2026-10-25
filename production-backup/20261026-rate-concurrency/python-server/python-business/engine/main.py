import asyncio
import inspect
import json
import logging
import os
import re
import signal
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings
from app.db.models import Base, SubAccount, GlobalRules
from app.db.session import engine as db_engine, SessionLocal
from app.db.models_auth import User
from engine.models import Position, TradeLog, EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed
from engine.orchestrator import Orchestrator
from engine.trading.borrow_coordination import (
    ACCOUNT_OPERATION_LOCK_TTL_SEC,
    AccountOperationLockBusy,
    AccountOperationLockUnavailable,
    account_operation_lock,
    master_symbol_lock,
)

logger = logging.getLogger("engine")

# Short-lived liveness marker consumed by the API/admin health view. Keep it
# independent from the DB heartbeat so a blocked DB transaction cannot make a
# live command consumer look stopped.
WORKER_HEARTBEAT_KEY = "engine:worker:heartbeat"
WORKER_HEARTBEAT_TTL = 30
# The timestamp remains the first field for backwards-compatible health reads.
# The owner suffix lets a graceful shutdown remove only its own heartbeat; a
# restarted Worker must never have its fresh key deleted by the old process.
WORKER_HEARTBEAT_OWNER_SEPARATOR = "|"
WORKER_HEARTBEAT_COMPARE_DELETE_SCRIPT = """
local value = redis.call('get', KEYS[1])
if not value then
    return 0
end
local suffix = ARGV[1] .. ARGV[2]
if string.sub(value, -string.len(suffix)) == suffix then
    local prefix_len = string.len(value) - string.len(suffix)
    local prefix = string.sub(value, 1, prefix_len)
    if string.match(prefix, '^%d+$') then
        return redis.call('del', KEYS[1])
    end
end
return 0
"""
# An API start request persists STARTING before the Redis command is consumed.
# Only a very short-lived STARTING row is eligible for crash/restart recovery;
# old rows must not silently re-enable a tenant after a maintenance stop.
STARTING_RECOVERY_MAX_AGE_SEC = 45
ADMIN_ENGINE_COMMAND_KEY = "engine:admin_commands"
# Starting a tenant engine performs a synchronous DB snapshot and may create
# several account workers.  Keep the command-consumer event loop responsive:
# a hung startup must become an actionable ERROR state instead of consuming a
# command and leaving the dashboard's toggle stuck at STARTING forever.
USER_ENGINE_START_TIMEOUT_SEC = 30

# 在途账户清理任务(clear_account 命令派生) —— 停机时先排空再关 client,防 use-after-close
_clear_tasks: set[asyncio.Task] = set()


def _new_worker_heartbeat_owner() -> str:
    """Return an unpredictable owner token for this Worker process."""
    return f"{os.getpid()}:{uuid.uuid4().hex}"


def _worker_heartbeat_value(owner: str, *, now: float | None = None) -> str:
    stamp = int(time.time() if now is None else now)
    return f"{stamp}{WORKER_HEARTBEAT_OWNER_SEPARATOR}{owner}"


async def _clear_worker_heartbeat(redis_client, owner: str) -> bool:
    """Compare-and-delete this process's heartbeat, without deleting a takeover.

    Redis ``EVAL`` is intentionally required for the production cleanup path;
    a GET followed by DEL would have a restart race.  Returning ``False`` on a
    missing/unsupported Redis command leaves the short TTL as the fallback.
    """
    if redis_client is None or not owner:
        return False
    try:
        deleted = await redis_client.eval(
            WORKER_HEARTBEAT_COMPARE_DELETE_SCRIPT,
            1,
            WORKER_HEARTBEAT_KEY,
            WORKER_HEARTBEAT_OWNER_SEPARATOR,
            owner,
        )
        return bool(int(deleted or 0))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Worker heartbeat compare-delete failed: %s", exc)
        return False


@asynccontextmanager
async def _maybe_master_symbol_lock(redis_client, user_id, symbol, *, owner: str):
    """Serialize account-clear exchange commands on a shared master symbol."""
    if user_id is None:
        yield
        return
    async with master_symbol_lock(
        redis_client,
        user_id,
        symbol,
        owner=owner,
        ttl_sec=ACCOUNT_OPERATION_LOCK_TTL_SEC,
    ):
        yield


class UserEngine:
    def __init__(self, user_id: int, spread_feed: SpreadFeed):
        self.user_id = user_id
        self.config_loader = ConfigLoader(user_id=user_id)
        self.orchestrator = Orchestrator(self.config_loader, spread_feed, user_id=user_id)

    async def start(self):
        await self.config_loader.start()
        await self.orchestrator.start()

    async def stop(self):
        await self.orchestrator.stop()
        await self.config_loader.stop()


def _get_active_user_ids() -> set[int]:
    db = SessionLocal()
    try:
        rows = db.query(SubAccount.user_id).filter(
            SubAccount.is_enabled == True,
            SubAccount.user_id.isnot(None),
        ).distinct().all()
        return {r.user_id for r in rows}
    finally:
        db.close()


def _starting_intent_is_fresh(state, *, now: datetime | None = None) -> bool:
    """Return whether a STARTING row still represents a recent user intent."""
    status = str(getattr(state, "status", "") or "").strip().upper()
    if status != "STARTING":
        return False
    current = now or datetime.now(timezone.utc)
    # ``updated_at`` is written by the API transaction that sets STARTING.  A
    # few legacy SQLite rows have no value, so fall back to last_heartbeat or
    # started_at rather than treating a missing timestamp as fresh.
    stamp = (
        getattr(state, "updated_at", None)
        or getattr(state, "last_heartbeat", None)
        or getattr(state, "started_at", None)
    )
    if stamp is None:
        return False
    try:
        if getattr(stamp, "tzinfo", None) is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (current - stamp).total_seconds()
    except (AttributeError, TypeError, ValueError):
        return False
    return 0 <= age <= STARTING_RECOVERY_MAX_AGE_SEC


def _get_running_user_ids() -> set[int]:
    db = SessionLocal()
    try:
        rows = db.query(EngineState).filter(
            EngineState.scope == "global",
            EngineState.user_id.isnot(None),
            EngineState.status.in_(["RUNNING", "STARTING"]),
        ).all()
        # RUNNING remains backward-compatible and always recovers; stale
        # STARTING rows are ignored so an old API intent cannot re-enable a
        # tenant after a maintenance stop.
        return {
            r.user_id for r in rows
            if str(getattr(r, "status", "") or "").strip().upper() == "RUNNING"
            or _starting_intent_is_fresh(r)
        }
    finally:
        db.close()


def _get_auto_start_user_ids() -> set[int]:
    db = SessionLocal()
    try:
        rows = db.query(GlobalRules.user_id).filter(
            GlobalRules.auto_start_on_boot == True,
            GlobalRules.user_id.isnot(None),
        ).all()
        return {r.user_id for r in rows}
    finally:
        db.close()


def _update_user_global_state(
    user_id: int,
    status: str,
    *,
    error_message: str | None = None,
):
    db = SessionLocal()
    try:
        state = db.query(EngineState).filter(
            EngineState.user_id == user_id, EngineState.scope == "global",
        ).first()
        if not state:
            state = EngineState(scope="global", user_id=user_id)
            db.add(state)
        state.status = status
        state.last_heartbeat = datetime.now(timezone.utc)
        # A successful acknowledgement clears the previous startup failure;
        # retaining it would make a recovered RUNNING tenant look unhealthy in
        # the expanded Worker panel.  Callers that do not pass an error keep
        # the historical value for intermediate states.
        if error_message is not None or status in {"RUNNING", "STOPPED"}:
            state.error_message = error_message
        db.commit()
    finally:
        db.close()


def _engine_start_error(exc: BaseException) -> str:
    """Build a short, non-secret diagnostic suitable for EngineState/UI."""
    # Exchange clients occasionally include a signed URL in exception text.
    # Persist only the exception class and a bounded, single-line message so a
    # failed startup cannot leak API credentials/signatures into the dashboard.
    detail = " ".join(str(exc or "").split())
    # Remove common signed-request fields before persisting/displaying the
    # diagnostic.  Keep the exception class and a short operational hint, but
    # never copy an API key, secret, listen key, or signature into EngineState.
    detail = re.sub(
        r"(?i)(api[_-]?(?:key|secret)|secretKey|listenKey|signature)\s*[:=]\s*[^\s,&]+",
        r"\1=<redacted>",
        detail,
    )
    detail = re.sub(
        r"(?i)([?&](?:api[_-]?(?:key|secret)|secretKey|listenKey|signature)=)[^&\s]+",
        r"\1<redacted>",
        detail,
    )
    if len(detail) > 240:
        detail = detail[:237] + "..."
    return (
        f"tenant engine startup failed ({type(exc).__name__})"
        + (f": {detail}" if detail else "")
    )


def _engine_stop_error(exc: BaseException) -> str:
    """Build a bounded, non-secret diagnostic for a failed tenant stop."""
    # Keep stop diagnostics subject to the same redaction and length limits as
    # startup diagnostics without changing the established startup wording.
    detail = _engine_start_error(exc)
    return detail.replace(
        "tenant engine startup failed",
        "tenant engine stop failed",
        1,
    )


async def _start_user_engine(
    user_engines: dict[int, "UserEngine"],
    spread_feed: SpreadFeed,
    user_id: int,
    *,
    source: str = "command",
) -> bool:
    """Start one tenant and always close the API lifecycle acknowledgement.

    The old command paths popped ``engine:<uid>:commands`` and awaited
    ``UserEngine.start()`` inline.  Any exception escaped to the outer loop,
    which logged it but never changed the persisted STARTING row.  This helper
    makes failure/timeout explicit, cleans partially-created tasks, and only
    publishes RUNNING after startup completed.
    """
    if user_id in user_engines:
        _update_user_global_state(user_id, "RUNNING", error_message=None)
        return True

    ue = UserEngine(user_id, spread_feed)
    try:
        await asyncio.wait_for(
            ue.start(),
            timeout=USER_ENGINE_START_TIMEOUT_SEC,
        )
    except asyncio.CancelledError:
        # The host is shutting down; do not overwrite a deliberate shutdown
        # with an ERROR acknowledgement, but still release partial resources.
        try:
            await ue.stop()
        except Exception:
            logger.debug("Partial tenant engine cleanup failed", exc_info=True)
        raise
    except Exception as exc:  # noqa: BLE001 - lifecycle boundary
        try:
            await ue.stop()
        except Exception:
            logger.warning(
                "Tenant %s partial startup cleanup failed",
                user_id,
                exc_info=True,
            )
        detail = _engine_start_error(exc)
        try:
            _update_user_global_state(user_id, "ERROR", error_message=detail)
        except Exception:
            # A DB outage must not kill the command consumer; the next health
            # read will expose the stale transition and permit an explicit
            # retry once the database is available.
            logger.error(
                "Unable to persist tenant %s startup failure",
                user_id,
                exc_info=True,
            )
        logger.error(
            "Tenant %s engine startup failed from %s: %s",
            user_id,
            source,
            detail,
            exc_info=True,
        )
        return False

    # Persist the acknowledgement before publishing the live engine in the
    # in-memory registry.  If the database commit fails, keeping the engine in
    # ``user_engines`` would let it trade while the control plane still shows
    # STARTING/ERROR.  Tear the partially started tenant down and make the
    # failure explicit instead.
    try:
        _update_user_global_state(user_id, "RUNNING", error_message=None)
    except Exception as exc:  # noqa: BLE001 - lifecycle boundary
        try:
            await ue.stop()
        except Exception:
            logger.warning(
                "Tenant %s cleanup failed after RUNNING acknowledgement error",
                user_id,
                exc_info=True,
            )
        detail = _engine_start_error(exc)
        try:
            _update_user_global_state(user_id, "ERROR", error_message=detail)
        except Exception:
            logger.error(
                "Unable to persist tenant %s acknowledgement failure",
                user_id,
                exc_info=True,
            )
        logger.error(
            "Tenant %s started but could not be acknowledged; engine stopped: %s",
            user_id,
            detail,
            exc_info=True,
        )
        return False

    user_engines[user_id] = ue
    logger.info("Started engine for user %s (%s)", user_id, source)
    return True


async def _stop_user_engine(
    user_engines: dict[int, "UserEngine"],
    user_id: int,
    *,
    source: str = "command",
) -> bool:
    """Stop one tenant and acknowledge the consumed stop command.

    Removing the registry entry before awaiting cleanup prevents a failed
    ``stop()`` from leaving a tenant eligible for heartbeats or subsequent
    work.  Every consumed stop is then acknowledged as either ``STOPPED`` or
    an actionable, bounded ``ERROR``; persistence failures are contained so a
    single broken tenant cannot halt command consumption for other users.
    """
    ue = user_engines.pop(user_id, None)
    stop_error: BaseException | None = None
    if ue is not None:
        try:
            await ue.stop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - lifecycle boundary
            stop_error = exc
            logger.error(
                "Tenant %s engine stop failed from %s: %s",
                user_id,
                source,
                _engine_stop_error(exc),
                exc_info=True,
            )

    status = "ERROR" if stop_error is not None else "STOPPED"
    error_message = _engine_stop_error(stop_error) if stop_error is not None else None
    try:
        if error_message is None:
            # Keep the no-op/success acknowledgement compatible with older
            # test doubles and local integrations that still expose the
            # historical two-argument state writer.
            result = _update_user_global_state(user_id, status)
            if inspect.isawaitable(result):
                await result
        else:
            try:
                result = _update_user_global_state(
                    user_id,
                    status,
                    error_message=error_message,
                )
                if inspect.isawaitable(result):
                    await result
            except TypeError:
                # During a rolling upgrade an older local consumer may still
                # expose the two-argument writer. Preserve the terminal
                # acknowledgement even when that version cannot store the
                # diagnostic text.
                result = _update_user_global_state(user_id, status)
                if inspect.isawaitable(result):
                    await result
    except Exception:  # noqa: BLE001 - acknowledgement boundary
        logger.error(
            "Unable to persist tenant %s %s acknowledgement",
            user_id,
            status,
            exc_info=True,
        )

    if stop_error is None:
        logger.info("Stopped engine for user %s (%s)", user_id, source)
        return True
    return False


async def _main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    logger.info("CEX Arbitrage Engine starting (pid=%d)", os.getpid())
    heartbeat_owner = _new_worker_heartbeat_owner()

    # Advertise command-consumer liveness before database/symbol recovery so
    # the API can distinguish a booting Worker host from a stopped one.  The
    # long-lived command loop refreshes the same key every iteration.
    try:
        heartbeat_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        try:
            await heartbeat_client.set(
                WORKER_HEARTBEAT_KEY,
                _worker_heartbeat_value(heartbeat_owner),
                ex=WORKER_HEARTBEAT_TTL,
            )
        finally:
            await heartbeat_client.aclose()
    except Exception as exc:
        # Startup continues so systemd can restart/retry; the API remains
        # fail-closed until a subsequent successful heartbeat is published.
        logger.warning("Initial Worker heartbeat unavailable: %s", exc)

    Base.metadata.create_all(bind=db_engine)
    logger.info("Database tables ensured")

    spread_feed = SpreadFeed()
    shutdown_event = asyncio.Event()

    def _shutdown(sig, frame):
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    db = SessionLocal()
    try:
        state = db.query(EngineState).filter(
            EngineState.scope == "global", EngineState.user_id.is_(None),
        ).first()
        if not state:
            state = EngineState(scope="global")
            db.add(state)
        state.status = "RUNNING"
        state.pid = os.getpid()
        state.started_at = datetime.now(timezone.utc)
        state.last_heartbeat = datetime.now(timezone.utc)
        state.error_message = None
        db.commit()
    finally:
        db.close()

    await spread_feed.start()

    user_engines: dict[int, UserEngine] = {}
    # Start the command consumer before tenant recovery so its dedicated
    # heartbeat remains fresh while DB/network startup awaits complete.  The
    # ready gate prevents commands from racing the boot-time registry rebuild.
    boot_ready = asyncio.Event()
    command_task = asyncio.create_task(
        _command_consumer_loop(
            user_engines,
            spread_feed,
            shutdown_event,
            heartbeat_owner=heartbeat_owner,
            ready_event=boot_ready,
        )
    )

    running_user_ids = _get_running_user_ids()
    if running_user_ids:
        for uid in running_user_ids:
            # A fresh STARTING row is a recoverable user intent.  Once the
            # orchestrator has been re-created, acknowledge it explicitly so
            # the dashboard does not remain in STARTING until another command
            # happens to arrive.  A failed recovery is isolated to this
            # tenant and is persisted as ERROR rather than aborting the host.
            await _start_user_engine(
                user_engines,
                spread_feed,
                uid,
                source="boot recovery",
            )
    else:
        active_user_ids = _get_active_user_ids()
        if not active_user_ids:
            ue = UserEngine(None, spread_feed)
            await ue.start()
            user_engines[0] = ue
            logger.info("Started legacy engine (no user_id)")

    # C1: auto_start_on_boot — auto-start engines for users with this flag
    auto_start_ids = _get_auto_start_user_ids()
    for uid in auto_start_ids:
        if uid in user_engines:
            continue
        logger.info(f"Auto-starting engine for user {uid} (auto_start_on_boot=true)")
        await asyncio.sleep(1)
        await _start_user_engine(
            user_engines,
            spread_feed,
            uid,
            source="auto-start",
        )

    logger.info(
        "Engine running: %d spreads, %d user engines",
        spread_feed.count,
        len(user_engines),
    )

    heartbeat_task = asyncio.create_task(_heartbeat_loop(shutdown_event, user_engines))
    reconcile_task = asyncio.create_task(_user_reconcile_loop(user_engines, spread_feed, shutdown_event))
    boot_ready.set()

    await shutdown_event.wait()

    logger.info("Shutting down gracefully...")
    heartbeat_task.cancel()
    reconcile_task.cancel()
    command_task.cancel()
    # Let each task run its cancellation/finally path before closing shared
    # clients.  In particular, the command consumer must release only its own
    # heartbeat marker before another Worker can take over the key.
    await asyncio.gather(
        heartbeat_task,
        reconcile_task,
        command_task,
        return_exceptions=True,
    )

    # 在途清仓任务是多腿交易,必须完整结束后才能关 worker/master client
    if _clear_tasks:
        logger.info(f"Waiting for {len(_clear_tasks)} in-flight clear task(s)...")
        done, pending = await asyncio.wait(set(_clear_tasks), timeout=60)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    for uid in list(user_engines.keys()):
        await _stop_user_engine(user_engines, uid, source="shutdown")

    from engine.trading.master_client import close_all as close_master_clients
    await close_master_clients()
    await spread_feed.stop()

    db = SessionLocal()
    try:
        state = db.query(EngineState).filter(
            EngineState.scope == "global", EngineState.user_id.is_(None),
        ).first()
        if state:
            state.status = "STOPPED"
            state.last_heartbeat = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

    logger.info("Engine stopped")


async def _command_consumer_loop(
    user_engines: dict[int, UserEngine],
    spread_feed: SpreadFeed,
    shutdown_event: asyncio.Event,
    *,
    heartbeat_owner: str | None = None,
    ready_event: asyncio.Event | None = None,
):
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    owner = heartbeat_owner or _new_worker_heartbeat_owner()
    heartbeat_task = asyncio.create_task(
        _command_heartbeat_loop(r, shutdown_event, owner)
    )

    try:
        if ready_event is not None:
            # Keep the host heartbeat alive while _main restores tenant
            # engines, but do not consume start/stop commands until the
            # in-memory registry and boot-time state are coherent.
            await ready_event.wait()
        while not shutdown_event.is_set():
            try:
                while True:
                    raw = await r.lpop(ADMIN_ENGINE_COMMAND_KEY)
                    if not raw:
                        break
                    try:
                        cmd = json.loads(raw)
                        uid = int(cmd.get("user_id", 0))
                        action = cmd.get("action")
                        if uid <= 0 or action not in {"start_user", "stop_user"}:
                            logger.warning("Ignoring invalid admin engine command: %s", cmd)
                            continue
                        if action == "start_user":
                            await _start_user_engine(
                                user_engines,
                                spread_feed,
                                uid,
                                source="admin command",
                            )
                        else:
                            await _stop_user_engine(
                                user_engines,
                                uid,
                                source="admin command",
                            )
                    except Exception:
                        logger.exception("Failed to process admin engine command")

                for uid in list(user_engines.keys()):
                    if uid == 0:
                        continue
                    key = f"engine:{uid}:commands"
                    while True:
                        raw = await r.lpop(key)
                        if not raw:
                            break
                        cmd = json.loads(raw)
                        if cmd.get("action") == "maintenance_pause":
                            # Maintenance is an admission gate, not a process
                            # stop. Keep this tenant's workers alive so
                            # existing positions can close, buy back and repay.
                            logger.info("Maintenance pause acknowledged for user %s", uid)
                        elif cmd["action"] == "stop":
                            await _stop_user_engine(
                                user_engines,
                                uid,
                                source="user command",
                            )
                        elif cmd["action"] == "start":
                            # A consumed start is acknowledged only after the
                            # tenant's ConfigLoader/Orchestrator has really
                            # started.  Failures are persisted as ERROR by the
                            # helper so the UI can retry instead of remaining
                            # in STARTING forever.
                            await _start_user_engine(
                                user_engines,
                                spread_feed,
                                uid,
                                source="user command",
                            )
                        elif cmd["action"] == "clear_account":
                            account_id = cmd.get("account_id")
                            if account_id and uid in user_engines:
                                orch = user_engines[uid].orchestrator
                                t = asyncio.create_task(
                                    _clear_account_positions(orch, account_id)
                                )
                                _clear_tasks.add(t)
                                t.add_done_callback(_clear_tasks.discard)
                        elif cmd["action"] == "restart_worker":
                            account_id = cmd.get("account_id")
                            if account_id and uid in user_engines:
                                orch = user_engines[uid].orchestrator
                                asyncio.create_task(orch.restart_worker(account_id))

                keys = await r.keys("engine:*:commands")
                for key in keys:
                    parts = key.split(":")
                    if len(parts) == 3 and parts[1].isdigit():
                        uid = int(parts[1])
                        if uid in user_engines:
                            continue
                        raw = await r.lpop(key)
                        if not raw:
                            continue
                        cmd = json.loads(raw)
                        if cmd["action"] == "start":
                            await _start_user_engine(
                                user_engines,
                                spread_feed,
                                uid,
                                source="inactive-user command",
                            )
                        elif cmd["action"] == "stop":
                            # The user may have no active UserEngine (for
                            # example after a crash or when all sub-accounts
                            # are disabled).  The command still represents a
                            # successful idempotent stop and must close the
                            # API's STOPPING transition instead of being
                            # silently discarded.
                            await _stop_user_engine(
                                user_engines,
                                uid,
                                source="inactive-user command",
                            )
                        else:
                            logger.warning(
                                "Ignoring unsupported command for inactive user %s: %s",
                                uid,
                                cmd.get("action"),
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Command consumer error: %s", e)

            await asyncio.sleep(3)
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        await _clear_worker_heartbeat(r, owner)
        await r.aclose()


async def _command_heartbeat_loop(redis_client, shutdown_event, owner: str):
    """Refresh the command-consumer liveness marker independently of work.

    Starting or stopping a tenant can involve DB/network awaits.  Keeping the
    heartbeat in the same coroutine as command dispatch made a healthy but
    busy consumer appear dead after the 30-second Redis TTL, causing the API
    to reject retries and the dashboard to show an error.  A small dedicated
    task keeps the marker fresh while preserving owner-scoped cleanup in the
    command loop's ``finally`` block.
    """
    while not shutdown_event.is_set():
        try:
            await redis_client.set(
                WORKER_HEARTBEAT_KEY,
                _worker_heartbeat_value(owner),
                ex=WORKER_HEARTBEAT_TTL,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # The API will fail closed when Redis is unavailable.  Retry on
            # the next tick rather than taking down the command consumer.
            logger.warning("Worker command heartbeat refresh failed", exc_info=True)
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            continue


async def _user_reconcile_loop(
    user_engines: dict[int, UserEngine],
    spread_feed: SpreadFeed,
    shutdown_event: asyncio.Event,
):
    while not shutdown_event.is_set():
        try:
            await asyncio.sleep(60)
            wanted_ids = _get_running_user_ids()
            running_ids = {uid for uid in user_engines if uid != 0}

            for uid in wanted_ids - running_ids:
                # Reconcile can be the path that recovers a fresh STARTING
                # intent after the initial boot scan.  Use the same guarded
                # lifecycle path as explicit commands so one broken tenant
                # cannot abort recovery for every other user.
                await _start_user_engine(
                    user_engines,
                    spread_feed,
                    uid,
                    source="periodic reconcile",
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"User reconcile error: {e}")


async def _heartbeat_loop(
    shutdown_event: asyncio.Event,
    user_engines: dict[int, UserEngine] | None = None,
):
    """Keep host and active user global states alive.

    Worker tasks publish their own ``sub:<id>`` heartbeats, but the API also
    reads ``scope=global,user_id=<uid>``.  Updating only the legacy NULL-user
    row left a running user's global row stale indefinitely after startup.
    """
    while not shutdown_event.is_set():
        try:
            await asyncio.sleep(10)
            db = SessionLocal()
            try:
                now = datetime.now(timezone.utc)
                active_users = {
                    uid for uid in (user_engines or {}) if uid != 0
                }
                states = db.query(EngineState).filter(
                    EngineState.scope == "global",
                ).all()
                for state in states:
                    # The NULL row is the process heartbeat.  User rows are
                    # refreshed only while their engine is actually present;
                    # a deliberately stopped user remains stopped/stale.
                    if state.user_id is None or state.user_id in active_users:
                        state.last_heartbeat = now
                db.commit()
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Heartbeat error: {e}")


async def _clear_account_positions_legacy(orchestrator: Orchestrator, account_id: int):
    worker = orchestrator._workers.get(account_id)
    if not worker or not worker._trading_client:
        logger.warning(f"No active worker for account {account_id}, cannot clear positions")
        return

    from engine.trading.order_executor import execute_close
    from engine.notify.feishu_sender import FeishuSender

    notifier = worker._notifier or FeishuSender()
    account_note = f"#{account_id}"
    try:
        account_info = await asyncio.to_thread(worker._load_account)
        if account_info:
            account_note = account_info["note"]
    except Exception:
        pass

    positions = await asyncio.to_thread(worker._load_open_positions)
    spread_feed = orchestrator.spread_feed

    for pos in positions:
        spread = spread_feed.get_symbol(pos.symbol)
        if not spread:
            # Account clearing is an explicit risk-reducing operation. It may
            # proceed with market legs even when the cached quote is absent;
            # the executor never uses this zero snapshot for maker pricing.
            from decimal import Decimal
            from engine.spread_feed import SpreadSnapshot
            spread = SpreadSnapshot(
                symbol=pos.symbol,
                spot_bid=Decimal("0"), spot_ask=Decimal("0"),
                fut_bid=Decimal("0"), fut_ask=Decimal("0"),
                spread_long=Decimal("0"), spread_short=Decimal("0"), ts=0,
            )
        try:
            fc = None
            if getattr(pos, "hedge_account", None) == "master":
                from engine.trading.master_client import get_master_futures_client
                fc = await get_master_futures_client(orchestrator.user_id)
            await execute_close(
                pos,
                spread,
                worker._trading_client,
                notifier,
                account_note,
                futures_client=fc,
                spot_order_mode="market",
                allow_emergency_close=True,
            )
            logger.info(f"Clear request completed for {pos.symbol} account {account_id}")
        except Exception as e:
            logger.error(f"Failed to clear position {pos.symbol}: {e}")

    await notifier.send("账户清理完成", f"账户: {account_note}\n已平仓 {len(positions)} 个持仓")
    logger.info(f"Account {account_id} clearing complete")


async def _clear_account_positions(orchestrator: Orchestrator, account_id: int):
    """Close an account without inventing an exchange acknowledgement.

    A missing worker or a failed close/repay leaves the position in its
    current lifecycle state.  Only a database row that is actually ``CLOSED``
    is counted as cleared; the active worker will retry the remaining rows.
    """
    from engine.models import Position as PositionModel
    from engine.notify.feishu_sender import FeishuSender

    def _load_positions():
        db = SessionLocal()
        try:
            return db.query(PositionModel).filter(
                PositionModel.sub_account_id == account_id,
                PositionModel.status.notin_(("CLOSED", "FAILED")),
            ).order_by(PositionModel.id).all()
        finally:
            db.close()

    def _mark_pending(position_ids=None, reason="account clear pending"):
        db = SessionLocal()
        try:
            q = db.query(PositionModel).filter(
                PositionModel.sub_account_id == account_id,
                PositionModel.status.notin_(("CLOSED", "FAILED")),
            )
            if position_ids:
                q = q.filter(PositionModel.id.in_(tuple(position_ids)))
            rows = q.all()
            for row in rows:
                row.error_message = reason
                row.retry_count = (row.retry_count or 0) + 1
            if rows:
                db.commit()
            return len(rows)
        finally:
            db.close()

    def _status(position_id):
        db = SessionLocal()
        try:
            return db.query(PositionModel.status).filter(
                PositionModel.id == position_id,
            ).scalar()
        finally:
            db.close()

    def _promote_idle(position_id):
        # A borrowed-but-not-hedged row has no exchange hedge to close.  Move
        # it into the existing repayment state machine instead of force-closing
        # the record locally.
        db = SessionLocal()
        try:
            changed = db.query(PositionModel).filter(
                PositionModel.id == position_id,
                PositionModel.status == "BORROWED_IDLE",
            ).update({
                "status": "PENDING_REPAY",
                "error_message": "account clear requested: borrowed idle position",
            }, synchronize_session=False)
            db.commit()
            return bool(changed)
        finally:
            db.close()

    async def _alert(notifier, account_note, action, detail):
        try:
            await notifier.notify_error(account_note, action, detail)
        except Exception:
            logger.exception("Unable to publish account-clear alert for %s", account_id)

    worker = orchestrator._workers.get(account_id)
    notifier = getattr(worker, "_notifier", None) if worker else None
    if notifier is None:
        notifier = FeishuSender()
        notifier.user_id = getattr(orchestrator, "user_id", None)

    positions = await asyncio.to_thread(_load_positions)
    if not worker or not worker._trading_client:
        reason = "account clear pending: worker unavailable; exchange close/repay not confirmed"
        pending = await asyncio.to_thread(_mark_pending, [p.id for p in positions], reason)
        logger.warning("No active worker for account %s; kept %s position(s) active", account_id, pending)
        if pending:
            await _alert(notifier, f"#{account_id}", "account clear", reason)
        return False

    account_note = f"#{account_id}"
    try:
        account_info = await asyncio.to_thread(worker._load_account)
        if account_info:
            account_note = account_info["note"]
    except Exception:
        pass

    # Disable new borrows for this worker while leaving risk-reducing loops
    # available to close/repay existing positions.
    if hasattr(worker, "_account_opening_enabled"):
        worker._account_opening_enabled = False

    from engine.trading.order_executor import execute_close, execute_repay

    spread_feed = orchestrator.spread_feed
    closed = 0
    pending_ids = []
    lock_failure_reasons: dict[int, str] = {}
    for pos in positions:
        try:
            async with account_operation_lock(
                worker._redis,
                account_id,
                pos.symbol,
                owner=f"account-clear:{orchestrator.user_id}:{pos.id}",
                ttl_sec=ACCOUNT_OPERATION_LOCK_TTL_SEC,
            ) as operation_lock_token:
                # A Worker/manual request may have advanced this row while the
                # clear task waited for the lock. Always branch on locked state.
                current = await asyncio.to_thread(_status, pos.id)
                if current in ("CLOSED", "FAILED"):
                    continue
                if current == "BORROWED_IDLE":
                    if not await asyncio.to_thread(_promote_idle, pos.id):
                        pending_ids.append(pos.id)
                        continue
                    current = "PENDING_REPAY"

                if current == "PENDING_REPAY":
                    try:
                        async with _maybe_master_symbol_lock(
                            worker._redis,
                            getattr(orchestrator, "user_id", None),
                            pos.symbol,
                            owner=f"account-clear:{orchestrator.user_id}:{pos.id}:master",
                        ):
                            await execute_repay(
                                pos,
                                worker._trading_client,
                                notifier,
                                account_note,
                                operation_lock_redis=worker._redis,
                                operation_lock_token=operation_lock_token,
                                operation_lock_ttl_sec=ACCOUNT_OPERATION_LOCK_TTL_SEC,
                            )
                    except Exception as exc:
                        logger.error(
                            "Failed to repay %s while clearing account %s: %s",
                            pos.symbol, account_id, exc,
                        )
                    if await asyncio.to_thread(_status, pos.id) == "CLOSED":
                        closed += 1
                    else:
                        pending_ids.append(pos.id)
                    continue

                # Transitional states (for example HEDGING or REPAYING) are
                # owned by the Worker state machine. Do not fabricate progress.
                if current != "OPEN":
                    pending_ids.append(pos.id)
                    continue

                spread = spread_feed.get_symbol(pos.symbol)
                if not spread:
                    # Emergency market close does not price from this snapshot.
                    from decimal import Decimal
                    from engine.spread_feed import SpreadSnapshot
                    spread = SpreadSnapshot(
                        symbol=pos.symbol,
                        spot_bid=Decimal("0"), spot_ask=Decimal("0"),
                        fut_bid=Decimal("0"), fut_ask=Decimal("0"),
                        spread_long=Decimal("0"), spread_short=Decimal("0"), ts=0,
                    )

                fc = None
                if getattr(pos, "hedge_account", None) == "master":
                    from engine.trading.master_client import get_master_futures_client
                    fc = await get_master_futures_client(orchestrator.user_id)
                async with _maybe_master_symbol_lock(
                    worker._redis,
                    getattr(orchestrator, "user_id", None),
                    pos.symbol,
                    owner=f"account-clear:{orchestrator.user_id}:{pos.id}:master",
                ):
                    completed = await execute_close(
                        pos,
                        spread,
                        worker._trading_client,
                        notifier,
                        account_note,
                        futures_client=fc,
                        spot_order_mode="market",
                        allow_emergency_close=True,
                        user_id=getattr(orchestrator, "user_id", None),
                        operation_lock_redis=worker._redis,
                        operation_lock_token=operation_lock_token,
                        operation_lock_ttl_sec=ACCOUNT_OPERATION_LOCK_TTL_SEC,
                    )
                # execute_close may return after unhedging while repayment
                # remains pending. Persisted status is the source of truth.
                if await asyncio.to_thread(_status, pos.id) == "CLOSED":
                    closed += 1
                    logger.info(
                        "Clear request completed for %s account %s",
                        pos.symbol, account_id,
                    )
                else:
                    pending_ids.append(pos.id)
                    logger.warning(
                        "Clear request for %s account %s remains active (executor=%s)",
                        pos.symbol, account_id, completed,
                    )
        except AccountOperationLockBusy as exc:
            reason = (
                f"account clear deferred: {pos.symbol} account operation lock busy "
                f"({exc.key})"
            )
            pending_ids.append(pos.id)
            lock_failure_reasons[pos.id] = reason
            logger.warning(reason)
        except AccountOperationLockUnavailable as exc:
            reason = (
                f"account clear blocked: {pos.symbol} coordination unavailable "
                f"({exc.key})"
            )
            pending_ids.append(pos.id)
            lock_failure_reasons[pos.id] = reason
            logger.error(reason)
        except Exception as exc:
            logger.error("Failed to clear position %s: %s", pos.symbol, exc)
            pending_ids.append(pos.id)

    if pending_ids:
        reason = "account clear pending: exchange close/repay not confirmed; retry required"
        generic_pending = [pid for pid in pending_ids if pid not in lock_failure_reasons]
        if generic_pending:
            await asyncio.to_thread(_mark_pending, generic_pending, reason)
        for position_id, lock_reason in lock_failure_reasons.items():
            await asyncio.to_thread(_mark_pending, [position_id], lock_reason)
        await _alert(
            notifier,
            account_note,
            "account clear",
            f"{len(pending_ids)} position(s) remain active; no terminal status was fabricated",
        )
        logger.warning(
            "Account %s clear incomplete: %s closed, %s still active",
            account_id, closed, len(pending_ids),
        )
        return False

    await notifier.send("Account clear complete", f"Account: {account_note}\nConfirmed closed/repaid: {closed}")
    logger.info("Account %s clearing complete: %s position(s) confirmed CLOSED", account_id, closed)
    return True


def run():
    asyncio.run(_main())
