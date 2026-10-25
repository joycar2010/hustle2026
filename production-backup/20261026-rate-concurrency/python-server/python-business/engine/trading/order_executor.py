import asyncio
import inspect
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP

from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from engine.models import Position, TradeLog, canonical_position_symbol
from engine.config_loader import GlobalRulesSnapshot
from engine.spread_feed import (
    SpreadFeed,
    SpreadSnapshot,
    is_spread_fresh,
)
from engine.freshness import configured_spread_max_age_ms
from engine.thresholds import upward_reached
from engine.trading.binance_trading import (
    BinanceAPIError,
    BinancePreSubmitRejected,
    BinanceTradingClient,
)
from engine.trading.borrow_coordination import (
    ACCOUNT_OPERATION_LOCK_TTL_SEC,
    AccountOperationLockBusy,
    AccountOperationLockUnavailable,
    account_operation_lock,
    account_operation_lock_key,
    borrow_capacity_key,
    borrow_failure_key,
    no_inventory_key,
    normalize_asset,
)
from engine.trading.quantity_calc import usdt_to_quantity, round_to_step
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)

# 逐币强制 enforce 观察名单:命中的币净期望闸一律按 enforce(E≤0拒开),无视全局 net_gate_mode 的 shadow。
# 用于对结构性负期望的币(如 FIL 恒 E<0 却被反复借)单独止血观察。默认 FILUSDT;运维改 systemd 环境变量
# NETGATE_ENFORCE_SYMBOLS=A,B 覆盖(设为空字符串=关闭强制),重启引擎生效。
_FORCE_ENFORCE_SYMBOLS = {
    x.strip().upper() for x in os.getenv("NETGATE_ENFORCE_SYMBOLS", "FILUSDT").split(",") if x.strip()
}

# 子账户→归属用户 缓存(归属不可变,进程级缓存;未命中查 DB 后回填)。
# 用于给 TradeLog 补 user_id —— 历史上 _log_trade 漏写该字段致流水「用户」列全空。
_uid_cache: dict[int, int | None] = {}


def _resolve_user_id(db, sub_account_id: int):
    if sub_account_id in _uid_cache:
        return _uid_cache[sub_account_id]
    uid = None
    try:
        from app.db.models import SubAccount
        uid = db.query(SubAccount.user_id).filter(SubAccount.id == sub_account_id).scalar()
    except Exception:
        return None  # 解析失败不缓存,下次再试;绝不因补 user_id 影响下单/记账
    _uid_cache[sub_account_id] = uid
    return uid


def _publish_balance_refresh(user_id):
    """借/还币成功后请求 BalancePusher 对该用户做一次「写后即时余额刷新」(事件驱动,绕开 10s 轮询),
    让 dashboard 子账户行的现币/借币/利息秒级刷新(问题4)。同步轻量 publish(与本模块 -3045 冷却同款);
    失败静默——余额最终仍由 10s 轮询兜底,绝不因刷新影响已成功的借/还币。"""
    if user_id is None:
        return
    try:
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        rc.publish("balance:refresh", str(user_id))
        rc.close()
    except Exception:
        pass


def _publish_position_update(pos, user_id=None, account_note=None):
    """状态跃迁即推:持仓状态每次变更 commit 后 publish position:updates → 后端 WS 按
    user_id 路由 → 前端 ws:position 秒级插行/更新/删行,替代「开仓后只能等 30s 兜底轮询
    或 F5 才可见」。payload 字段对齐 REST PositionResponse 的行渲染所需;user_id/sub_account_id
    用 int(与前端 balanceMap 的 account_id 同类型,get 才命中)。
    同步轻量 publish、失败静默:推送绝不影响交易主流程,REST 轮询仍兜底。"""
    try:
        import json as _json
        uid = user_id if user_id is not None else getattr(pos, "user_id", None)
        if uid is None:
            uid = _uid_cache.get(pos.sub_account_id)

        def _s(v):
            return str(v) if v is not None else None

        payload = {
            "id": pos.id,
            "user_id": int(uid) if uid is not None else None,
            "sub_account_id": int(pos.sub_account_id),
            "account_note": account_note,
            "symbol": pos.symbol,
            "base_asset": pos.base_asset,
            "status": pos.status,
            "borrow_qty": _s(pos.borrow_qty),
            "borrow_usdt_amount": _s(getattr(pos, "borrow_usdt_amount", None)),
            "borrowed_at": (
                pos.borrowed_at.isoformat()
                if getattr(pos, "borrowed_at", None)
                else None
            ),
            "spot_sell_price": _s(pos.spot_sell_price),
            "futures_long_qty": _s(pos.futures_long_qty),
            "futures_long_price": _s(pos.futures_long_price),
            "open_spread": _s(pos.open_spread),
            "close_spread": _s(pos.close_spread),
            "open_usdt_amount": _s(pos.open_usdt_amount),
            "realized_pnl": _s(pos.realized_pnl),
            "error_message": pos.error_message,
            "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
            "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
            "created_at": pos.created_at.isoformat() if getattr(pos, "created_at", None) else None,
            "updated_at": pos.updated_at.isoformat() if getattr(pos, "updated_at", None) else None,
        }
        import redis as _r
        from app.config import settings as _s2
        rc = _r.from_url(_s2.redis_url, decode_responses=True)
        rc.publish("position:updates", _json.dumps(payload))
        rc.close()
    except Exception:
        pass


TAKER_FEE_RATE = Decimal("0.00075")
FEE_BUFFER = Decimal("1.0015")
# Keep the borrow confirmation hard gate aligned with the Rust local-receive
# timestamp contract.  A legacy snapshot with no per-leg receive fields fails
# closed instead of falling back to exchange event time.
BORROW_FRESH_MS = configured_spread_max_age_ms()
BORROW_SUBMITTING = "BORROW_SUBMITTING"
BORROW_OUTCOME_UNKNOWN = "BORROW_OUTCOME_UNKNOWN"
BORROW_SUBMISSION_STARTED = "started"
BORROW_SUBMISSION_FINISHED = "finished"
# ── C2 反插针二次确认 (对冲前 REST 交叉核对) ──
# 卖现货做空+合约做多前,用一次独立的 REST bookTicker 复核 WS 快照点差是否真实。
# WS 单源(Rust 引擎→Redis spreads)若某腿被插针,重采同一路抓不住持久幻价;REST 是
# 唯一不经该链路的独立源。任一轴偏离容差 / 取价失败 / 超时 → 判幻价,fail-closed 跳过
# 对冲(留 BORROWED_IDLE 下轮重试)。纯验证闸,不参与下单定价;env 可关,改后重启引擎生效。
HEDGE_REST_CONFIRM_ENABLED = os.getenv(
    "HEDGE_REST_CONFIRM_ENABLED", "1"
).strip().lower() not in ("0", "false", "no", "off", "")
try:
    HEDGE_REST_CONFIRM_TOL_PP = Decimal(os.getenv("HEDGE_REST_CONFIRM_TOL_PP", "0.6"))
except (InvalidOperation, ValueError):
    HEDGE_REST_CONFIRM_TOL_PP = Decimal("0.6")
try:
    HEDGE_REST_CONFIRM_TIMEOUT_SEC = float(os.getenv("HEDGE_REST_CONFIRM_TIMEOUT_SEC", "1.5"))
except (TypeError, ValueError):
    HEDGE_REST_CONFIRM_TIMEOUT_SEC = 1.5
# ── Multi-tranche (多笔独立对冲) 建仓窗口不变量 ──
# A borrow is *establishing* a tranche until it is either hedged to ``OPEN``
# or has entered the closing/terminal path.  At most one establishing row may
# exist per (sub_account, canonical_symbol) at a time, because:
#   1. Cap accuracy — while a borrow is PENDING_BORROW/BORROW_SUBMITTING the
#      principal is not yet in the database, so a parallel borrow would
#      under-count the cumulative per-slot cap and over-borrow.
#   2. Top-up integrity — the BORROWED_IDLE top-up path adds debt in place and
#      requires exactly one BORROWED_IDLE row for the symbol.
#   3. Churn bound — one opening pipeline at a time stops a flapping spread
#      from spawning dust tranches.
# Everything past OPEN is exempt: a hedged (持仓) OPEN tranche, every closing
# state (CLOSING_FUTURES/FUTURES_CLOSED/CLOSING_SPOT/SPOT_BOUGHT/PENDING_REPAY/
# REPAYING) and every terminal row (CLOSED/FAILED/CANCELLED/CANCELED) no
# longer serialize a new borrow, so an OPEN or closing tranche may coexist
# with a fresh independent tranche up to the shared cap.
#
# The invariant is expressed as an *allow-set* (NON_ESTABLISHING_STATUSES):
# a row conflicts unless its status is in this set.  Stated negatively, any
# status NOT listed here — including any opening-pipeline state and any future
# status added without updating this list — defaults to *blocking*, which is
# the fail-safe direction.  This tuple is the single source of truth shared by
# ``_first_borrow_conflict`` and the partial unique index migration
# (f3a4b5c6d7e8); the two MUST stay byte-for-byte in lockstep.
NON_ESTABLISHING_STATUSES = (
    "OPEN",
    "CLOSING_FUTURES",
    "FUTURES_CLOSED",
    "CLOSING_SPOT",
    "SPOT_BOUGHT",
    "PENDING_REPAY",
    "REPAYING",
    "CLOSED",
    "FAILED",
    "CANCELLED",
    "CANCELED",
)
TOPUP_CONFIRM_RESERVE_SEC = 30.0
TOPUP_SUBMISSION_WINDOW_SEC = max(
    0.0,
    float(ACCOUNT_OPERATION_LOCK_TTL_SEC) - TOPUP_CONFIRM_RESERVE_SEC,
)


def _topup_clock() -> float:
    """Return the monotonic clock used to fence top-up submissions."""
    return time.monotonic()


def _topup_before_submission_deadline(submission_deadline: float) -> bool:
    """Fail closed when the lock's reserved debt-confirmation window begins."""
    try:
        return _topup_clock() < float(submission_deadline)
    except (TypeError, ValueError, ArithmeticError):
        logger.warning("Invalid top-up submission deadline: %r", submission_deadline)
        return False

# A process can die between the DB lifecycle CAS and the corresponding
# Binance request.  These states are intentionally recovered only after a
# quiet window longer than the Redis operation-lock TTL.  Recovery is
# exchange-read driven and fail-closed; a missing/ambiguous response leaves
# the row in place for the next pass instead of inventing a terminal state.
TRANSITIONAL_POSITION_STATUSES = (
    "HEDGING", "SPOT_SOLD", "CLOSING_FUTURES", "FUTURES_CLOSED",
    "CLOSING_SPOT", "SPOT_BOUGHT",
)
RECOVERY_FUTURES_OWNING_STATUSES = (
    "HEDGING", "SPOT_SOLD", "OPEN", "CLOSING_FUTURES",
    # Buy-first close contract: these states still own their futures leg
    # (spot buy-back runs BEFORE the reduce-only futures close). Without
    # them, stacked sibling tranches sharing one master net position all
    # fail the owned-quantity match and hold each other forever.
    "CLOSING_SPOT", "SPOT_BOUGHT",
)
TRANSITIONAL_RECOVERY_STALE_SEC = max(
    180, int(ACCOUNT_OPERATION_LOCK_TTL_SEC) + 60
)
RECOVERY_EPSILON = Decimal("0.00000001")


async def _emit_borrow_submission_event(callback, event: str) -> None:
    """Publish a best-effort UI event without making Redis part of execution."""
    if callback is None:
        return
    try:
        result = callback(event)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.warning("Borrow submission event callback failed: %s", event, exc_info=True)


async def _finish_borrow_submission_event(callback) -> None:
    """Complete the matching ``finished`` event before propagating cancellation."""
    if callback is None:
        return
    task = asyncio.create_task(
        _emit_borrow_submission_event(callback, BORROW_SUBMISSION_FINISHED)
    )
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    if task.cancelled():
        raise asyncio.CancelledError
    task.result()
    if cancelled:
        raise asyncio.CancelledError


def _pre_submit_guard_allows(callback) -> bool:
    """Fail closed when a caller's decision snapshot has been superseded."""
    if callback is None:
        return True
    try:
        return bool(callback())
    except Exception:
        logger.warning("Borrow pre-submit generation guard failed", exc_info=True)
        return False


def _pre_submit_kwargs(callback) -> dict:
    return {"pre_submit_guard": callback} if callback is not None else {}


def _borrow_submit_guard(
    pre_submit_guard,
    inventory_guard,
    quantity: Decimal,
    *,
    position_guard=None,
    operation_lock_guard=None,
    new_action_guard=None,
):
    """Combine rule fencing with a quantity-aware inventory assertion.

    The returned zero-argument callback is compatible with
    ``BinanceTradingClient._request`` and is evaluated at its final HTTP
    boundary.  Keeping ``inventory_guard`` separate until quantity sizing is
    complete prevents a merely positive snapshot from authorizing a larger
    borrow request.
    """
    if (
        inventory_guard is None
        and position_guard is None
        and operation_lock_guard is None
        and new_action_guard is None
    ):
        return pre_submit_guard

    def allowed() -> bool:
        allowed.rejection_reason = None
        if not _pre_submit_guard_allows(pre_submit_guard):
            allowed.rejection_reason = "pre_submit"
            return False
        if new_action_guard is not None:
            try:
                if not new_action_guard():
                    allowed.rejection_reason = "pause"
                    return False
            except Exception:
                logger.warning("Borrow pre-submit pause guard failed", exc_info=True)
                allowed.rejection_reason = "pause"
                return False
        if position_guard is not None:
            try:
                position_allowed = bool(position_guard())
            except Exception:
                logger.warning(
                    "Borrow pre-submit active-position guard failed",
                    exc_info=True,
                )
                allowed.rejection_reason = "active_position"
                return False
            if not position_allowed:
                allowed.rejection_reason = "active_position"
                return False
        if operation_lock_guard is not None:
            try:
                if not operation_lock_guard():
                    allowed.rejection_reason = "operation_lock"
                    return False
            except Exception:
                logger.warning(
                    "Borrow pre-submit operation-lock guard failed",
                    exc_info=True,
                )
                allowed.rejection_reason = "operation_lock"
                return False
        if inventory_guard is not None:
            try:
                inventory_allowed = bool(inventory_guard(quantity))
            except Exception:
                logger.warning(
                    "Borrow pre-submit inventory guard failed for quantity %s",
                    quantity,
                    exc_info=True,
                )
                allowed.rejection_reason = "inventory"
                return False
            if not inventory_allowed:
                allowed.rejection_reason = "inventory"
                return False
        return True

    allowed.rejection_reason = None

    # ``BinanceTradingClient`` invokes the ordinary callback synchronously at
    # its final HTTP boundary.  A Redis asyncio client cannot be queried from
    # that synchronous callback, so an operation-lock guard may expose an
    # async validator.  The client awaits it immediately before sending.
    async_check = getattr(operation_lock_guard, "async_check", None)
    if callable(async_check):
        async def _async_allowed():
            if not allowed():
                return False
            try:
                return bool(await async_check())
            except Exception:
                logger.warning(
                    "Borrow async operation-lock guard failed",
                    exc_info=True,
                )
                return False

        allowed.async_check = _async_allowed
    return allowed


def _inventory_guard_rejected(callback) -> bool:
    return getattr(callback, "rejection_reason", None) == "inventory"


def _active_position_guard_rejected(callback) -> bool:
    return getattr(callback, "rejection_reason", None) == "active_position"


def _operation_lock_guard_rejected(callback) -> bool:
    return getattr(callback, "rejection_reason", None) == "operation_lock"


def _pause_guard_rejected(callback) -> bool:
    return getattr(callback, "rejection_reason", None) == "pause"


def _symbol_is_paused(user_id: int | None, symbol: str) -> bool:
    """Fail-closed tenant admission check used at final exchange boundaries."""
    from engine.pause_gate import is_symbol_paused_sync

    return is_symbol_paused_sync(user_id, symbol)


def _first_borrow_conflict(
    db,
    sub_account_id: int,
    symbol: str,
    *,
    exclude_position_id: int | None = None,
    allow_open_increment: bool = False,
):
    """Return a row that must serialize a new borrow for this account/symbol.

    Only a tranche still *establishing* itself serializes a new borrow: any row
    whose status is **not** in :data:`NON_ESTABLISHING_STATUSES` (i.e. the
    opening pipeline PENDING_BORROW → BORROW_SUBMITTING →
    BORROW_OUTCOME_UNKNOWN → BORROWED(_IDLE) → HEDGING → SPOT_SOLD).  Two
    establishing tranches may never overlap for the same account/symbol: the
    second borrow's principal is not yet in the database while the first is
    in-flight, so a parallel borrow would under-count the cumulative cap and
    over-borrow, and the BORROWED_IDLE top-up path requires a unique idle row.

    A hedged ``OPEN`` tranche, any closing-side tranche
    (CLOSING_FUTURES/FUTURES_CLOSED/CLOSING_SPOT/SPOT_BOUGHT/PENDING_REPAY/
    REPAYING) and every terminal row are **not** conflicts: an independent
    tranche (多笔独立对冲) may be borrowed alongside them, bounded only by the
    shared per-slot cap that the worker enforces separately.  The legacy
    ``allow_open_increment`` argument is retained for source compatibility but
    is now redundant — ``OPEN`` is never a conflict regardless of its value.
    """
    canonical = canonical_position_symbol(symbol)
    if not canonical:
        return None
    from sqlalchemy import func

    # Lifecycle writes use uppercase values, but legacy/manual rows may not.
    # A casing difference must never bypass the establishing-window invariant.
    # Expressed as NOT IN (allow-set) so any opening-pipeline state — and any
    # unknown/future status — fails safe by continuing to serialize borrows.
    query = db.query(Position).filter(
        Position.sub_account_id == sub_account_id,
        func.upper(func.trim(func.coalesce(Position.status, ""))).notin_(
            NON_ESTABLISHING_STATUSES
        ),
    )
    canonical_column = getattr(Position, "canonical_symbol", None)
    if canonical_column is not None:
        # The migration backfills every production row.  The symbol fallback
        # keeps rolling upgrades and lightweight test repositories compatible.
        # Legacy rows may still spell the pair as ``btc-usdt``/``BTC_USDT``
        # while the new column is NULL, so normalize those separators in SQL
        # instead of comparing only ``upper(symbol)``.
        from sqlalchemy import or_
        def _normalized_pair(column):
            return func.upper(
                func.replace(
                    func.replace(
                        func.replace(column, "-", ""),
                        "_",
                        "",
                    ),
                    " ",
                    "",
                )
            )

        normalized_legacy = _normalized_pair(Position.symbol)
        normalized_canonical = _normalized_pair(canonical_column)
        legacy_keys = (canonical, canonical[:-4])
        # During a rolling upgrade (or after a legacy/manual direct SQL
        # write), the denormalized canonical column can be present but stale
        # while ``symbol`` still identifies the real pair.  Match both
        # representations unconditionally so a bad canonical value cannot
        # authorize a second active lifecycle before the database migration
        # has rebuilt the partial unique index.
        query = query.filter(
            or_(
                normalized_canonical.in_(legacy_keys),
                normalized_legacy.in_(legacy_keys),
            )
        )
    else:
        query = query.filter(Position.symbol == canonical)
    if exclude_position_id is not None:
        query = query.filter(Position.id != exclude_position_id)
    order_by = getattr(query, "order_by", None)
    if callable(order_by):
        query = order_by(Position.id.asc())
    conflict = query.first()
    # Real SQL applies the exclusion above.  Keep the identity check as a
    # defensive fallback for lightweight repositories/test doubles and for
    # callers that hand back a stale in-memory instance of the row being
    # guarded; the current row must never conflict with itself.
    if (
        conflict is not None
        and exclude_position_id is not None
        and getattr(conflict, "id", None) == exclude_position_id
    ):
        return None
    return conflict


class _OperationLockGuard:
    """Synchronous + asynchronous ownership fence for a Redis lease."""

    def __init__(
        self,
        redis_client,
        sub_account_id: int,
        symbol: str,
        token: str,
        *,
        ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
    ):
        self.redis_client = redis_client
        self.key = account_operation_lock_key(sub_account_id, symbol)
        self.token = str(token or "")
        # Borrow workers may deliberately acquire a longer lease to cover a
        # configured confirmation delay; renewal must not silently shorten it
        # back to the default and reject a valid long-delay operation.
        try:
            self.ttl_sec = max(1, int(ttl_sec))
        except (TypeError, ValueError, ArithmeticError):
            self.ttl_sec = ACCOUNT_OPERATION_LOCK_TTL_SEC
        self.valid = bool(self.token and redis_client is not None)

    def __call__(self) -> bool:
        # The async validator refreshes this bit immediately before HTTP.  A
        # synchronous callback must never turn an absent token into ownership.
        return self.valid

    async def async_check(self) -> bool:
        """Atomically verify and renew the lease before a Binance request."""
        if not self.valid:
            return False
        # A final ownership check is mandatory. Redis-compatible clients must
        # expose EVAL so compare-and-renew happens atomically inside Redis; a
        # local token, a plain GET, or a best-effort EXPIRE is not a fencing
        # primitive and must never authorize a Binance write.
        if not callable(getattr(self.redis_client, "eval", None)):
            self.valid = False
            return False
        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "redis.call('expire', KEYS[1], ARGV[2]); return 1 "
            "else return 0 end"
        )
        try:
            result = self.redis_client.eval(
                script,
                1,
                self.key,
                self.token,
                str(self.ttl_sec),
            )
            if inspect.isawaitable(result):
                result = await result
            # Redis normally returns an integer 0/1 for this script.  A few
            # proxies/adapters decode integer replies as strings, where
            # ``bool('0')`` is unfortunately true.  Treat only explicit
            # success values as ownership; every other representation fails
            # closed at the final Binance boundary.
            if isinstance(result, (bytes, bytearray)):
                result = result.decode("ascii", errors="ignore")
            if isinstance(result, str):
                self.valid = result.strip().lower() in {"1", "true"}
            elif isinstance(result, bool):
                self.valid = result
            elif isinstance(result, (int, float)):
                self.valid = result == 1
            else:
                self.valid = False
        except Exception:
            self.valid = False
            logger.warning(
                "Unable to verify account operation lock %s before HTTP",
                self.key,
                exc_info=True,
            )
        return self.valid


def _fresh_topup_position_allows_submission(
    position_id: int,
    sub_account_id: int,
    symbol: str,
    *,
    user_id: int | None = None,
) -> bool:
    """Check top-up ownership using a new database session.

    This guard runs immediately before the Binance HTTP boundary.  It must not
    reuse the executor's identity map because a hedge/manual action may have
    moved the Position while a submission callback was running.
    """
    status_db = None
    try:
        status_db = SessionLocal()
        canonical = canonical_position_symbol(symbol)
        if not canonical:
            return False
        from sqlalchemy import func, or_

        normalized_symbol = func.upper(
            func.replace(
                func.replace(func.replace(Position.symbol, "-", ""), "_", ""),
                " ",
                "",
            )
        )
        normalized_canonical = func.upper(
            func.replace(
                func.replace(
                    func.replace(Position.canonical_symbol, "-", ""),
                    "_",
                    "",
                ),
                " ",
                "",
            )
        )
        predicates = [
            Position.id == position_id,
            Position.sub_account_id == sub_account_id,
            Position.status.in_(("BORROWED_IDLE", BORROW_SUBMITTING)),
            or_(
                normalized_symbol.in_((canonical, canonical[:-4])),
                normalized_canonical.in_((canonical, canonical[:-4])),
            ),
        ]
        expected_user = user_id
        if expected_user is None:
            expected_user = _resolve_user_id(status_db, sub_account_id)
        # A known tenant must be part of the final predicate.  If a legacy
        # account cannot be resolved, only a NULL-owned legacy row may pass;
        # a row belonging to another tenant is never accepted implicitly.
        if expected_user is not None:
            predicates.append(Position.user_id == expected_user)
        else:
            predicates.append(Position.user_id.is_(None))
        try:
            row = status_db.query(
                Position.id,
                Position.sub_account_id,
                Position.status,
                Position.symbol,
                Position.canonical_symbol,
                Position.user_id,
            ).filter(*predicates).first()
        except TypeError:
            # Lightweight repositories used by rolling-upgrade tests may only
            # accept a mapped class in query(). Production uses the scalar
            # projection above.
            row = status_db.query(Position).filter(*predicates).first()
        if row is None:
            return False
        if canonical_position_symbol(getattr(row, "symbol", "")) != canonical:
            return False
        if expected_user is not None:
            try:
                if int(getattr(row, "user_id", -1)) != int(expected_user):
                    return False
            except (TypeError, ValueError, ArithmeticError):
                return False
        return _first_borrow_conflict(
            status_db,
            sub_account_id,
            symbol,
            exclude_position_id=position_id,
            allow_open_increment=False,
        ) is None
    except Exception:
        logger.warning(
            "Top-up fresh position guard failed for position %s",
            position_id,
            exc_info=True,
        )
        return False
    finally:
        if status_db is not None:
            try:
                status_db.close()
            except Exception:
                logger.warning(
                    "Unable to close top-up status session for position %s",
                    position_id,
                    exc_info=True,
                )


def _fresh_hedge_position_allows_submission(
    position_id: int,
    sub_account_id: int,
    symbol: str,
    *,
    user_id: int | None = None,
    hedge_account: str | None = None,
    expected_statuses=("HEDGING", "SPOT_SOLD"),
) -> bool:
    """Read the lifecycle row immediately before an opening hedge POST.

    The ORM object held by a Worker can be stale after a manual action or a
    replacement Worker acquires the same account lease.  A final callback must
    therefore validate the durable identity and tenant, not merely the Redis
    token or the cached status.  ``expected_statuses`` covers the paired spot /
    futures opening window: the first spot request starts in ``HEDGING`` and
    subsequent futures/spot batches run while the row is ``SPOT_SOLD``.
    """
    status_db = None
    try:
        status_db = SessionLocal()
        canonical = canonical_position_symbol(symbol)
        if not canonical:
            return False
        from sqlalchemy import func, or_

        normalized_symbol = func.upper(
            func.replace(
                func.replace(func.replace(Position.symbol, "-", ""), "_", ""),
                " ",
                "",
            )
        )
        normalized_canonical = func.upper(
            func.replace(
                func.replace(
                    func.replace(Position.canonical_symbol, "-", ""),
                    "_",
                    "",
                ),
                " ",
                "",
            )
        )
        predicates = [
            Position.id == position_id,
            Position.sub_account_id == sub_account_id,
            Position.status.in_(tuple(expected_statuses)),
            or_(
                normalized_symbol.in_((canonical, canonical[:-4])),
                normalized_canonical.in_((canonical, canonical[:-4])),
            ),
        ]
        expected_user = user_id
        if expected_user is None:
            expected_user = _resolve_user_id(status_db, sub_account_id)
        if expected_user is not None:
            predicates.append(Position.user_id == expected_user)
        else:
            predicates.append(Position.user_id.is_(None))
        if hedge_account is not None:
            predicates.append(Position.hedge_account == hedge_account)
        try:
            row = status_db.query(
                Position.id,
                Position.sub_account_id,
                Position.status,
                Position.symbol,
                Position.canonical_symbol,
                Position.user_id,
                Position.hedge_account,
            ).filter(*predicates).first()
        except TypeError:
            row = status_db.query(Position).filter(*predicates).first()
        if row is None:
            return False
        try:
            if int(getattr(row, "id", -1)) != int(position_id):
                return False
            if int(getattr(row, "sub_account_id", -1)) != int(sub_account_id):
                return False
        except (TypeError, ValueError, ArithmeticError):
            return False
        if str(getattr(row, "status", "") or "").strip().upper() not in {
            str(value).strip().upper() for value in expected_statuses
        }:
            return False
        if canonical_position_symbol(getattr(row, "symbol", "")) != canonical:
            return False
        if expected_user is not None:
            try:
                if int(getattr(row, "user_id", -1)) != int(expected_user):
                    return False
            except (TypeError, ValueError, ArithmeticError):
                return False
        if hedge_account is not None and getattr(row, "hedge_account", None) != hedge_account:
            return False
        # This is a rolling-upgrade defence in addition to the database
        # partial unique index: a stale row cannot authorize a second active
        # lifecycle while the migration is still being applied.
        return (
            _first_borrow_conflict(
                status_db,
                sub_account_id,
                canonical,
                exclude_position_id=position_id,
                allow_open_increment=False,
            )
            is None
        )
    except Exception:
        logger.warning(
            "Hedge fresh position guard failed for position %s",
            position_id,
            exc_info=True,
        )
        return False
    finally:
        if status_db is not None:
            try:
                status_db.close()
            except Exception:
                logger.warning(
                    "Unable to close hedge status session for position %s",
                    position_id,
                    exc_info=True,
                )


def _fresh_borrow_position_allows_submission(
    position_id: int,
    sub_account_id: int,
    symbol: str,
    *,
    user_id: int | None = None,
    db=None,
) -> bool:
    """Verify that this borrow call still owns its lifecycle row.

    ``execute_borrow`` performs several private reads before the final Binance
    POST.  A manual/API action or a stale worker can move the row to a
    terminal/unknown state during that window.  Read scalar identity/status
    columns rather than trusting a cached ORM instance, so a row that no
    longer belongs to this call cannot authorize a request. Require both the
    row identity and the tenant/account/symbol key to match.
    The second active-row check protects rolling deployments before the partial
    unique index has reached every writer.
    """
    canonical = canonical_position_symbol(symbol)
    if not canonical:
        return False
    # The executor passes its lifecycle session so test doubles and the
    # surrounding transaction keep their normal resource ownership.  Direct
    # callers still get an isolated session.  The query below selects scalar
    # columns only, so it observes the current database row without expiring
    # or overwriting unrelated uncommitted ORM fields on the executor object.
    status_db = db
    owns_session = status_db is None
    try:
        if status_db is None:
            status_db = SessionLocal()
        from sqlalchemy import func, or_

        status_expr = func.upper(func.trim(func.coalesce(Position.status, "")))
        normalized_symbol = func.upper(
            func.replace(
                func.replace(
                    func.replace(Position.symbol, "-", ""),
                    "_",
                    "",
                ),
                " ",
                "",
            )
        )
        predicates = [
            Position.id == position_id,
            Position.sub_account_id == sub_account_id,
            status_expr.in_(("PENDING_BORROW", BORROW_SUBMITTING)),
        ]
        canonical_column = getattr(Position, "canonical_symbol", None)
        if canonical_column is not None:
            normalized_canonical = func.upper(
                func.replace(
                    func.replace(
                        func.replace(canonical_column, "-", ""),
                        "_",
                        "",
                    ),
                    " ",
                    "",
                )
            )
            predicates.append(
                or_(
                    normalized_symbol.in_((canonical, canonical[:-4])),
                    normalized_canonical.in_((canonical, canonical[:-4])),
                )
            )
        else:
            predicates.append(normalized_symbol.in_((canonical, canonical[:-4])))
        # A newly created Position always carries the resolved tenant.  A
        # caller that supplies a tenant must never be allowed to use a legacy
        # NULL/mismatched row as its submission lease.
        if user_id is not None:
            predicates.append(Position.user_id == user_id)
        # Do not load the mapped Position: a mapped refresh can discard
        # legitimate uncommitted fields on the caller's instance.  Selecting
        # the identity/status columns still gives a statement-level fresh
        # read under the normal READ COMMITTED transaction contract.
        try:
            query = status_db.query(
                Position.id,
                Position.sub_account_id,
                Position.status,
                Position.symbol,
                Position.canonical_symbol,
                Position.user_id,
            )
        except TypeError:
            # Lightweight rolling-upgrade repositories may only accept a
            # single mapped model in ``query()``.  They still receive the
            # same predicates; production SQLAlchemy uses the scalar path.
            query = status_db.query(Position)
        query = query.filter(*predicates)
        owned = query.first()
        if owned is None:
            return False
        try:
            if int(getattr(owned, "id", -1)) != int(position_id):
                return False
            if int(getattr(owned, "sub_account_id", -1)) != int(sub_account_id):
                return False
        except (TypeError, ValueError, ArithmeticError):
            return False
        owned_status = str(getattr(owned, "status", "") or "").strip().upper()
        if owned_status not in {"PENDING_BORROW", BORROW_SUBMITTING}:
            return False
        if user_id is not None:
            try:
                if int(getattr(owned, "user_id", -1)) != int(user_id):
                    return False
            except (TypeError, ValueError, ArithmeticError):
                return False
        if canonical_position_symbol(getattr(owned, "symbol", "")) != canonical:
            return False
        return (
            _first_borrow_conflict(
                status_db,
                sub_account_id,
                canonical,
                exclude_position_id=position_id,
                allow_open_increment=False,
            )
            is None
        )
    except Exception:
        logger.warning(
            "Borrow fresh position guard failed for position %s",
            position_id,
            exc_info=True,
        )
        return False
    finally:
        if status_db is not None and owns_session:
            try:
                status_db.close()
            except Exception:
                logger.warning(
                    "Unable to close borrow status session for position %s",
                    position_id,
                    exc_info=True,
                )


def _cas_topup_position(
    db,
    position: Position,
    expected_status: str,
    values: dict,
) -> bool:
    """Conditionally update a top-up row without overwriting a newer state."""
    updated = db.query(Position).filter(
        Position.id == position.id,
        Position.sub_account_id == position.sub_account_id,
        Position.symbol == position.symbol,
        Position.status == expected_status,
    ).update(values, synchronize_session=False)
    db.commit()
    try:
        db.refresh(position)
    except Exception:
        logger.warning(
            "Unable to refresh top-up position %s after CAS",
            position.id,
            exc_info=True,
        )
        return False
    return updated == 1


def _hedge_position_identity_query(
    db,
    position_id: int,
    sub_account_id: int,
    symbol: str,
    *,
    user_id: int | None,
    expected_statuses=("SPOT_SOLD",),
    hedge_account: str | None = None,
):
    """Build a fresh, tenant-scoped query for the final hedge transition.

    The ORM instance held by ``execute_hedge`` may be stale after a spot or
    futures callback.  Every final lifecycle write therefore has to prove the
    complete Position identity again.  In particular, filtering only by the
    numeric id is unsafe for a rolling worker/API deployment that has an old
    object in memory or a malformed legacy row.
    """
    from sqlalchemy import func, or_

    canonical = canonical_position_symbol(symbol)
    if not canonical:
        return None
    status_expr = func.upper(func.trim(func.coalesce(Position.status, "")))
    normalized = func.upper(
        func.replace(
            func.replace(
                func.replace(Position.symbol, "-", ""),
                "_",
                "",
            ),
            " ",
            "",
        )
    )
    predicates = [
        Position.id == position_id,
        Position.sub_account_id == sub_account_id,
        status_expr.in_(tuple(str(value).upper() for value in expected_statuses)),
        normalized.in_((canonical, canonical[:-4])),
    ]
    canonical_column = getattr(Position, "canonical_symbol", None)
    if canonical_column is not None:
        normalized_canonical = func.upper(
            func.replace(
                func.replace(
                    func.replace(canonical_column, "-", ""),
                    "_",
                    "",
                ),
                " ",
                "",
            )
        )
        # Require the persisted canonical key to agree when it exists.  The
        # OR retains compatibility with a legacy row during the short rolling
        # window before the migration has backfilled the new column.
        predicates.append(
            or_(canonical_column.is_(None), normalized_canonical.in_((canonical, canonical[:-4])))
        )
    if user_id is None:
        predicates.append(Position.user_id.is_(None))
    else:
        predicates.append(Position.user_id == user_id)
    if hedge_account is not None:
        predicates.append(Position.hedge_account == hedge_account)
    return db.query(Position).filter(*predicates)


def _fresh_hedge_position_allows_open(
    db,
    position_id: int,
    sub_account_id: int,
    symbol: str,
    *,
    user_id: int | None,
    hedge_account: str,
) -> bool:
    """Check the final Position identity and active-row ownership.

    This is intentionally a new query at the commit boundary.  A sibling
    worker, manual endpoint, or recovery pass may have changed the row after
    the opening fills were submitted.  The partial unique index is the hard
    database fence, while this read gives a useful fail-closed result on
    rolling databases before that index is installed.
    """
    try:
        row = _hedge_position_identity_query(
            db,
            position_id,
            sub_account_id,
            symbol,
            user_id=user_id,
            expected_statuses=("SPOT_SOLD",),
            hedge_account=hedge_account,
        ).first()
        if row is None:
            return False
        return (
            _first_borrow_conflict(
                db,
                sub_account_id,
                symbol,
                exclude_position_id=position_id,
                allow_open_increment=False,
            )
            is None
        )
    except Exception:
        logger.warning(
            "Final hedge Position identity check failed for %s/%s",
            sub_account_id,
            symbol,
            exc_info=True,
        )
        return False


def _cas_hedge_open(
    db,
    position: Position,
    *,
    sub_account_id: int,
    symbol: str,
    user_id: int | None,
    hedge_account: str,
    values: dict,
) -> bool:
    """Commit ``SPOT_SOLD -> OPEN`` only for the exact current lifecycle row."""
    query = _hedge_position_identity_query(
        db,
        getattr(position, "id", None),
        sub_account_id,
        symbol,
        user_id=user_id,
        expected_statuses=("SPOT_SOLD",),
        hedge_account=hedge_account,
    )
    try:
        updated = query.update(values, synchronize_session=False)
        if updated != 1:
            db.rollback()
            return False
        db.commit()
        # The caller publishes fields from this row immediately afterwards;
        # refresh it so no stale identity-map values escape in the event.
        db.refresh(position)
        return True
    except IntegrityError:
        # A concurrent writer winning the active-position unique index must
        # never be turned into an unowned OPEN row.
        db.rollback()
        logger.warning(
            "Final hedge OPEN CAS rejected by active-position uniqueness for %s",
            symbol,
        )
        return False
    except Exception:
        db.rollback()
        logger.warning("Final hedge OPEN CAS failed for %s", symbol, exc_info=True)
        return False


def _cas_hedge_spot_sold(
    db,
    position: Position,
    *,
    sub_account_id: int,
    symbol: str,
    user_id: int | None,
    hedge_account: str,
    error_message: str,
    expected_statuses=("SPOT_SOLD", "HEDGING"),
) -> bool:
    """Record a lost final lease without clobbering a newer lifecycle state."""
    # ``OPEN`` is a completed, exchange-backed lifecycle state.  Reverting it
    # to ``SPOT_SOLD`` after a post-CAS lease loss can overwrite a replacement
    # owner's state, so this helper is deliberately limited to the pre-OPEN
    # recovery window.
    if any(str(value).strip().upper() == "OPEN" for value in expected_statuses):
        logger.warning("Refusing to revert an OPEN hedge row to SPOT_SOLD")
        return False
    query = _hedge_position_identity_query(
        db,
        getattr(position, "id", None),
        sub_account_id,
        symbol,
        user_id=user_id,
        expected_statuses=expected_statuses,
        hedge_account=hedge_account,
    )
    try:
        updated = query.update(
            {
                Position.status: "SPOT_SOLD",
                Position.error_message: error_message,
                Position.updated_at: datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )
        db.commit()
        if updated == 1:
            try:
                db.refresh(position)
            except Exception:
                pass
        return updated == 1
    except Exception:
        db.rollback()
        logger.warning("Unable to preserve SPOT_SOLD for %s", symbol, exc_info=True)
        return False


def _cas_borrow_failure(
    db,
    position: Position,
    message: str,
    *,
    expected_statuses=("PENDING_BORROW", BORROW_SUBMITTING),
) -> bool:
    """Mark a pre-submit borrow failure without clobbering a newer lifecycle.

    A final guard rejection can race a manual close or a sibling recovery
    worker.  Updating the stale ORM instance directly would overwrite that
    newer state.  Use a conditional database update and publish only when this
    call still owns the submission row.
    """
    query = db.query(Position).filter(
        Position.id == getattr(position, "id", None),
        Position.sub_account_id == getattr(position, "sub_account_id", None),
        Position.status.in_(tuple(expected_statuses)),
    )
    user_id = getattr(position, "user_id", None)
    if user_id is not None:
        query = query.filter(Position.user_id == user_id)
    values = {Position.status: "FAILED", Position.error_message: message}
    update = getattr(query, "update", None)
    if callable(update):
        updated = update(values, synchronize_session=False)
    else:
        # Keep lightweight repository/test doubles compatible while retaining
        # the same status check when they do not expose Query.update().
        current = query.first()
        updated = 0
        if current is not None:
            current.status = "FAILED"
            current.error_message = message
            updated = 1
    db.commit()
    if updated:
        try:
            db.refresh(position)
        except Exception:
            logger.debug(
                "Unable to refresh borrow failure position %s",
                getattr(position, "id", None),
                exc_info=True,
            )
    return updated == 1


def _restore_topup_borrowed_idle(
    db,
    position: Position,
    error_message: str | None,
) -> bool:
    """Restore only the submission boundary still owned by this executor."""
    return _cas_topup_position(
        db,
        position,
        BORROW_SUBMITTING,
        {
            Position.status: "BORROWED_IDLE",
            Position.error_message: error_message,
        },
    )


def _lock_sub_account(db, sub_account_id: int):
    """Serialize active-position creation on PostgreSQL; test doubles stay compatible."""
    from app.db.models import SubAccount

    query = db.query(SubAccount).filter(SubAccount.id == sub_account_id)
    with_for_update = getattr(query, "with_for_update", None)
    if callable(with_for_update):
        query = with_for_update()
    return query.first()


def _discard_unsent_borrow_position(
    db,
    position: Position,
    *,
    user_id: int | None,
    account_note: str,
    quantity: Decimal,
) -> None:
    """Remove a transient row when inventory rejected a provably unsent borrow."""
    position.status = "FAILED"
    position.error_message = (
        f"Borrow skipped: fresh pool inventory is below requested quantity {quantity}"
    )
    try:
        db.delete(position)
        db.commit()
    except Exception:
        # Retain a terminal row if cleanup itself fails; never leave a
        # PENDING/BORROW_SUBMITTING row that stale recovery could misread.
        db.rollback()
        position.status = "FAILED"
        position.error_message = (
            f"Borrow skipped: fresh pool inventory is below requested quantity {quantity}"
        )
        db.commit()
    _publish_position_update(position, user_id, account_note)


def _execution_spread_sane(
    snapshot: SpreadSnapshot | None,
    rules: GlobalRulesSnapshot | None,
) -> bool:
    """Validate a quote at an exchange side-effect boundary.

    Worker discovery intentionally accepts large finite opportunities, but
    direct/manual callers must not bypass the configured execution ceiling.
    """
    if snapshot is None:
        return False
    try:
        prices = (
            Decimal(str(snapshot.spot_ask)),
            Decimal(str(snapshot.spot_bid)),
            Decimal(str(snapshot.fut_ask)),
            Decimal(str(snapshot.fut_bid)),
        )
        spreads = (
            Decimal(str(snapshot.spread_short)),
            Decimal(str(snapshot.spread_long)),
        )
        if not all(value.is_finite() and value > 0 for value in prices):
            return False
        if not all(value.is_finite() for value in spreads):
            return False
        ceiling = Decimal(str(getattr(rules, "max_spread_pct", 3) or 0))
        return ceiling <= 0 or all(abs(value) <= ceiling for value in spreads)
    except (AttributeError, TypeError, ValueError):
        return False


def _borrow_outcome_is_unknown(exc: BaseException) -> bool:
    """Whether a post-boundary failure lacks a definite Binance rejection.

    A Binance response with an ordinary API code proves that the exchange
    rejected the request. Code -1007 explicitly means execution status
    unknown. Everything outside ``BinanceAPIError`` is also ambiguous once the
    durable ``BORROW_SUBMITTING`` boundary has been crossed: connection resets
    and even local exceptions can happen after bytes were sent.
    """
    if isinstance(exc, BinancePreSubmitRejected):
        return False
    if isinstance(exc, BinanceAPIError):
        return getattr(exc, "api_code", None) == -1007
    return True


def _borrow_snapshot_ok(
    snapshot: SpreadSnapshot | None,
    confirm_spread: Decimal | None,
    *,
    skip_threshold: bool = False,
    max_age_ms: int = BORROW_FRESH_MS,
    now_ms: int | None = None,
) -> bool:
    """Validate the snapshot used to size/submit a borrow order.

    ``skip_threshold`` is only the deliberate negative-threshold pre-borrow
    policy. It never skips the per-leg local-receive freshness requirement.
    """
    if not is_spread_fresh(snapshot, now_ms=now_ms, max_age_ms=max_age_ms):
        return False
    return skip_threshold or upward_reached(
        snapshot.spread_short if snapshot is not None else None,
        confirm_spread,
    )


def _close_snapshot_ok(
    snapshot: SpreadSnapshot | None,
    *,
    spot_order_mode: str = "market",
    allow_emergency_close: bool = False,
    max_age_ms: int = BORROW_FRESH_MS,
    now_ms: int | None = None,
) -> bool:
    """Apply the close freshness policy before any exchange side effect.

    Emergency is deliberately narrow: only an explicitly requested market
    exit may proceed with a stale/legacy quote. Maker exits need the quote for
    limit pricing and therefore remain freshness-gated.
    """
    if is_spread_fresh(snapshot, now_ms=now_ms, max_age_ms=max_age_ms):
        return True
    return bool(
        allow_emergency_close
        and str(spot_order_mode or "market").lower() == "market"
    )


def _compute_net_expect(spread_short_pct, notional_usdt: float, interest_rate_daily,
                        hold_hours: float, f_spot, f_fut, buffer_pct) -> tuple[float, dict]:
    """开仓前净期望收益 E(USDT,统一绝对值口径)。所有输入折成 USDT 再比较,避免 %/币/分数混算。
      E = 点差捕获 − 利息(持有期) − 4腿手续费 − tick/滑点摩擦
    - 点差捕获 = spread_short(%)/100 × 名义额。本策略借币→卖现货→多合约,收敛即赚这段基差。
    - 利息 = 日利率 × 名义额 × 持有小时/24。持有小时取"预期最短持仓"(≥1,币安按小时头计息)。
    - 4腿手续费 = (现卖+现买)×f_spot + (期开+期平)×f_fut = 2×名义×(f_spot+f_fut)。
    - tick摩擦 = open_spread_buffer(%)/100 × 名义额(近似腿间滑点/tick 步进,现状唯一摩擦旋钮)。
    资金费预期第一版不计入(短持有常跨不到8h结算,且可正可负):作为已知保守偏差,E 偏低=宁可少开。
    返回 (E, 分项dict)。E≤0 = 结构性亏损,不该开。"""
    n = float(notional_usdt or 0)
    cap = float(spread_short_pct or 0) / 100.0 * n
    interest = float(interest_rate_daily or 0) * n * max(1.0, hold_hours) / 24.0
    fee = 2.0 * n * (float(f_spot or 0) + float(f_fut or 0))
    tick = float(buffer_pct or 0) / 100.0 * n
    e = cap - interest - fee - tick
    return e, {
        "notional_usdt": round(n, 4), "spread_capture": round(cap, 4),
        "interest_cost": round(interest, 4), "fee_cost": round(fee, 4),
        "tick_cost": round(tick, 4), "funding_expect": 0.0, "E": round(e, 4),
    }


def _publish_net_eval(user_id, symbol: str, e: float, br: dict, decision: str, gate_mode: str):
    """把开仓净期望评估写 Redis(供 coinadmin market-monitor 实时 E 榜)。
    键 engine:{uid}:neteval:{SYMBOL},60s TTL 保鲜;失败静默,绝不影响借币主流程。"""
    if user_id is None:
        return
    try:
        import json as _json, time as _t, redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        rc.setex(f"engine:{user_id}:neteval:{symbol}", 60, _json.dumps({
            **br, "decision": decision, "gate_mode": gate_mode, "ts": int(_t.time() * 1000),
        }))
        rc.close()
    except Exception:
        pass


async def _get_asset_debt(client: BinanceTradingClient, asset: str) -> tuple[Decimal, Decimal]:
    margin_info = await client.get_margin_account()
    for a in margin_info.get("userAssets", []):
        if a["asset"] == asset:
            borrowed = Decimal(str(a.get("borrowed", "0")))
            interest = Decimal(str(a.get("interest", "0")))
            return borrowed + interest, interest
    return Decimal("0"), Decimal("0")


MARGIN_DEBT_VERIFY_DELAYS = (0.0, 0.25, 0.5, 1.0, 2.0)
REPAY_DEBT_VERIFY_DELAYS = (0.0, 0.25, 0.5, 1.0)
REPAY_DEBT_EPSILON = Decimal("0.00000001")


class MarginDebtVerificationUnavailable(RuntimeError):
    pass


def _margin_borrowed_principal(margin_info: dict, asset: str) -> Decimal:
    """Read a finite, non-negative cross-margin principal from an account snapshot."""
    if not isinstance(margin_info, dict) or not isinstance(margin_info.get("userAssets"), list):
        raise ValueError("margin account response has no userAssets list")
    wanted = str(asset or "").upper()
    for item in margin_info["userAssets"]:
        if str(item.get("asset") or "").upper() != wanted:
            continue
        principal = Decimal(str(item.get("borrowed", "0") or "0"))
        if not principal.is_finite() or principal < 0:
            raise ValueError(f"invalid borrowed principal for {wanted}: {principal}")
        return principal
    return Decimal("0")


def _recorded_active_borrow_notional(
    db,
    sub_account_id: int,
    symbol: str,
) -> Decimal:
    """Return immutable borrow-time USDT notional for active positions.

    Binance exposes principal in coin units only. Revaluing that principal at
    a lower current price would incorrectly reopen a cumulative USDT cap, so
    every confirmed bite also keeps its original notional on the Position.
    """
    rows = db.query(Position).filter(
        Position.sub_account_id == sub_account_id,
        Position.symbol == symbol,
        Position.status.notin_(("CLOSED", "FAILED")),
    ).all()
    total = Decimal("0")
    for row in rows:
        raw = getattr(row, "borrow_usdt_amount", None)
        if raw is None:
            continue
        value = Decimal(str(raw))
        if not value.is_finite() or value < 0:
            raise ValueError(
                f"invalid recorded borrow notional for position {row.id}: {raw}"
            )
        total += value
    return total


def _resolve_single_order_amount(
    db,
    sub_account_id: int,
    symbol: str,
    rules: GlobalRulesSnapshot,
    user_id: int | None = None,
    *,
    account=None,
    account_symbol_rule=None,
    symbol_rule=None,
) -> Decimal:
    """Resolve the USDT amount for one Binance borrow request.

    Precedence is account-symbol, user-symbol, sub-account
    ``single_order_amount``, then the global ``order_amount``. This field is
    deliberately independent from the hedge tranche amount below.
    """
    from app.db.models import AccountSymbolRule, SubAccount, SymbolRule

    base_asset = str(symbol or "").replace("USDT", "")
    if account is None:
        account = db.query(SubAccount).get(sub_account_id)

    if account_symbol_rule is None:
        account_rule_query = db.query(AccountSymbolRule).filter(
            AccountSymbolRule.sub_account_id == sub_account_id,
            AccountSymbolRule.symbol == symbol,
        )
        if user_id is None:
            account_rule_query = account_rule_query.filter(
                AccountSymbolRule.user_id.is_(None)
            )
        else:
            account_rule_query = account_rule_query.filter(
                AccountSymbolRule.user_id == user_id
            )
        account_symbol_rule = account_rule_query.first()
        if account_symbol_rule is None and base_asset != symbol:
            account_rule_query = db.query(AccountSymbolRule).filter(
                AccountSymbolRule.sub_account_id == sub_account_id,
                AccountSymbolRule.symbol == base_asset,
            )
            if user_id is None:
                account_rule_query = account_rule_query.filter(
                    AccountSymbolRule.user_id.is_(None)
                )
            else:
                account_rule_query = account_rule_query.filter(
                    AccountSymbolRule.user_id == user_id
                )
            account_symbol_rule = account_rule_query.first()

    if symbol_rule is None and user_id is not None:
        symbol_rule = db.query(SymbolRule).filter(
            SymbolRule.user_id == user_id,
            SymbolRule.symbol == symbol,
        ).first()
        if symbol_rule is None and base_asset != symbol:
            symbol_rule = db.query(SymbolRule).filter(
                SymbolRule.user_id == user_id,
                SymbolRule.symbol == base_asset,
            ).first()

    amount = getattr(rules, "order_amount", 0)
    # ``None`` means "follow the parent rule".  A configured zero is an
    # explicit account-level disable and must remain authoritative, just like
    # the symbol-level override below.  Using truthiness here would silently
    # turn a user's zero into a live global borrow amount.
    account_amount = getattr(account, "single_order_amount", None)
    if account_amount is not None:
        amount = account_amount
    user_amount = getattr(symbol_rule, "order_amount", None)
    if user_amount is not None:
        amount = user_amount
    account_symbol_amount = getattr(account_symbol_rule, "order_amount", None)
    if account_symbol_amount is not None:
        amount = account_symbol_amount

    try:
        value = Decimal(str(amount or 0))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0")
    return value if value.is_finite() and value >= 0 else Decimal("0")


def _resolve_authoritative_borrow_threshold(
    db,
    sub_account_id: int,
    symbol: str,
    rules: GlobalRulesSnapshot,
    user_id: int | None,
    fallback: Decimal | None,
) -> Decimal:
    """Re-read the effective borrow line at the exchange submission boundary."""
    from app.db.models import AccountSymbolRule, GlobalRules, SymbolRule

    # The same session loaded sizing overrides earlier. Expire its identity map
    # so READ COMMITTED fetches edits saved while preflights were in flight.
    expire_all = getattr(db, "expire_all", None)
    if callable(expire_all):
        expire_all()

    def fresh_first(query):
        populate_existing = getattr(query, "populate_existing", None)
        if callable(populate_existing):
            query = populate_existing()
        return query.first()

    global_row = None
    if user_id is not None:
        global_row = fresh_first(
            db.query(GlobalRules).filter(GlobalRules.user_id == user_id)
        )

    threshold = fallback
    # ``fallback`` is Worker.eff_borrow and already contains the buffer.
    # Add a buffer only when a fresh DB row replaces that effective fallback.
    buffer_value = 0
    threshold_from_db = False
    if global_row is not None:
        global_threshold = getattr(global_row, "borrow_spread", None)
        if global_threshold is None:
            global_threshold = getattr(global_row, "open_spread", None)
        if global_threshold is not None:
            threshold = global_threshold
            threshold_from_db = True
            buffer_value = getattr(global_row, "open_spread_buffer", 0) or 0

    base_asset = symbol[:-4] if symbol.endswith("USDT") else symbol
    symbols = (symbol, base_asset) if base_asset != symbol else (symbol,)
    symbol_row = None
    if user_id is not None:
        for candidate in symbols:
            symbol_row = fresh_first(
                db.query(SymbolRule).filter(
                    SymbolRule.user_id == user_id,
                    SymbolRule.symbol == candidate,
                )
            )
            if symbol_row is not None:
                break
    if symbol_row is not None and symbol_row.borrow_spread is not None:
        threshold = symbol_row.borrow_spread
        threshold_from_db = True
        if global_row is None:
            buffer_value = getattr(rules, "open_spread_buffer", 0) or 0

    account_row = None
    for candidate in symbols:
        account_query = db.query(AccountSymbolRule).filter(
            AccountSymbolRule.sub_account_id == sub_account_id,
            AccountSymbolRule.symbol == candidate,
        )
        # Account ids are globally unique today, but the rule table contains
        # legacy rows with nullable/incorrect ownership.  The submission
        # boundary is a security-critical read: never let another tenant's
        # symbol rule override this user's freshly saved threshold.  Workers
        # without a resolved tenant may only consume explicitly legacy rows.
        if user_id is None:
            account_query = account_query.filter(AccountSymbolRule.user_id.is_(None))
        else:
            account_query = account_query.filter(AccountSymbolRule.user_id == user_id)
        account_row = fresh_first(account_query)
        if account_row is not None:
            break
    if account_row is not None and account_row.borrow_spread is not None:
        threshold = account_row.borrow_spread
        threshold_from_db = True
        if global_row is None:
            buffer_value = getattr(rules, "open_spread_buffer", 0) or 0

    if threshold is None:
        threshold = getattr(rules, "borrow_spread", None)
    if threshold is None:
        threshold = getattr(rules, "open_spread", None)
    if fallback is None and not threshold_from_db:
        buffer_value = getattr(rules, "open_spread_buffer", 0) or 0
    value = Decimal(str(threshold)) + Decimal(str(buffer_value))
    if not value.is_finite():
        raise ValueError(f"non-finite authoritative borrow threshold: {value}")
    return value


def _authoritative_borrow_enabled(
    db,
    sub_account_id: int,
    symbol: str,
    user_id: int | None,
) -> bool:
    """Re-read every opening gate at the final submission boundary.

    Worker discovery already filters the shared eligible universe, but manual
    and API callers can bypass that read model.  The delisting scanner writes
    ``Symbol.is_delisting``/``allow_open`` and a global ``Blacklist`` row; both
    must therefore be checked again immediately before a borrow request.  The
    check is intentionally global for delisting/blacklist, while account-symbol
    switches remain tenant-scoped.
    """
    from app.db.models import AccountSymbolRule, Blacklist, SubAccount, Symbol

    try:
        expire_all = getattr(db, "expire_all", None)
        if callable(expire_all):
            expire_all()

        account = db.query(SubAccount).filter(
            SubAccount.id == sub_account_id,
        ).first()
        if account is None or getattr(account, "is_enabled", True) is False:
            return False
        owner = getattr(account, "user_id", None)
        if user_id is None:
            if owner is not None:
                return False
        else:
            if owner is None or int(owner) != int(user_id):
                return False

        normalized = str(symbol or "").strip().upper()
        base_asset = normalized[:-4] if normalized.endswith("USDT") else normalized
        candidates = (
            (normalized, base_asset) if base_asset != normalized else (normalized,)
        )

        # A symbol discovered by Binance CMS/Telegram is blocked for every
        # tenant.  Do not let a stale pushed row or a manual endpoint submit a
        # new loan after the scanner has marked it.  Missing legacy Symbol
        # rows are tolerated for backward compatibility; an explicit global
        # blacklist or a disallowed Symbol row is fail-closed.
        symbol_row = None
        for candidate in candidates:
            symbol_row = db.query(Symbol).filter(Symbol.symbol == candidate).first()
            if symbol_row is not None:
                break
        if symbol_row is not None and (
            getattr(symbol_row, "is_delisting", False) is True
            or getattr(symbol_row, "allow_open", True) is False
            or getattr(symbol_row, "is_active", True) is False
        ):
            return False
        global_blacklist = db.query(Blacklist).filter(
            Blacklist.symbol.in_(candidates),
            Blacklist.user_id.is_(None),
        ).first()
        if global_blacklist is not None:
            return False

        for candidate in candidates:
            query = db.query(AccountSymbolRule).filter(
                AccountSymbolRule.sub_account_id == sub_account_id,
                AccountSymbolRule.symbol == candidate,
            )
            if user_id is None:
                query = query.filter(AccountSymbolRule.user_id.is_(None))
            else:
                query = query.filter(AccountSymbolRule.user_id == user_id)
            account_rule = query.first()
            if account_rule is not None:
                return getattr(account_rule, "is_enabled", True) is not False
        return True
    except Exception:
        logger.warning(
            "Authoritative opening switch check failed for account %s %s",
            sub_account_id,
            symbol,
            exc_info=True,
        )
        return False


def _resolve_hedge_order_amount(
    db,
    sub_account_id: int,
    symbol: str,
    rules: GlobalRulesSnapshot,
    user_id: int | None = None,
    *,
    account=None,
    account_symbol_rule=None,
    symbol_rule=None,
) -> Decimal:
    """Resolve one spot/futures opening tranche without changing borrow size.

    Precedence mirrors the borrow resolver but uses an independent field:
    account-symbol ``open_order_amount``, user-symbol
    ``open_order_amount``, sub-account ``order_amount``, then global
    ``open_order_amount``. If every new field is null, the legacy global
    ``order_amount`` preserves the pre-migration behavior.
    """
    from app.db.models import AccountSymbolRule, SubAccount, SymbolRule

    base_asset = str(symbol or "").replace("USDT", "")
    if account is None:
        account = db.query(SubAccount).get(sub_account_id)

    if account_symbol_rule is None:
        query = db.query(AccountSymbolRule).filter(
            AccountSymbolRule.sub_account_id == sub_account_id,
            AccountSymbolRule.symbol.in_([symbol, base_asset]),
        )
        if user_id is not None:
            query = query.filter(AccountSymbolRule.user_id == user_id)
        else:
            query = query.filter(AccountSymbolRule.user_id.is_(None))
        account_symbol_rule = query.first()

    if symbol_rule is None and user_id is not None:
        symbol_rule = db.query(SymbolRule).filter(
            SymbolRule.user_id == user_id,
            SymbolRule.symbol.in_([symbol, base_asset]),
        ).first()

    global_open = getattr(rules, "open_order_amount", None)
    amount = global_open if global_open is not None else getattr(rules, "order_amount", 0)
    account_amount = getattr(account, "order_amount", None)
    if account_amount is not None:
        amount = account_amount
    symbol_amount = getattr(symbol_rule, "open_order_amount", None)
    if symbol_amount is not None:
        amount = symbol_amount
    account_symbol_amount = getattr(account_symbol_rule, "open_order_amount", None)
    if account_symbol_amount is not None:
        amount = account_symbol_amount
    try:
        value = Decimal(str(amount or 0))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0")
    return value if value.is_finite() and value >= 0 else Decimal("0")


def _hedge_batch_size(
    quantity: Decimal,
    price: Decimal,
    order_amount: Decimal,
    step_size: Decimal,
    borrow_notional: Decimal | None = None,
) -> Decimal:
    """Return one spot-sell tranche without exceeding the borrowed quantity.

    Confirmed positions carry the borrow-time USDT notional.  Use it to derive
    the number of configured single-order tranches so a later price move does
    not turn (for example) an 80U borrow into a different batch plan.  Legacy
    rows without that column retain the previous price-based calculation.
    """
    original_quantity = quantity
    try:
        quantity = Decimal(str(quantity))
        price = Decimal(str(price))
        order_amount = Decimal(str(order_amount))
        step_size = Decimal(str(step_size))
        recorded = (
            Decimal(str(borrow_notional))
            if borrow_notional is not None
            else Decimal("0")
        )
        if not quantity.is_finite() or quantity <= 0 or step_size <= 0:
            return Decimal("0")
        if (
            recorded.is_finite()
            and recorded > 0
            and order_amount.is_finite()
            and order_amount > 0
        ):
            # IOC 部分成交时「记录名义」是计划值,可能远大于实际持币规模;按计划切批
            # 会把每批切到交易所最小名义之下(实证: 计划100U/实收24U/单笔20U → 5批×4.87U
            # → 首批即 -1013 整单回滚)。分批基数取 min(记录名义, 实际数量×现价)。
            effective_notional = recorded
            if price.is_finite() and price > 0:
                actual_notional = quantity * price
                if actual_notional > 0 and actual_notional < effective_notional:
                    effective_notional = actual_notional
            batches = int(
                (effective_notional / order_amount).to_integral_value(rounding=ROUND_UP)
            )
            batches = max(1, batches)
            candidate = round_to_step(quantity / Decimal(batches), step_size)
            # Keep the historical tranche count, but never let a quote jump
            # make an individual order exceed the configured USDT amount.
            # When price falls the historical tranche remains smaller than
            # the cap; when price rises additional loop iterations are safe.
            if price.is_finite() and price > 0:
                price_capped = round_to_step(order_amount / price, step_size)
                if price_capped > 0:
                    candidate = min(candidate, price_capped)
        elif order_amount.is_finite() and order_amount > 0 and price.is_finite() and price > 0:
            candidate = round_to_step(order_amount / price, step_size)
        else:
            candidate = quantity
        return candidate if candidate > 0 else quantity
    except (TypeError, ValueError, ArithmeticError):
        try:
            fallback = Decimal(str(original_quantity))
            return fallback if fallback.is_finite() and fallback > 0 else Decimal("0")
        except (TypeError, ValueError, ArithmeticError):
            return Decimal("0")


def _cumulative_hedge_order_qty(
    total_spot_filled: Decimal,
    total_futures_filled: Decimal,
    futures_step_size: Decimal,
) -> Decimal:
    """Return the next futures order from the rounded cumulative target."""
    target = round_to_step(total_spot_filled, futures_step_size)
    remaining = target - total_futures_filled
    if remaining <= 0:
        return Decimal("0")
    return round_to_step(remaining, futures_step_size)


async def _confirm_margin_borrow_delta(
    client: BinanceTradingClient,
    asset: str,
    principal_before: Decimal,
) -> Decimal:
    """Poll authoritative margin debt and return this MARGIN_BUY's principal delta.

    A valid zero/non-positive delta is returned to the caller as a confirmed
    non-borrow. If every post-submit read fails, the outcome is ambiguous and
    the caller must install a retry guard while orphan-debt reconciliation
    waits for the account API to recover.
    """
    last_error = None
    observed_delta = None
    for delay in MARGIN_DEBT_VERIFY_DELAYS:
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            principal_after = _margin_borrowed_principal(
                await client.get_margin_account(), asset
            )
            delta = principal_after - principal_before
            if not delta.is_finite():
                raise ValueError(f"non-finite debt delta for {asset}: {delta}")
            observed_delta = delta
            if delta > 0:
                return delta
        except Exception as exc:
            last_error = exc
    if observed_delta is not None:
        return observed_delta
    detail = str(last_error) if last_error is not None else "no debt snapshot returned"
    raise MarginDebtVerificationUnavailable(detail)


def _set_borrow_fail_guard(
    user_id: int | None,
    sub_account_id: int,
    symbol: str,
    reason: str,
    ttl: int = 120,
) -> None:
    """Throttle only the margin account whose borrow attempt failed."""
    try:
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        rc.set(
            borrow_failure_key(user_id, sub_account_id, symbol),
            reason,
            ex=ttl,
        )
        rc.close()
    except Exception:
        logger.debug("failed to persist borrow verification cooldown", exc_info=True)


def _mark_borrow_outcome_unknown(
    db,
    position: Position,
    *,
    user_id: int | None,
    account_note: str,
    requested_qty: Decimal,
    principal_before: Decimal | None,
    reason: BaseException | str,
    latency: int | None = None,
) -> str:
    """Persist an ambiguous submission without inventing debt ownership.

    The baseline/request are diagnostic evidence only. ``borrow_qty`` remains
    unset until an operator can attribute a Binance principal delta safely;
    account-level debt must never be assigned to this row by assumption.
    """
    baseline = "unknown" if principal_before is None else str(principal_before)
    message = (
        "Borrow outcome requires reconciliation: "
        f"principal_before={baseline}; requested_qty={requested_qty}; reason={reason}"
    )
    position.status = BORROW_OUTCOME_UNKNOWN
    position.borrow_qty = None
    position.error_message = message
    db.commit()
    _publish_position_update(position, user_id, account_note)
    _log_trade(
        db,
        position.id,
        position.sub_account_id,
        "BORROW_VERIFY",
        position.symbol,
        quantity=requested_qty,
        status="UNKNOWN",
        error=message,
        latency=latency,
    )
    _publish_balance_refresh(user_id)
    return message


def _mark_borrow_topup_outcome_unknown(
    db,
    position: Position,
    *,
    user_id: int | None,
    account_note: str,
    requested_qty: Decimal,
    principal_before: Decimal | None,
    reason: BaseException | str,
    latency: int | None = None,
) -> str:
    """Quarantine an ambiguous top-up without erasing confirmed debt.

    ``_mark_borrow_outcome_unknown`` is for a newly-created Position and
    intentionally clears ``borrow_qty`` because ownership is unknown. A
    top-up runs against an already confirmed row; clearing its quantity would
    make the existing debt untracked. Keep the previously confirmed amount,
    mark the whole row as unresolved, and require reconciliation before any
    further automatic borrow.
    """
    baseline = "unknown" if principal_before is None else str(principal_before)
    message = (
        "Borrow top-up outcome requires reconciliation: "
        f"principal_before={baseline}; requested_qty={requested_qty}; reason={reason}"
    )
    if not _cas_topup_position(
        db,
        position,
        BORROW_SUBMITTING,
        {
            Position.status: BORROW_OUTCOME_UNKNOWN,
            Position.error_message: message,
        },
    ):
        logger.error(
            "Top-up outcome for position %s is unknown, but its state moved to %s",
            position.id,
            position.status,
        )
        return message
    _publish_position_update(position, user_id, account_note)
    try:
        _log_trade(
            db,
            position.id,
            position.sub_account_id,
            "BORROW_TOPUP_VERIFY",
            position.symbol,
            quantity=requested_qty,
            status="UNKNOWN",
            error=message,
            latency=latency,
        )
    except Exception:
        logger.warning("Unable to record ambiguous top-up for %s", position.symbol, exc_info=True)
    _publish_balance_refresh(user_id)
    return message


async def _topup_redis_set(redis_client, key: str, value: str, *, ex: int) -> None:
    """Set a top-up marker for either sync or asyncio Redis clients."""
    result = redis_client.set(key, value, ex=ex)
    if inspect.isawaitable(result):
        await result


def _fc_symbol_lock(fc, symbol: str) -> asyncio.Lock:
    """Per-symbol lock attached to the futures client. hedge_via_master 下该 client 被
    全部 worker 共享 —— 同 symbol 的开/平在共享净仓上必须串行,避免 reduceOnly 拒单/过量平仓。
    (子账户自有 client 时各 worker 各一份锁表,无跨账户竞争,加锁无副作用。)"""
    locks = getattr(fc, "_symbol_locks", None)
    if locks is None:
        locks = {}
        fc._symbol_locks = locks
    return locks.setdefault(symbol, asyncio.Lock())


def _master_recorded_futures_qty(
    db,
    *,
    user_id: int | None,
    symbol: str,
    exclude_position_id: int | None = None,
) -> Decimal | None:
    """Sum durable master hedge quantities for one tenant/symbol.

    ``None`` means a malformed row or query failure made the aggregate
    unverifiable; callers must fail closed rather than submit a blind shared
    position order.
    """
    try:
        query = db.query(Position).filter(
            Position.symbol == canonical_position_symbol(symbol),
            Position.hedge_account == "master",
            Position.status.in_(
                # buy-first close: CLOSING_SPOT rows still hold their futures
                # leg; omitting them under-counts the shared master aggregate
                # and holds sibling closes with a phantom mismatch.
                ("HEDGING", "SPOT_SOLD", "OPEN", "CLOSING_FUTURES",
                 "CLOSING_SPOT", "SPOT_BOUGHT")
            ),
        )
        if user_id is None:
            query = query.filter(Position.user_id.is_(None))
        else:
            query = query.filter(Position.user_id == user_id)
        if exclude_position_id is not None:
            query = query.filter(Position.id != exclude_position_id)
        total = Decimal("0")
        for row in query.all():
            raw = getattr(row, "futures_long_qty", None)
            qty = Decimal(str(raw or "0"))
            if not qty.is_finite() or qty < 0:
                return None
            total += qty
        return total
    except Exception:
        logger.warning("Unable to calculate master futures aggregate for %s", symbol, exc_info=True)
        return None


_precheck_warn_ts: dict[str, float] = {}
_topup_ts: dict[str, float] = {}


def _load_fund_floor_and_sources() -> tuple[Decimal, list[str]]:
    """读全局 FundRules:(源钱包留底 base_margin_amount, 给合约钱包供资的源顺序)。
    源取 transfer_order 中的非 futures 项(spot/margin),空则默认 [spot, margin]。同步,to_thread 调。"""
    db = SessionLocal()
    try:
        from app.db.models import FundRules
        fr = db.query(FundRules).first()
        floor = Decimal(str(fr.base_margin_amount)) if fr and fr.base_margin_amount is not None else Decimal("0")
        raw = (fr.transfer_order if fr and fr.transfer_order else "spot,margin")
        sources = [s.strip() for s in raw.split(",") if s.strip() in ("spot", "margin")]
        if not sources:
            sources = ["spot", "margin"]
        return floor, sources
    finally:
        db.close()


async def _topup_master_futures(
    fc,
    symbol: str,
    deficit: Decimal,
    pre_submit_guard=None,
) -> bool:
    """hedge_via_master 主账户合约钱包欠资时,从主账户 spot/margin 钱包**账户内**划入 USDT
    (fc.transfer,非跨账户),让对冲能继续。源钱包留底 base_margin_amount,按 transfer_order
    顺序累计补足 deficit;30s/币种 节流防循环。任一笔成功返回 True。
    任何异常静默(不抛),调用方据再查结果决定放行或回退 hold —— 绝不因补给失败把持仓推入回滚空转。"""
    if not _pre_submit_guard_allows(pre_submit_guard):
        return False
    now = time.monotonic()
    if now - _topup_ts.get(symbol, 0) < 30:
        return False
    _topup_ts[symbol] = now
    try:
        floor, sources = await asyncio.to_thread(_load_fund_floor_and_sources)
        remaining = deficit.quantize(Decimal("0.01"), rounding=ROUND_UP)
        moved = Decimal("0")
        for src in sources:
            if remaining <= 0:
                break
            try:
                if src == "spot":
                    acct = await fc.get_spot_account()
                    free = next((Decimal(str(b.get("free", "0"))) for b in acct.get("balances", [])
                                 if b.get("asset") == "USDT"), Decimal("0"))
                    ttype = "MAIN_UMFUTURE"
                else:  # margin
                    acct = await fc.get_margin_account()
                    free = next((Decimal(str(a.get("free", "0"))) for a in acct.get("userAssets", [])
                                 if a.get("asset") == "USDT"), Decimal("0"))
                    ttype = "MARGIN_UMFUTURE"
                pullable = free - floor
                amt = min(remaining, pullable).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                if amt <= 0:
                    continue
                if not _pre_submit_guard_allows(pre_submit_guard):
                    return moved > 0
                await fc.transfer(
                    ttype,
                    "USDT",
                    amt,
                    **_pre_submit_kwargs(pre_submit_guard),
                )
                moved += amt
                remaining -= amt
                logger.info(f"hedge_via_master topup: {amt} USDT {src}->futures (master) for {symbol}")
            except BinancePreSubmitRejected:
                return moved > 0
            except Exception as e:
                logger.warning(f"hedge_via_master topup {src}->futures failed ({symbol}): {e}")
                continue
        return moved > 0
    except Exception as e:
        logger.warning(f"hedge_via_master topup failed {symbol}: {e}")
        return False


async def _master_margin_precheck(
    fc,
    symbol,
    qty,
    spread,
    notifier,
    account_note,
    pre_submit_guard=None,
) -> Decimal | None:
    """hedge_via_master: 对冲前查主账户合约可用余额(按该 symbol 当前杠杆估算所需保证金,
    留 10% 缓冲)。带账户级预留(挂在共享 client 上的 in-flight 计数,锁内比较+占用),
    防止多 worker 并发用同一余额各自通过。通过返回预留额(调用方 finally 归还)。
    欠资时先尝试主账户内自动补给(spot/margin→futures)再复检一次;仍不足或查询异常 → None,
    调用方把持仓留在 BORROWED_IDLE 等下轮 —— 绝不进入「卖出→合约失败→回滚」的空转。"""
    try:
        if not _pre_submit_guard_allows(pre_submit_guard):
            return None
        price = spread.fut_ask if (getattr(spread, "fut_ask", None) and spread.fut_ask > 0) else spread.spot_ask
        pr = await fc.futures_position_risk(symbol)
        lev = Decimal(str((pr or {}).get("leverage") or "20"))
        if lev <= 0:
            lev = Decimal("20")
        need = (qty * price / lev) * Decimal("1.1")

        rlock = getattr(fc, "_reserve_lock", None)
        if rlock is None:
            rlock = asyncio.Lock()
            fc._reserve_lock = rlock
        async with rlock:
            acct = await fc.get_futures_account()
            avail = Decimal(str(acct.get("availableBalance", "0")))
            reserved = getattr(fc, "_margin_reserved", Decimal("0"))
            if avail - reserved >= need:
                fc._margin_reserved = reserved + need
                return need
            deficit = need - (avail - reserved)

        # 欠资 → 主账户内自动补给(锁外做转账/查询,避免占用 reserve 锁阻塞其他 worker),再复检一次
        if await _topup_master_futures(
            fc, symbol, deficit, pre_submit_guard=pre_submit_guard
        ):
            if not _pre_submit_guard_allows(pre_submit_guard):
                return None
            async with rlock:
                acct = await fc.get_futures_account()
                avail = Decimal(str(acct.get("availableBalance", "0")))
                reserved = getattr(fc, "_margin_reserved", Decimal("0"))
                if avail - reserved >= need:
                    fc._margin_reserved = reserved + need
                    logger.info(f"hedge_via_master: {symbol} 自动补给后合约保证金已满足(need≈{need:.4f})")
                    return need

        now = time.monotonic()
        if now - _precheck_warn_ts.get(symbol, 0) > 300:
            _precheck_warn_ts[symbol] = now
            logger.warning(f"hedge_via_master: master avail insufficient for {symbol} (need≈{need:.4f}); hold BORROWED_IDLE")
            await notifier.notify_error(
                account_note, f"hedge {symbol}",
                f"主账户合约可用余额不足(需≈{need:.2f} USDT),自动补给未能补足,持仓停在待对冲",
            )
        return None
    except Exception as e:
        logger.warning(f"hedge_via_master: precheck failed {symbol}: {e}; hold BORROWED_IDLE")
        return None


def _release_margin_reserve(fc, amount: Decimal):
    if fc is None or amount is None:
        return
    try:
        fc._margin_reserved = max(Decimal("0"), getattr(fc, "_margin_reserved", Decimal("0")) - amount)
    except Exception:
        pass


def _ensure_avg_price(o: dict) -> dict:
    """Fill a missing futures average price from a cumulative quote amount.

    Futures-compatible gateways have returned both ``cumQuote`` and the spot
    spelling ``cummulativeQuoteQty``.  Keep this normalizer in sync with
    :func:`_avg_fill_price` so a zero ``avgPrice`` cannot reach accounting when
    a quote total is available.
    """
    try:
        eq = Decimal(str(o.get("executedQty", "0") or "0"))
        ap = Decimal(str(o.get("avgPrice", "0") or "0"))
        if eq.is_finite() and eq > 0 and ap.is_finite() and ap <= 0:
            cq = None
            for quote_key in (
                "cumQuote",
                "cummulativeQuoteQty",
                "quoteQty",
                "cumulativeQuoteQty",
            ):
                try:
                    candidate = Decimal(str(o.get(quote_key, "0") or "0"))
                except (TypeError, ValueError, ArithmeticError):
                    continue
                if candidate.is_finite() and candidate > 0:
                    cq = candidate
                    break
            derived = (cq / eq) if cq is not None else _avg_fill_price(o)
            if derived.is_finite() and derived > 0:
                o = dict(o)
                o["avgPrice"] = str(derived)
    except Exception:
        pass
    return o


def _normalize_futures_result(result: dict) -> dict:
    """Normalize a futures fill without treating a zero price as a fill.

    Binance-compatible gateways occasionally omit ``status`` on an otherwise
    complete market ``RESULT`` response.  A positive executed quantity and a
    verifiable positive average price are enough to normalize that legacy
    shape to ``FILLED``.  Explicit non-terminal/canceled statuses are kept as
    received and are rejected by the lifecycle gate below.
    """
    normalized = _ensure_avg_price(dict(result or {}))
    try:
        qty = Decimal(str(normalized.get("executedQty", "0") or "0"))
    except (TypeError, ValueError, ArithmeticError):
        qty = Decimal("0")
    status = str(normalized.get("status") or "").upper()
    if (
        not status
        and qty.is_finite()
        and qty > RECOVERY_EPSILON
        and _avg_fill_price(normalized) > RECOVERY_EPSILON
    ):
        normalized["status"] = "FILLED"
    return normalized


def _futures_fill_metrics(result: dict) -> tuple[dict, str, Decimal, Decimal]:
    """Return normalized status, quantity, and authoritative average price."""
    normalized = _normalize_futures_result(result)
    status = str(normalized.get("status") or "").upper()
    try:
        quantity = Decimal(str(normalized.get("executedQty", "0") or "0"))
    except (TypeError, ValueError, ArithmeticError):
        quantity = Decimal("0")
    if not quantity.is_finite() or quantity < 0:
        quantity = Decimal("0")
    price = _avg_fill_price(normalized)
    if not price.is_finite() or price < 0:
        price = Decimal("0")
    return normalized, status, quantity, price


def _futures_fill_is_complete(result: dict, target: Decimal) -> bool:
    """Require a terminal FILLED response, target quantity, and positive price."""
    _normalized, status, quantity, price = _futures_fill_metrics(result)
    try:
        target = Decimal(str(target or "0"))
    except (TypeError, ValueError, ArithmeticError):
        return False
    return (
        status == "FILLED"
        and target.is_finite()
        and target > 0
        and quantity + RECOVERY_EPSILON >= target
        and price > RECOVERY_EPSILON
    )


async def _confirm_futures_result(fc, symbol: str, result: dict) -> dict:
    """市价单应答补齐:executedQty==0 → 轮询终态;executedQty>0 但 avgPrice<=0(RESULT 均价/cumQuote
    填充滞后)→ 先 cumQuote/executedQty 兜底,仍缺则回查订单。每次查询【独立 try】(下单瞬间 -2013
    订单查不到 / 网络瞬时错 不再中断整轮回查),窗口放宽到 ~3.2s 覆盖币安成交聚合延迟。
    否则合约腿价落 0 → realized_pnl 漏算整条合约腿(实测 futures_long_price=0 致 pnl 虚高 +19.8)。"""
    def _avg(o):
        try:
            return Decimal(str((o or {}).get("avgPrice", "0") or "0"))
        except Exception:
            return Decimal("0")
    try:
        result = _normalize_futures_result(result)
        eq0 = Decimal(str(result.get("executedQty", "0") or "0"))
        oid = result.get("orderId")
        if eq0 > 0:
            result = _ensure_avg_price(result)
            if _avg(result) > 0 or not oid:
                return result
            for _ in range(8):
                await asyncio.sleep(0.4)
                try:
                    o = _normalize_futures_result(
                        await fc.futures_get_order(symbol, str(oid))
                    )
                except Exception:
                    continue
                if _avg(o) > 0:
                    return o
            return result
        if not oid:
            return result
        for _ in range(8):
            await asyncio.sleep(0.4)
            try:
                o = _normalize_futures_result(
                    await fc.futures_get_order(symbol, str(oid))
                )
            except Exception:
                continue
            if Decimal(str(o.get("executedQty", "0") or "0")) > 0 or \
               o.get("status") in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
                return o
        return result
    except Exception:
        return result


async def _confirm_spot_result(client, symbol: str, result: dict, *, is_margin: bool = True) -> dict:
    """Resolve a spot market response to an authoritative fill when possible.

    Binance normally returns a filled ``RESULT`` for a market margin order,
    but transport/proxy paths can return an ACK with ``executedQty=0`` or a
    partial status.  The close state machine must not advance to the futures
    leg from an ACK alone: query the recorded order when the client exposes the
    reader, and leave the durable ``CLOSING_SPOT`` row for reconciliation when
    the outcome remains unknown.
    """
    result = dict(result or {})
    try:
        qty = Decimal(str(result.get("executedQty", "0") or "0"))
    except (TypeError, ValueError, ArithmeticError):
        qty = Decimal("0")
    status = str(result.get("status") or "").upper()
    order_id = result.get("orderId")
    # Some Binance-compatible gateways (and the RESULT shape used by older
    # clients) omit ``status`` even though ``executedQty`` and fill data are
    # authoritative.  A positive executed quantity is sufficient evidence in
    # that shape only when a positive execution price is also present.  If the
    # response has the known ``price=0``/missing-fills shape, query the order so
    # the caller can recover the cumulative quote amount before accounting it.
    accepted_status = status in {"FILLED", "PARTIALLY_FILLED"} or not status
    if qty > 0 and accepted_status and _avg_fill_price(result) > 0:
        # Normalize the legacy/compat response so callers that gate on the
        # terminal status do not accidentally reject an already-filled order.
        if not status:
            result["status"] = "FILLED"
        return result
    query = getattr(client, "spot_query_order", None)
    if not order_id or not callable(query):
        return result
    latest = result
    # Keep the window short; an unresolved market response is deliberately
    # left in CLOSING_SPOT and recovered from the exchange order later.
    for _ in range(8):
        try:
            candidate = await query(symbol, str(order_id), is_margin)
        except Exception:
            candidate = None
        if isinstance(candidate, dict):
            if order_id and not candidate.get("orderId"):
                # Some proxy/query implementations omit the id even though
                # they return the fill fields. Preserve the durable id so a
                # later recovery pass can re-read the exact order.
                candidate = dict(candidate)
                candidate["orderId"] = str(order_id)
            latest = candidate
            try:
                latest_qty = Decimal(str(candidate.get("executedQty", "0") or "0"))
            except (TypeError, ValueError, ArithmeticError):
                latest_qty = Decimal("0")
            latest_status = str(candidate.get("status") or "").upper()
            if (
                latest_qty > 0
                and (latest_status in {"FILLED", "PARTIALLY_FILLED"} or not latest_status)
                and _avg_fill_price(candidate) > 0
            ):
                if not latest_status:
                    candidate["status"] = "FILLED"
                return candidate
            if latest_status in {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}:
                break
        await asyncio.sleep(0.2)
    return latest


async def _query_filled_by_client_id(fc, symbol: str, coid: str) -> Decimal:
    """下单响应丢失(超时/5xx「状态未知」)后,按 clientOrderId 复核实际成交量。
    -2013(订单不存在)= 未送达 → 0;查询连续失败按 0 计但留告警日志。"""
    for _ in range(3):
        try:
            o = await fc.futures_get_order_by_client_id(symbol, coid)
            return Decimal(str(o.get("executedQty", "0")))
        except BinanceAPIError as e:
            if e.api_code == -2013:
                return Decimal("0")
        except Exception:
            pass
        await asyncio.sleep(0.5)
    logger.error(f"ambiguous futures order unresolved: {symbol} clientOrderId={coid} — verify manually")
    return Decimal("0")


def _log_trade(db, position_id: int, sub_account_id: int, action: str, symbol: str,
               side: str = None, quantity: Decimal = None, price: Decimal = None,
               order_id: str = None, status: str = "SUCCESS", error: str = None, latency: int = None):
    db.add(TradeLog(
        position_id=position_id,
        sub_account_id=sub_account_id,
        user_id=_resolve_user_id(db, sub_account_id),   # 按子账户归属补 user_id(流水用户列依赖此)
        action=action,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        order_id=order_id,
        status=status,
        error_message=error,
        latency_ms=latency,
    ))
    db.commit()


SPOT_MAKER_WAIT_SEC = 3.0    # maker 挂单最长等待成交,超时撤单转市价兜底
SPOT_MAKER_POLL_SEC = 0.4


async def _spot_maker_fill(client, symbol: str, side: str, qty: Decimal, spread,
                           spot_lot: dict, is_margin: bool = True,
                           pre_submit_guard=None) -> dict:
    """现货腿 maker 成交(P1 现货 maker 化):挂 post-only 限价(LIMIT_MAKER)做挂单方省手续费;
    最长等 SPOT_MAKER_WAIT_SEC,未全成 → 撤单 → 剩余市价兜底,保证必成交、绝不留单腿。
    返回结构兼容市价单:{executedQty, orderId, _avg}(_avg=成交均价)。post-only 若会穿越盘口被币安
    -2010 拒单,直接市价兜底(此刻点差已收窄,做 taker 也认)。"""
    filters = await client._get_spot_filters(symbol)
    tick = filters["tick"]
    if side == "SELL":
        px = round_to_step(spread.spot_ask, tick) if getattr(spread, "spot_ask", 0) else None
        maker_fn = client.spot_limit_maker_sell
        market_fn = client.spot_market_sell
    else:
        px = round_to_step(spread.spot_bid, tick) if getattr(spread, "spot_bid", 0) else None
        maker_fn = client.spot_limit_maker_buy
        market_fn = client.spot_market_buy_qty
    filled = Decimal("0"); value = Decimal("0"); oid = ""
    maker_accepted = False
    if px and px > 0:
        try:
            r = await maker_fn(
                symbol,
                qty,
                px,
                is_margin,
                **_pre_submit_kwargs(pre_submit_guard),
            )
            maker_accepted = True
            oid = str(r["orderId"])
            waited = 0.0; done = False
            while waited < SPOT_MAKER_WAIT_SEC:
                await asyncio.sleep(SPOT_MAKER_POLL_SEC); waited += SPOT_MAKER_POLL_SEC
                o = await client.spot_query_order(symbol, oid, is_margin)
                if o.get("status") == "FILLED":
                    filled = Decimal(str(o.get("executedQty", "0")))
                    value = Decimal(str(o.get("cummulativeQuoteQty", "0")))
                    done = True; break
            if not done:
                try:
                    c = await client.spot_cancel_order(symbol, oid, is_margin)
                    filled = Decimal(str(c.get("executedQty", "0")))
                    value = Decimal(str(c.get("cummulativeQuoteQty", "0")))
                except Exception:
                    o = await client.spot_query_order(symbol, oid, is_margin)
                    filled = Decimal(str(o.get("executedQty", "0")))
                    value = Decimal(str(o.get("cummulativeQuoteQty", "0")))
        except BinancePreSubmitRejected as e:
            # A maker order may have partially filled before its lease is
            # replaced.  Preserve that exchange-side fill on the exception so
            # the opening lifecycle can buy it back instead of treating the
            # whole spot leg as unsent.
            try:
                e.partial_spot_qty = filled
                e.partial_spot_value = value
                e.partial_spot_order_id = oid
            except Exception:
                pass
            raise
        except BinanceAPIError as e:
            if getattr(e, "api_code", None) != -2010 and "-2010" not in str(e):
                try:
                    e.partial_spot_qty = filled
                    e.partial_spot_value = value
                    e.partial_spot_order_id = oid
                except Exception:
                    pass
                raise   # 非"会立即成交被拒",真错误上抛
        except Exception as e:
            # Query/cancel transport failures after maker acceptance are also
            # ambiguous.  Carry the accepted order id and any observed fill to
            # the caller instead of allowing a retry to submit a duplicate
            # unkeyed buy/sell.
            try:
                e.partial_spot_qty = filled
                e.partial_spot_value = value
                e.partial_spot_order_id = oid
            except Exception:
                pass
            raise
    # 剩余市价兜底(必成交,不留单腿)
    remaining = round_to_step(qty - filled, spot_lot["stepSize"])
    if remaining > 0:
        # The market fallback is still an opening order when this helper is
        # used by ``execute_hedge``. Keep the same final-boundary fencing
        # callback even after a maker order was accepted/cancelled; otherwise
        # a lease replacement during the maker wait could authorize an
        # unguarded spot sell and leave a naked position.
        try:
            mr = await market_fn(
                symbol,
                remaining,
                is_margin,
                **_pre_submit_kwargs(pre_submit_guard),
            )
        except BinancePreSubmitRejected as e:
            # The maker order may have filled part of the quantity before the
            # final market fallback was fenced. Carry that partial fill into
            # execute_hedge's compensation path.
            try:
                e.partial_spot_qty = filled
                e.partial_spot_value = value
                e.partial_spot_order_id = oid
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                e.partial_spot_qty = filled
                e.partial_spot_value = value
                e.partial_spot_order_id = oid
            except Exception:
                pass
            raise
        mq = Decimal(str(mr.get("executedQty", "0")))
        filled += mq
        value += mq * _avg_fill_price(mr)
        oid = str(mr.get("orderId", oid))
    avg = (value / filled) if filled > 0 else Decimal("0")
    return {"executedQty": str(filled), "orderId": oid, "_avg": avg}


async def execute_borrow(
    sub_account_id: int,
    symbol: str,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    spread_feed: SpreadFeed = None,
    min_spread: Decimal = None,
    user_id: int = None,
    submission_event_callback=None,
    pre_submit_guard=None,
    inventory_guard=None,
    new_action_guard=None,
    operation_lock_token: str | None = None,
    operation_lock_redis=None,
    operation_lock_ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
    allow_open_increment: bool = False,
) -> int | None:
    """Phase 1: borrow the coin and hold it idle in the margin account (BORROWED_IDLE).
    Net-flat (owe coin, hold coin) — no directional exposure. Returns position id or None."""
    symbol = canonical_position_symbol(symbol)
    base_asset = normalize_asset(symbol)
    if not symbol or not base_asset:
        return None
    confirm_spread = rules.open_spread if min_spread is None else min_spread
    db = SessionLocal()
    operation_lock_guard = None
    if operation_lock_token is not None or operation_lock_redis is not None:
        operation_lock_guard = _OperationLockGuard(
            operation_lock_redis,
            sub_account_id,
            symbol,
            operation_lock_token or "",
            ttl_sec=operation_lock_ttl_sec,
        )
        # A caller that supplies a lock must prove ownership before any
        # private Binance preflight.  The final HTTP callback renews and
        # verifies the same token atomically immediately before POST.
        if not await operation_lock_guard.async_check():
            db.close()
            logger.warning(
                "Borrow blocked %s: account operation lock is not owned by caller",
                symbol,
            )
            return None
    # Serialize the read-before-create decision at the database boundary. The
    # Redis account-operation lease remains the cross-service fast path, while
    # this row lock prevents a caller that bypasses or outlives that lease from
    # creating a second lifecycle row before either borrow request is sent.
    account = _lock_sub_account(db, sub_account_id)
    if account is None:
        db.close()
        return None
    # Resolve the tenant before creating the position so every failure
    # cooldown and websocket update uses the same user-scoped key, including
    # direct/manual callers that omit ``user_id``.
    if user_id is None:
        user_id = getattr(account, "user_id", None)
        if user_id is None:
            user_id = _resolve_user_id(db, sub_account_id)
    account_owner = getattr(account, "user_id", None)
    if account_owner is not None and user_id is not None:
        try:
            if int(account_owner) != int(user_id):
                db.close()
                return None
        except (TypeError, ValueError, InvalidOperation):
            db.close()
            return None
    if new_action_guard is not None and not _pre_submit_guard_allows(
        new_action_guard
    ):
        logger.info("Borrow blocked %s: tenant pause gate is active", symbol)
        db.close()
        return None
    existing_conflict = _first_borrow_conflict(
        db,
        sub_account_id,
        symbol,
        allow_open_increment=allow_open_increment,
    )
    if existing_conflict is not None:
        logger.info(
            "Borrow blocked %s: in-flight position %s (%s) already owns this account/symbol",
            symbol,
            existing_conflict.id,
            existing_conflict.status,
        )
        db.close()
        return None
    position = Position(
        sub_account_id=sub_account_id,
        symbol=symbol,
        base_asset=base_asset,
        status="PENDING_BORROW",
        user_id=user_id,
    )
    db.add(position)
    try:
        db.commit()
    except IntegrityError:
        # The partial unique index is the last line of defense for callers
        # that race outside the Redis/row lock.  Never proceed to Binance when
        # another active row won the insert race.
        db.rollback()
        logger.info(
            "Borrow blocked %s: database active-position uniqueness conflict",
            symbol,
        )
        db.close()
        return None
    db.refresh(position)
    pos_id = position.id
    _publish_position_update(position, user_id, account_note)

    borrow_submission_started = False
    borrowed_before = None
    qty = Decimal("0")
    borrow_submit_guard = pre_submit_guard
    try:
        if not _execution_spread_sane(spread, rules):
            position.status = "FAILED"
            position.error_message = "Spread snapshot exceeds execution safety limits"
            db.commit()
            _publish_position_update(position, user_id, account_note)
            return None
        # interest-rate filter
        t0 = time.monotonic()
        interest_rate = await client.get_margin_interest_rate(base_asset)
        latency = int((time.monotonic() - t0) * 1000)
        if interest_rate > rules.interest_filter / 100:
            position.status = "FAILED"
            position.error_message = f"Interest rate {interest_rate} too high"
            db.commit()
            _publish_position_update(position, user_id, account_note)
            # High interest is specific to this margin account. Sibling
            # accounts must remain independently eligible.
            _set_borrow_fail_guard(
                user_id, sub_account_id, symbol, "INTEREST_RATE", ttl=300
            )
            db.close()
            return None
        position.borrow_interest_rate = interest_rate

        # delay + re-confirm spread still above the borrow threshold(含 ts 新鲜度,防陈旧缓存)
        # 负阈值(挂单差<0)=任何点差都借的囤券意图,点差质量/新鲜度与借币决策无关 → 跳过两道确认闸。
        # 否则冷门币(bookTicker 仅价/量变才推,常几十秒~分钟无 tick)会在「睡 borrow_delay_sec 后
        # 要求快照 ≤BORROW_FRESH_MS 新鲜；该值与 Rust/Python 执行新鲜度
        # 默认保持一致，避免借币落地被旧的独立阈值拖成分钟级随机延迟。
        skip_confirm = confirm_spread is not None and confirm_spread < 0
        # 负阈值零等待:确认闸已跳过时,borrow_delay_sec 的唯一意义(睡后复核点差)不复存在,
        # 该等待在负阈值路径纯属死等 → 连同省去，借币立即执行。正阈值路径行为不变。
        # API-side manual open passes no live SpreadFeed.  Its snapshot was
        # read immediately before this call, so waiting the configured engine
        # confirmation delay here would guarantee that the same snapshot turns
        # stale before the direct freshness check below.  Worker-driven opens
        # still keep the normal delay and second confirmation.
        if not skip_confirm and spread_feed is not None:
            await asyncio.sleep(rules.borrow_delay_sec)
        if spread_feed:
            current = spread_feed.get_symbol(symbol)
            if not _borrow_snapshot_ok(
                current,
                confirm_spread,
                skip_threshold=skip_confirm,
                max_age_ms=BORROW_FRESH_MS,
            ):
                position.status = "FAILED"
                position.error_message = (
                    f"Spread degraded/stale after delay: "
                    f"{current.spread_short if current else 'N/A'}% < {confirm_spread}% 或快照陈旧"
                )
                db.commit()
                _publish_position_update(position, user_id, account_note)
                _set_borrow_fail_guard(
                    user_id, sub_account_id, symbol, "SPREAD_STALE"
                )
                db.close()
                return None
            spread = current
        elif not is_spread_fresh(spread, max_age_ms=BORROW_FRESH_MS):
            # Direct/manual callers without a feed must still provide the Rust
            # per-leg receive fields; legacy snapshots fail closed.
            position.status = "FAILED"
            position.error_message = "Spread snapshot missing/freshness fields"
            db.commit()
            _publish_position_update(position, user_id, account_note)
            db.close()
            return None

        # quantity
        lot_info = await client.get_lot_size(symbol, "spot")
        price = spread.spot_ask
        from app.db.models import SymbolRule, AccountSymbolRule, SubAccount
        # 「金额限制」(借币金额上限,USDT)解析: 账户单币 → 单币通用 → 子账户全局
        cap_usdt = None
        asr_query = db.query(AccountSymbolRule).filter(
            AccountSymbolRule.sub_account_id == sub_account_id,
            AccountSymbolRule.symbol == symbol,
        )
        if user_id is None:
            asr_query = asr_query.filter(AccountSymbolRule.user_id.is_(None))
        else:
            asr_query = asr_query.filter(AccountSymbolRule.user_id == user_id)
        asr = asr_query.first()
        if asr is None and base_asset != symbol:
            asr_query = db.query(AccountSymbolRule).filter(
                AccountSymbolRule.sub_account_id == sub_account_id,
                AccountSymbolRule.symbol == base_asset,
            )
            if user_id is None:
                asr_query = asr_query.filter(AccountSymbolRule.user_id.is_(None))
            else:
                asr_query = asr_query.filter(AccountSymbolRule.user_id == user_id)
            asr = asr_query.first()
        if asr and asr.max_borrow_amount is not None:
            cap_usdt = asr.max_borrow_amount
        sr = None
        if user_id is not None:
            sr = db.query(SymbolRule).filter(
                SymbolRule.user_id == user_id, SymbolRule.symbol == symbol,
            ).first()
            if sr is None and base_asset != symbol:
                sr = db.query(SymbolRule).filter(
                    SymbolRule.user_id == user_id, SymbolRule.symbol == base_asset,
                ).first()
            if cap_usdt is None and sr and sr.max_borrow_amount is not None:
                cap_usdt = sr.max_borrow_amount
        if cap_usdt is None:
            if account and account.max_borrow_amount is not None:
                cap_usdt = account.max_borrow_amount

        cap_value = None
        if cap_usdt is not None:
            try:
                cap_value = Decimal(str(cap_usdt))
            except Exception:
                cap_value = Decimal("NaN")
            if not cap_value.is_finite() or cap_value <= 0:
                position.status = "FAILED"
                position.error_message = f"Borrow cap is disabled or invalid: {cap_usdt}"
                db.commit()
                _publish_position_update(position, user_id, account_note)
                return None

        # Resolve one borrow request independently from the cumulative cap. Account
        # symbol rules are the most specific layer and must not be ignored.
        eff_amount = _resolve_single_order_amount(
            db,
            sub_account_id,
            symbol,
            rules,
            user_id,
            account=account,
            account_symbol_rule=asr,
            symbol_rule=sr,
        )

        # 借币方式: 新枚举 borrow_mode 优先(config_loader 已归一化);兜底由旧 bool 推导。
        borrow_mode = getattr(rules, "borrow_mode", None) or ("otoco" if getattr(rules, "borrow_via_otoco", False) else "repay")
        # otoco/single/multi 三种都按「金额限制∩maxBorrowable×抵押率」借满;repay 维持单笔 order_amount。
        if cap_value is not None:
            # 挂单借币: 借满「金额限制」∩ maxBorrowable(币捏手上,后续按单笔分批对冲)
            preflight_error = None
            try:
                mb = await client.get_max_borrowable(base_asset)
                # get_max_borrowable 返回 {"amount":Decimal,"borrowLimit":Decimal};取实际可借 amount
                raw_max_borrowable = mb.get("amount") if isinstance(mb, dict) else mb
                max_borrowable = Decimal(str(raw_max_borrowable))
                if not max_borrowable.is_finite() or max_borrowable <= 0:
                    preflight_error = (
                        f"maxBorrowable returned no available borrow capacity "
                        f"(amount={raw_max_borrowable!r})"
                    )
            except BinanceAPIError:
                # Preserve Binance error semantics (notably -3045) so the
                # existing account/user inventory cooldown is still recorded.
                raise
            except Exception as exc:
                preflight_error = f"maxBorrowable preflight failed: {exc}"
            if preflight_error:
                logger.warning("Borrow preflight blocked %s: %s", symbol, preflight_error)
                position.status = "FAILED"
                position.error_message = preflight_error
                db.commit()
                _publish_position_update(position, user_id, account_note)
                _set_borrow_fail_guard(
                    user_id, sub_account_id, symbol, "MAX_BORROWABLE_PREFLIGHT"
                )
                db.close()
                return None
            try:
                borrowed_before = _margin_borrowed_principal(
                    await client.get_margin_account(), base_asset
                )
            except Exception as exc:
                message = f"cumulative borrow-cap debt preflight failed: {exc}"
                logger.warning("Borrow preflight blocked %s: %s", symbol, message)
                position.status = "FAILED"
                position.error_message = message
                db.commit()
                _publish_position_update(position, user_id, account_note)
                _set_borrow_fail_guard(
                    user_id, sub_account_id, symbol, "DEBT_PREFLIGHT"
                )
                db.close()
                return None
            # collateral_ratio 安全垫:不借满 maxBorrowable,按比例留出抵押冗余(1=借满,旧行为)
            ratio = Decimal(str(getattr(rules, "collateral_ratio", 1) or 1))
            if ratio <= 0 or ratio > 1:
                ratio = Decimal("1")
            eff_max = max_borrowable * ratio
            try:
                recorded_notional = _recorded_active_borrow_notional(
                    db, sub_account_id, symbol
                )
            except Exception as exc:
                message = f"cumulative borrow-cap history preflight failed: {exc}"
                logger.warning("Borrow preflight blocked %s: %s", symbol, message)
                position.status = "FAILED"
                position.error_message = message
                db.commit()
                _publish_position_update(position, user_id, account_note)
                _set_borrow_fail_guard(
                    user_id, sub_account_id, symbol, "CAP_HISTORY_PREFLIGHT"
                )
                db.close()
                return None
            # Use the larger exposure measure. The immutable recorded value
            # prevents a price decline from reopening historical capacity;
            # Binance principal at the current price covers legacy rows,
            # appreciation, and debt created outside this engine.
            used_cap_usdt = max(recorded_notional, borrowed_before * price)
            remaining_cap_usdt = max(Decimal("0"), cap_value - used_cap_usdt)
            per_bite_qty = Decimal(str(eff_amount)) / price
            target = min(remaining_cap_usdt / price, eff_max, per_bite_qty)
            qty = round_to_step(target, lot_info["stepSize"])
        else:
            # 单笔金额(order_amount)优先级: 单币规则(SymbolRule) > 子账户(single_order_amount) > 全局
            qty = usdt_to_quantity(eff_amount, price, lot_info["stepSize"], lot_info["minQty"])
        if qty <= 0:
            position.status = "FAILED"
            position.error_message = "Order amount too small for lot size"
            db.commit()
            _publish_position_update(position, user_id, account_note)
            db.close()
            return None

        # min_borrow_usdt 下限:名义低于此跳过,不做尘埃单(0=不启用)
        min_usdt = Decimal(str(getattr(rules, "min_borrow_usdt", 0) or 0))
        if min_usdt > 0 and qty * price < min_usdt:
            position.status = "FAILED"
            position.error_message = f"Borrow notional {float(qty * price):.2f} < min_borrow_usdt {float(min_usdt)}"
            db.commit()
            _publish_position_update(position, user_id, account_note)
            db.close()
            return None
        # A new Position must be large enough to execute its own spot hedge.
        # Small cumulative-cap tails belong to an existing BORROWED_IDLE row's
        # direct-borrow top-up path; submitting them as standalone tranches
        # used to borrow successfully and only then schedule an avoidable
        # repay because the spot leg cannot meet Binance NOTIONAL.
        standalone_price = Decimal(str(getattr(spread, "spot_bid", 0) or 0))
        standalone_min = max(Decimal("5.5"), min_usdt)
        if (
            not standalone_price.is_finite()
            or standalone_price <= 0
            or qty * standalone_price < standalone_min
        ):
            position.status = "FAILED"
            position.error_message = (
                f"Borrow notional {qty * standalone_price if standalone_price > 0 else 0} "
                f"is below standalone hedge minimum {standalone_min} USDT"
            )
            db.commit()
            _publish_position_update(position, user_id, account_note)
            return None

        # ── P0-1 净期望收益闸(成本线) ── 借币前评估这笔套利的净期望 E(USDT);此刻所有成本变量齐全
        # (点差/名义/利率/费率/缓冲)且尚未真花钱。shadow=只记录不拦(先跑一周看会拦掉多少);
        # enforce=E≤0 直接放弃(结构性亏损不开);off=不评估。评估结果写 Redis 供 market-monitor E 榜。
        gate_mode = getattr(rules, "net_gate_mode", "shadow") or "shadow"
        # 逐币强制 enforce 观察名单:命中即升 enforce(即便全局 shadow),对恒负期望币单独止血
        if gate_mode != "off" and symbol in _FORCE_ENFORCE_SYMBOLS:
            gate_mode = "enforce"
        expected_e = None
        e_break = None
        if gate_mode != "off":
            hold_hours = float(getattr(rules, "repay_ban_minutes", 30) or 30) / 60.0
            expected_e, e_break = _compute_net_expect(
                spread_short_pct=float(getattr(spread, "spread_short", 0) or 0),
                notional_usdt=float(qty * price),
                interest_rate_daily=float(interest_rate or 0),
                hold_hours=hold_hours,
                f_spot=float(getattr(rules, "taker_fee_spot", TAKER_FEE_RATE) or TAKER_FEE_RATE),
                f_fut=float(getattr(rules, "taker_fee_futures", TAKER_FEE_RATE) or TAKER_FEE_RATE),
                buffer_pct=float(getattr(rules, "open_spread_buffer", 0) or 0),
            )
            # 负阈值豁免:挂单差<0(skip_confirm)=用户显式囤券/测试意图(-1 等),enforce 让路只记录
            # 不拦——与 idle 超时"负阈值=故意囤券不适用"同一原则。E 仍写榜供观察;阈值回正后闸恢复把关。
            decision = "borrow" if (gate_mode == "shadow" or skip_confirm or expected_e > 0) else "reject"
            _publish_net_eval(user_id, symbol, expected_e, e_break, decision, gate_mode)
            if gate_mode == "enforce" and expected_e <= 0 and skip_confirm:
                logger.info(f"[netgate] 负阈值豁免 {symbol}: E={expected_e:.4f}U≤0 仍放行(挂单差<0=显式囤券/测试)")
            if gate_mode == "enforce" and expected_e <= 0 and not skip_confirm:
                position.status = "FAILED"
                position.error_message = (f"净期望闸拒开: E={expected_e:.4f}U≤0 "
                                          f"(点差捕获{e_break['spread_capture']:.4f}−利息{e_break['interest_cost']:.4f}"
                                          f"−手续费{e_break['fee_cost']:.4f}−摩擦{e_break['tick_cost']:.4f})")
                logger.info(f"Net-expect gate REJECT {symbol}: {position.error_message}")
                db.commit()
                db.close()
                # 拒开冷却键(5min):①worker 见键即显示状态"E闸拒开"并跳过重试——否则用户只看到
                # "运行中"却始终不借(反馈黑洞);②防每秒重试制造 FAILED 洪水(实测11秒20行)+白烧
                # 利率查询 REST。点差是活的,5min 后重评一次。与 -3045 noinv 键同款 sync 写法。
                try:
                    _uid_g = user_id
                    if _uid_g is None:
                        _db2 = SessionLocal()
                        try:
                            _uid_g = _resolve_user_id(_db2, sub_account_id)
                        finally:
                            _db2.close()
                    import redis as _r
                    from app.config import settings as _s
                    rc = _r.from_url(_s.redis_url, decode_responses=True)
                    rc.set(f"engine:{_uid_g}:netgate:{symbol}", f"E={expected_e:.4f}U", ex=300)
                    rc.close()
                except Exception:
                    pass
                return None
            if expected_e is not None and expected_e <= 0:
                logger.info(f"[shadow] Net-expect≤0 {symbol}: E={expected_e:.4f}U (借币仍继续, gate={gate_mode})")

        margin_buy_mode = borrow_mode in ("single", "multi", "otoco")
        if borrowed_before is None:
            try:
                borrowed_before = _margin_borrowed_principal(
                    await client.get_margin_account(), base_asset
                )
            except Exception as exc:
                message = f"borrow debt preflight failed: {exc}"
                logger.warning("Borrow preflight blocked %s: %s", symbol, message)
                position.status = "FAILED"
                position.error_message = message
                db.commit()
                _publish_position_update(position, user_id, account_note)
                _set_borrow_fail_guard(
                    user_id, sub_account_id, symbol, "DEBT_PREFLIGHT"
                )
                db.close()
                return None

        # 借币前最终二次确认: 算 qty 期间(get_lot_size / maxBorrowable / debt REST)又过去若干 ms,
        # 重读最新点差,确认仍新鲜且 ≥ 阈值 → 否则放弃,减少在已消失点差上完成 ~160ms 借币。
        # 负阈值同上跳过(囤券不依赖点差存活)。
        latest = spread
        if spread_feed:
            latest = spread_feed.get_symbol(symbol)
            if not _borrow_snapshot_ok(
                latest,
                confirm_spread,
                skip_threshold=skip_confirm,
                max_age_ms=BORROW_FRESH_MS,
            ):
                position.status = "FAILED"
                position.error_message = (
                    f"Spread vanished/stale before borrow: "
                    f"{latest.spread_short if latest else 'N/A'} (需 >={confirm_spread}, 新鲜<{BORROW_FRESH_MS}ms)"
                )
                db.commit()
                _publish_position_update(position, user_id, account_note)
                _set_borrow_fail_guard(
                    user_id, sub_account_id, symbol, "SPREAD_STALE"
                )
                db.close()
                return None

        # Pub/sub reloads minimize propagation delay, but a coroutine already
        # in preflight can still hold the former threshold. Re-read the current
        # account > symbol > global hierarchy immediately before submission.
        try:
            authoritative_spread = _resolve_authoritative_borrow_threshold(
                db,
                sub_account_id,
                symbol,
                rules,
                user_id,
                confirm_spread,
            )
        except Exception as exc:
            position.status = "FAILED"
            position.error_message = f"Authoritative borrow-rule recheck failed: {exc}"
            db.commit()
            _publish_position_update(position, user_id, account_note)
            return None

        def owns_active_position() -> bool:
            # This callback is evaluated by BinanceTradingClient immediately
            # before the POST.  The helper reads scalar columns instead of
            # trusting this session's cached Position, while preserving any
            # unrelated uncommitted lifecycle fields.
            return _fresh_borrow_position_allows_submission(
                pos_id,
                sub_account_id,
                symbol,
                user_id=user_id,
                db=db,
            )

        borrow_submit_guard = _borrow_submit_guard(
            pre_submit_guard,
            inventory_guard,
            qty,
            position_guard=owns_active_position,
            operation_lock_guard=operation_lock_guard,
            new_action_guard=new_action_guard,
        )
        authoritative_skip = authoritative_spread < 0
        if not _borrow_snapshot_ok(
            latest,
            authoritative_spread,
            skip_threshold=authoritative_skip,
            max_age_ms=BORROW_FRESH_MS,
        ):
            position.status = "FAILED"
            position.error_message = (
                "Borrow rule changed before submission: "
                f"spread={latest.spread_short if latest else 'N/A'}% "
                f"requires >= {authoritative_spread}%"
            )
            db.commit()
            _publish_position_update(position, user_id, account_note)
            return None
        if (
            gate_mode == "enforce"
            and expected_e is not None
            and expected_e <= 0
            and not authoritative_skip
        ):
            position.status = "FAILED"
            position.error_message = (
                "Net-expect gate became authoritative before submission: "
                f"E={expected_e:.4f}U"
            )
            db.commit()
            _publish_position_update(position, user_id, account_note)
            return None
        confirm_spread = authoritative_spread
        skip_confirm = authoritative_skip

        # MARGIN_BUY borrows only the shortage needed to place the order. If a
        # previous bite is still free in the margin wallet, submitting another
        # same-sized IOC consumes that free balance and creates zero new debt.
        # Preserve the configured per-bite amount by using direct BORROW for
        # incremental bites; that endpoint is independently clamped to 2/s.
        incremental_direct_borrow = margin_buy_mode and borrowed_before > 0
        submission_mode = (
            "repay-incremental" if incremental_direct_borrow else borrow_mode
        )

        # borrow → idle
        # 借币方式分支(borrow_mode,见上方归一化):
        #   single        → 单腿裸 MARGIN_BUY(order-count 仅1笔,最省额度,~10/s)
        #   multi         → 多账户并联,单账户借币动作用单腿(协调在 worker 层)
        #   otoco+legs=1  → 等同单腿
        #   otoco+legs2/3 → IOC OTO/OTOCO(2/3单撤,币留手上)
        #   repay         → borrow-repay 直接借(默认,不改变现网行为)
        legs = int(getattr(rules, "otoco_legs", 2) or 2)
        bid = Decimal(str(getattr(spread, "spot_bid", 0) or 0))
        if not _authoritative_borrow_enabled(
            db, sub_account_id, symbol, user_id
        ):
            position.status = "FAILED"
            position.error_message = "Borrow cancelled: account or symbol opening is disabled"
            db.commit()
            _publish_position_update(position, user_id, account_note)
            return None
        if operation_lock_guard is not None and not await operation_lock_guard.async_check():
            position.status = "FAILED"
            position.error_message = "Borrow cancelled: account operation lock ownership was lost"
            db.commit()
            _publish_position_update(position, user_id, account_note)
            return None
        if not _pre_submit_guard_allows(borrow_submit_guard):
            if _inventory_guard_rejected(borrow_submit_guard):
                _discard_unsent_borrow_position(
                    db,
                    position,
                    user_id=user_id,
                    account_note=account_note,
                    quantity=qty,
                )
                return None
            position.status = "FAILED"
            position.error_message = (
                "Borrow cancelled: another active account/symbol position exists"
                if _active_position_guard_rejected(borrow_submit_guard)
                else "Borrow cancelled: symbol pause gate is active"
                if _pause_guard_rejected(borrow_submit_guard)
                else "Borrow cancelled: account operation lock ownership was lost"
                if _operation_lock_guard_rejected(borrow_submit_guard)
                else "Borrow cancelled: rules changed before submission"
            )
            db.commit()
            _publish_position_update(position, user_id, account_note)
            return None
        # Persist the submission boundary before network I/O. A process death
        # from this point onward cannot be reclaimed as a definite failure.
        pre_submission_status = position.status
        pre_submission_error = position.error_message
        position.status = BORROW_SUBMITTING
        position.error_message = (
            "Borrow request submitting; outcome not yet confirmed: "
            f"principal_before={borrowed_before}; requested_qty={qty}; mode={submission_mode}"
        )
        db.commit()
        _publish_position_update(position, user_id, account_note)
        borrow_submission_started = True
        try:
            await _emit_borrow_submission_event(
                submission_event_callback, BORROW_SUBMISSION_STARTED
            )
        except asyncio.CancelledError:
            try:
                await _finish_borrow_submission_event(submission_event_callback)
            finally:
                borrow_submission_started = False
                position.status = pre_submission_status
                position.error_message = pre_submission_error
                db.commit()
                _publish_position_update(position, user_id, account_note)
            raise
        opening_enabled = _authoritative_borrow_enabled(
            db, sub_account_id, symbol, user_id
        )
        if operation_lock_guard is not None and not await operation_lock_guard.async_check():
            guard_allowed = False
            borrow_submit_guard.rejection_reason = "operation_lock"
        else:
            guard_allowed = (
                _pre_submit_guard_allows(borrow_submit_guard)
                if opening_enabled
                else False
            )
        if not opening_enabled or not guard_allowed:
            inventory_rejected = (
                guard_allowed is False
                and _inventory_guard_rejected(borrow_submit_guard)
            )
            try:
                await _finish_borrow_submission_event(submission_event_callback)
            finally:
                borrow_submission_started = False
                if inventory_rejected:
                    _discard_unsent_borrow_position(
                        db,
                        position,
                        user_id=user_id,
                        account_note=account_note,
                        quantity=qty,
                    )
                else:
                    failure_message = (
                        "Borrow cancelled: another active account/symbol position exists"
                        if _active_position_guard_rejected(borrow_submit_guard)
                        else "Borrow cancelled: symbol pause gate is active"
                        if _pause_guard_rejected(borrow_submit_guard)
                        else "Borrow cancelled: opening switch or rules changed before network I/O"
                    )
                    if _cas_borrow_failure(db, position, failure_message):
                        _publish_position_update(position, user_id, account_note)
            return None
        t0 = time.monotonic()
        try:
            if incremental_direct_borrow:
                await client.margin_borrow(
                    base_asset, qty, **_pre_submit_kwargs(borrow_submit_guard)
                )
            elif borrow_mode in ("single", "multi") or (borrow_mode == "otoco" and legs == 1):
                await client.margin_borrow_single(
                    symbol,
                    qty,
                    bid=bid if bid > 0 else None,
                    **_pre_submit_kwargs(borrow_submit_guard),
                )
            elif borrow_mode == "otoco":
                await client.margin_borrow_otoco(
                    symbol,
                    qty,
                    legs=max(2, legs),
                    **_pre_submit_kwargs(borrow_submit_guard),
                )
            else:
                await client.margin_borrow(
                    base_asset, qty, **_pre_submit_kwargs(borrow_submit_guard)
                )
        finally:
            await _finish_borrow_submission_event(submission_event_callback)
        latency = int((time.monotonic() - t0) * 1000)

        if borrowed_before is not None:
            # HTTP success only means Binance accepted the IOC/OTO request. It
            # does not prove that MARGIN_BUY created debt: an existing free
            # balance can satisfy the order and produce a zero/partial loan.
            # Keep BORROW_SUBMITTING while verification is in flight. If the
            # process exits in this window, stale recovery must preserve the
            # ambiguous outcome instead of authorizing a retry.
            position.error_message = "Borrow accepted; verifying margin debt"
            db.commit()
            _publish_position_update(position, user_id, account_note)
            try:
                actual_borrow_qty = await _confirm_margin_borrow_delta(
                    client, base_asset, borrowed_before
                )
            except MarginDebtVerificationUnavailable as exc:
                message = _mark_borrow_outcome_unknown(
                    db,
                    position,
                    user_id=user_id,
                    account_note=account_note,
                    requested_qty=qty,
                    principal_before=borrowed_before,
                    reason=exc,
                    latency=latency,
                )
                logger.error("Borrow verification unavailable %s: %s", symbol, message)
                try:
                    await notifier.notify_error(account_note, f"borrow verify {symbol}", message)
                except Exception:
                    logger.debug("borrow verification notification failed", exc_info=True)
                return None
            if actual_borrow_qty <= 0:
                message = (
                    f"MARGIN_BUY created no debt (principal delta={actual_borrow_qty}, "
                    f"request qty={qty})"
                )
                logger.warning("Borrow verification rejected %s: %s", symbol, message)
                position.status = "FAILED"
                position.error_message = message
                db.commit()
                _publish_position_update(position, user_id, account_note)
                _log_trade(
                    db, pos_id, sub_account_id, "BORROW", symbol,
                    quantity=Decimal("0"), status="FAILED", error=message, latency=latency,
                )
                _set_borrow_fail_guard(
                    user_id, sub_account_id, symbol, "DEBT_DELTA_ZERO"
                )
                return None

            step = Decimal(str(lot_info["stepSize"]))
            min_qty = Decimal(str(lot_info.get("minQty", "0") or "0"))
            sellable_qty = round_to_step(actual_borrow_qty, step)
            required_notional = max(Decimal("5.5"), min_usdt)
            price_ref = bid if bid > 0 else price
            verification_error = None
            if actual_borrow_qty > qty + Decimal("0.00000001"):
                verification_error = (
                    f"confirmed debt delta {actual_borrow_qty} exceeds request qty {qty}"
                )
            elif sellable_qty <= 0 or sellable_qty < min_qty:
                verification_error = (
                    f"confirmed debt delta {actual_borrow_qty} is below spot minQty {min_qty}"
                )
            elif sellable_qty * price_ref < required_notional:
                verification_error = (
                    f"confirmed debt notional {sellable_qty * price_ref} is below "
                    f"executable minimum {required_notional} USDT"
                )
            if verification_error:
                # A real but non-executable debt must stay tracked. Existing
                # PENDING_REPAY processing reads authoritative account debt and
                # repays it; marking FAILED here would turn it into an orphan
                # that can be hidden by another active position in this asset.
                message = f"MARGIN_BUY debt scheduled for repay: {verification_error}"
                logger.error("Borrow verification rejected %s: %s", symbol, message)
                position.status = "PENDING_REPAY"
                position.borrow_qty = actual_borrow_qty
                position.borrow_usdt_amount = (
                    actual_borrow_qty * price
                ).quantize(Decimal("0.0001"), rounding=ROUND_UP)
                position.borrowed_at = datetime.now(timezone.utc)
                position.error_message = message
                db.commit()
                _publish_position_update(position, user_id, account_note)
                _log_trade(
                    db, pos_id, sub_account_id, "BORROW_VERIFY", symbol,
                    quantity=actual_borrow_qty, status="FAILED", error=message,
                    latency=latency,
                )
                _set_borrow_fail_guard(
                    user_id,
                    sub_account_id,
                    symbol,
                    "DEBT_DELTA_UNEXECUTABLE",
                    ttl=1800,
                )
                _publish_balance_refresh(user_id)
                try:
                    await notifier.notify_error(
                        account_note, f"borrow verify {symbol}", message
                    )
                except Exception:
                    logger.debug("borrow verification notification failed", exc_info=True)
                return None
            qty = actual_borrow_qty

        position.status = "BORROWED_IDLE"
        position.borrow_qty = qty
        position.borrow_usdt_amount = (qty * price).quantize(
            Decimal("0.0001"), rounding=ROUND_UP
        )
        position.borrowed_at = datetime.now(timezone.utc)
        position.error_message = None
        # 记开仓预期净收益 E + 分项(事后与 round_net_pnl 校准闸的准度)
        if expected_e is not None:
            position.expected_e = Decimal(str(round(expected_e, 4)))
            try:
                import json as _j
                position.e_breakdown = _j.dumps(e_break)
            except Exception:
                pass
        db.commit()
        _log_trade(db, pos_id, sub_account_id, "BORROW", symbol, quantity=qty, status="SUCCESS", latency=latency)
        logger.info(f"Borrowed (idle): {symbol} qty={qty}")
        # 写后即时刷新:借到币 → 让该用户 dashboard 现币/借币列秒级更新,不等 10s 轮询
        _uid = user_id if user_id is not None else _resolve_user_id(db, sub_account_id)
        _publish_balance_refresh(_uid)
        # 持仓实时推送:让前端 positions 立即含这条 BORROWED_IDLE(切换成真实持仓行),不等轮询
        _publish_position_update(position, _uid, account_note)
        try:
            await notifier.notify_new_borrow(account_note, symbol, qty, qty * price)
        except Exception as e:
            logger.debug(f"notify_new_borrow failed: {e}")
        return pos_id

    except BinancePreSubmitRejected as e:
        logger.info("Borrow cancelled before Binance submission: %s", e)
        borrow_submission_started = False
        if _inventory_guard_rejected(borrow_submit_guard):
            _discard_unsent_borrow_position(
                db,
                position,
                user_id=user_id,
                account_note=account_note,
                quantity=qty,
            )
            return None
        failure_message = (
            "Borrow cancelled: another active account/symbol position exists"
            if _active_position_guard_rejected(borrow_submit_guard)
            else "Borrow cancelled: symbol pause gate is active"
            if _pause_guard_rejected(borrow_submit_guard)
            else "Borrow cancelled: rules changed before Binance submission"
        )
        if _cas_borrow_failure(db, position, failure_message):
            _publish_position_update(position, user_id, account_note)
        return None
    except BinanceAPIError as e:
        logger.error(f"Borrow failed: {e}")
        if borrow_submission_started and _borrow_outcome_is_unknown(e):
            elapsed = int((time.monotonic() - t0) * 1000)
            message = _mark_borrow_outcome_unknown(
                db,
                position,
                user_id=user_id,
                account_note=account_note,
                requested_qty=qty,
                principal_before=borrowed_before,
                reason=e,
                latency=elapsed,
            )
            try:
                await notifier.notify_error(
                    account_note, f"borrow outcome unknown {symbol}", message
                )
            except Exception:
                logger.debug("unknown borrow notification failed", exc_info=True)
            return None
        position.status = "FAILED"
        position.error_message = str(e)
        db.commit()
        _publish_position_update(position, user_id, account_note)
        _log_trade(db, pos_id, sub_account_id, "BORROW", symbol, status="FAILED", error=str(e))
        # -3045 = 币安杠杆池该币无可借库存。这是相当稳定的市场状态(一个币池子空,常持续数小时),
        # 故冷却设 30 分钟:半小时重试一次足够捕捉库存恢复,又避免每 5 分钟重试一波刷高错误率/SAPI。
        # 注:不再自动拉黑——「无券」是临时供给状态,不等于「币本身坏」;仅做冷却(自动失效自动恢复),
        # 黑名单回归人工维护。库存恢复后冷却 key 到期即自然恢复推送/显示。
        if "-3045" in str(e):
            try:
                import redis as _r
                from app.config import settings as _s
                rc = _r.from_url(_s.redis_url, decode_responses=True)
                # Capacity is account-scoped. A user-wide cooldown here can
                # block a sibling account whose collateral still gives it a
                # positive maxBorrowable result. The worker's user/symbol lock
                # already serializes requests, while each failed account keeps
                # its own 30-minute no-inventory marker.
                rc.set(no_inventory_key(sub_account_id, symbol), "1", ex=1800)
                rc.close()
            except Exception:
                pass
        else:
            # 通用借币失败冷却(120s):-3045有noinv/E闸有netgate,但其它错误码(-3055等)原来
            # 零冷却 → 每周期重试刷 FAILED 行(实测sub9 -3055 十分钟467条)+打错误通知。
            # worker 见键显示"借币异常"并跳过;120s后重试(错误多为账户态/临时性,自愈即恢复)。
            _set_borrow_fail_guard(
                user_id,
                sub_account_id,
                symbol,
                str(getattr(e, "api_code", None) or "ERR"),
            )
            await notifier.notify_error(account_note, f"borrow {symbol}", str(e))
        return None
    except Exception as e:
        logger.error(f"Borrow failed unexpectedly: {e}", exc_info=True)
        if borrow_submission_started and _borrow_outcome_is_unknown(e):
            elapsed = int((time.monotonic() - t0) * 1000)
            _mark_borrow_outcome_unknown(
                db,
                position,
                user_id=user_id,
                account_note=account_note,
                requested_qty=qty,
                principal_before=borrowed_before,
                reason=e,
                latency=elapsed,
            )
            return None
        position.status = "FAILED"
        position.error_message = str(e)
        db.commit()
        _publish_position_update(position, user_id, account_note)
        return None
    finally:
        db.close()


async def _execute_borrow_topup_locked(
    position_id: int,
    sub_account_id: int,
    symbol: str,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    *,
    user_id: int | None,
    redis_client,
    operation_lock_token: str,
    submission_deadline: float,
    submission_event_callback=None,
    pre_submit_guard=None,
    inventory_guard=None,
    new_action_guard=None,
) -> Decimal:
    """Perform a cumulative borrow top-up while the account/asset lock is held.

    The helper deliberately keeps all exchange I/O inside the lock. A
    ``BORROWED_IDLE`` row is shared by manual actions and sibling workers; a
    top-up that only locks the Worker loop can race a repay or hedge and leave
    an unowned debt. Every MARGIN_BUY is therefore wrapped by a durable
    ``BORROW_SUBMITTING`` state and confirmed against Binance's principal
    delta before the row is updated.
    """
    from app.db.models import AccountSymbolRule, SubAccount, SymbolRule

    symbol = canonical_position_symbol(symbol)
    base_asset = normalize_asset(symbol)
    if not symbol or not base_asset or client is None:
        return Decimal("0")

    # The public wrapper owns this lease.  Carry its token all the way to the
    # final Binance boundary; checking only the DB row is insufficient because
    # a manual/API action can acquire the same account lock after lease expiry.
    operation_lock_guard = _OperationLockGuard(
        redis_client, sub_account_id, symbol, operation_lock_token
    )
    if not await operation_lock_guard.async_check():
        logger.info("Top-up blocked %s: account operation lock is no longer owned", symbol)
        return Decimal("0")

    # Every borrow route uses the same configured per-request bite. The
    # direct-borrow route therefore needs the same in-place cumulative-cap
    # completion as the order-based routes.
    borrow_mode = getattr(rules, "borrow_mode", None) or (
        "otoco" if getattr(rules, "borrow_via_otoco", False) else "repay"
    )
    if borrow_mode not in ("single", "multi", "otoco", "repay"):
        return Decimal("0")

    db = SessionLocal()
    try:
        # Resolve and verify ownership before reading any rule. A sub-account
        # id is globally unique today, but legacy rule/position rows are not
        # consistently tenant-tagged; never let a caller select another
        # tenant's position by id.
        account = _lock_sub_account(db, sub_account_id)
        if account is None:
            logger.warning("Top-up blocked: sub-account %s does not exist", sub_account_id)
            return Decimal("0")
        # ``is_enabled`` is the opening gate for direct/manual callers too.
        # Workers check it before entering this helper, but the execution
        # boundary must enforce it independently so a stale worker or an API
        # caller cannot create another borrow after an account is disabled.
        if getattr(account, "is_enabled", True) is False:
            logger.info("Top-up blocked: sub-account %s is disabled", sub_account_id)
            return Decimal("0")
        account_owner = getattr(account, "user_id", None)
        if account_owner is None:
            if user_id is not None:
                logger.warning(
                    "Top-up blocked: account %s has no owner but caller supplied user %s",
                    sub_account_id,
                    user_id,
                )
                return Decimal("0")
            owner_id = None
        else:
            try:
                owner_id = int(account_owner)
            except (TypeError, ValueError):
                logger.warning("Top-up blocked: invalid owner for account %s", sub_account_id)
                return Decimal("0")
            if user_id is not None:
                try:
                    if int(user_id) != owner_id:
                        logger.warning(
                            "Top-up blocked: account %s belongs to user %s, caller is %s",
                            sub_account_id,
                            owner_id,
                            user_id,
                        )
                        return Decimal("0")
                except (TypeError, ValueError):
                    return Decimal("0")
        effective_user_id = owner_id

        if new_action_guard is not None and not _pre_submit_guard_allows(
            new_action_guard
        ):
            logger.info("Top-up blocked %s: tenant pause gate is active", symbol)
            return Decimal("0")

        position = db.query(Position).filter(
            Position.id == position_id,
            Position.sub_account_id == sub_account_id,
            Position.symbol == symbol,
        ).first()
        if position is None or position.status != "BORROWED_IDLE":
            return Decimal("0")
        conflicting_position = _first_borrow_conflict(
            db,
            sub_account_id,
            symbol,
            exclude_position_id=position_id,
            allow_open_increment=False,
        )
        if conflicting_position is not None:
            logger.error(
                "Top-up blocked %s: position %s conflicts with in-flight row %s",
                symbol,
                position_id,
                getattr(conflicting_position, "id", "?"),
            )
            return Decimal("0")

        def owns_topup_position() -> bool:
            return (
                _topup_before_submission_deadline(submission_deadline)
                and _fresh_topup_position_allows_submission(
                    position_id,
                    sub_account_id,
                    symbol,
                    user_id=effective_user_id,
                )
            )
        position_owner = getattr(position, "user_id", None)
        if position_owner is not None:
            try:
                if effective_user_id is None or int(position_owner) != int(effective_user_id):
                    logger.warning(
                        "Top-up blocked: position %s ownership mismatch (position=%s account=%s)",
                        position_id,
                        position_owner,
                        effective_user_id,
                    )
                    return Decimal("0")
            except (TypeError, ValueError):
                return Decimal("0")
        elif effective_user_id is not None:
            # Backfill only after ownership has been proven. The assignment is
            # committed together with the first confirmed chunk, so a failed
            # preflight does not mutate a legacy row.
            position.user_id = effective_user_id

        try:
            already = Decimal(str(position.borrow_qty or "0"))
        except (TypeError, ValueError, ArithmeticError):
            return Decimal("0")
        if not already.is_finite() or already <= 0:
            # A top-up must never manufacture ownership for a row that has no
            # confirmed principal. Such a row belongs in reconciliation.
            logger.warning("Top-up blocked: position %s has invalid borrow_qty=%r", position_id, position.borrow_qty)
            return Decimal("0")

        # Both local WS receive timestamps and execution-price sanity are
        # required before any private Binance request. Negative thresholds are
        # an explicit pre-borrow policy, but they do not bypass freshness.
        if not _execution_spread_sane(spread, rules) or not is_spread_fresh(
            spread, max_age_ms=BORROW_FRESH_MS
        ):
            return Decimal("0")
        try:
            price = Decimal(str(spread.spot_ask))
        except (AttributeError, TypeError, ValueError, ArithmeticError):
            return Decimal("0")
        if not price.is_finite() or price <= 0:
            return Decimal("0")

        pair_symbols = (symbol, base_asset) if base_asset != symbol else (symbol,)

        def _account_rule():
            for candidate in pair_symbols:
                query = db.query(AccountSymbolRule).filter(
                    AccountSymbolRule.sub_account_id == sub_account_id,
                    AccountSymbolRule.symbol == candidate,
                )
                if effective_user_id is None:
                    query = query.filter(AccountSymbolRule.user_id.is_(None))
                else:
                    query = query.filter(AccountSymbolRule.user_id == effective_user_id)
                row = query.first()
                if row is not None:
                    return row
            return None

        def _symbol_rule():
            for candidate in pair_symbols:
                query = db.query(SymbolRule).filter(SymbolRule.symbol == candidate)
                if effective_user_id is None:
                    query = query.filter(SymbolRule.user_id.is_(None))
                else:
                    query = query.filter(SymbolRule.user_id == effective_user_id)
                row = query.first()
                if row is not None:
                    return row
            return None

        account_rule = _account_rule()
        symbol_rule = _symbol_rule()
        if account_rule is not None and getattr(account_rule, "is_enabled", True) is False:
            return Decimal("0")

        # Resolve the effective borrow line with the same account > symbol >
        # global precedence used by execute_borrow. A negative line remains a
        # deliberate force/pre-borrow setting; all other lines are hard gates.
        threshold = getattr(rules, "borrow_spread", None)
        if threshold is None:
            threshold = getattr(rules, "open_spread", None)
        if symbol_rule is not None and getattr(symbol_rule, "borrow_spread", None) is not None:
            threshold = symbol_rule.borrow_spread
        if account_rule is not None and getattr(account_rule, "borrow_spread", None) is not None:
            threshold = account_rule.borrow_spread
        try:
            threshold = Decimal(str(threshold))
            buffer_value = Decimal(str(getattr(rules, "open_spread_buffer", 0) or 0))
        except (TypeError, ValueError, ArithmeticError):
            return Decimal("0")
        if not threshold.is_finite() or not buffer_value.is_finite():
            return Decimal("0")
        effective_threshold = threshold + buffer_value
        if not effective_threshold.is_finite():
            return Decimal("0")
        if not _borrow_snapshot_ok(
            spread,
            effective_threshold,
            skip_threshold=effective_threshold < 0,
            max_age_ms=BORROW_FRESH_MS,
        ):
            return Decimal("0")

        # Amount cap precedence mirrors execute_borrow. Zero is an explicit
        # disable; malformed values fail closed instead of falling back to a
        # larger parent cap.
        cap_raw = None
        if account_rule is not None and getattr(account_rule, "max_borrow_amount", None) is not None:
            cap_raw = account_rule.max_borrow_amount
        if cap_raw is None and symbol_rule is not None and getattr(symbol_rule, "max_borrow_amount", None) is not None:
            cap_raw = symbol_rule.max_borrow_amount
        if cap_raw is None:
            cap_raw = getattr(account, "max_borrow_amount", None)
        if cap_raw is None:
            return Decimal("0")
        try:
            cap_usdt = Decimal(str(cap_raw))
        except (TypeError, ValueError, ArithmeticError):
            return Decimal("0")
        if not cap_usdt.is_finite() or cap_usdt <= 0:
            return Decimal("0")

        try:
            lot_info = await client.get_lot_size(symbol, "spot")
            step = Decimal(str(lot_info.get("stepSize", "0")))
            min_qty = Decimal(str(lot_info.get("minQty", "0") or "0"))
        except Exception as exc:
            logger.warning("Top-up preflight lot-size failed %s: %s", symbol, exc)
            return Decimal("0")
        if not step.is_finite() or step <= 0 or not min_qty.is_finite() or min_qty < 0:
            return Decimal("0")

        # The current principal is authoritative for capacity. The immutable
        # Position notional prevents a price drop from reopening an already
        # consumed USDT cap; debt created outside this engine is also counted.
        try:
            principal_before = _margin_borrowed_principal(
                await client.get_margin_account(), base_asset
            )
            recorded_notional = _recorded_active_borrow_notional(
                db, sub_account_id, symbol
            )
        except Exception as exc:
            logger.warning("Top-up debt preflight failed %s: %s", symbol, exc)
            return Decimal("0")
        used_cap_usdt = max(recorded_notional, principal_before * price)
        remaining_cap_usdt = cap_usdt - used_cap_usdt
        if remaining_cap_usdt <= 0:
            return Decimal("0")

        try:
            initial_max = await client.get_max_borrowable(base_asset)
            raw_max = initial_max.get("amount") if isinstance(initial_max, dict) else initial_max
            max_borrowable = Decimal(str(raw_max))
        except BinanceAPIError as exc:
            if getattr(exc, "api_code", None) == -3045 or "-3045" in str(exc):
                try:
                    await _topup_redis_set(
                        redis_client,
                        no_inventory_key(sub_account_id, symbol), "1", ex=1800
                    )
                except Exception:
                    logger.debug("Unable to persist top-up no-inventory marker", exc_info=True)
            logger.warning("Top-up maxBorrowable rejected %s: %s", symbol, exc)
            return Decimal("0")
        except Exception as exc:
            # A missing private capacity read is not permission to borrow by
            # the configured cap. This is the critical fail-closed boundary.
            logger.warning("Top-up maxBorrowable unavailable %s: %s", symbol, exc)
            return Decimal("0")
        if not max_borrowable.is_finite() or max_borrowable <= 0:
            try:
                await _topup_redis_set(
                    redis_client,
                    borrow_capacity_key(
                        effective_user_id, sub_account_id, symbol
                    ),
                    "1",
                    ex=300,
                )
            except Exception:
                logger.debug(
                    "Unable to persist top-up capacity marker", exc_info=True
                )
            return Decimal("0")

        try:
            ratio = Decimal(str(getattr(rules, "collateral_ratio", 1) or 1))
        except (TypeError, ValueError, ArithmeticError):
            return Decimal("0")
        if not ratio.is_finite() or ratio <= 0:
            return Decimal("0")
        ratio = min(Decimal("1"), ratio)

        # Keep the initial intersection as an upper bound, then re-check both
        # debt and maxBorrowable before each subsequent chunk. This handles a
        # collateral change while preserving confirmed chunks if a later
        # request is unavailable.
        target_qty = round_to_step(
            min(remaining_cap_usdt / price, max_borrowable * ratio), step
        )
        if target_qty <= 0:
            return Decimal("0")

        eff_amount = _resolve_single_order_amount(
            db,
            sub_account_id,
            symbol,
            rules,
            effective_user_id,
            account=account,
            account_symbol_rule=account_rule,
            symbol_rule=symbol_rule,
        )
        if not eff_amount.is_finite() or eff_amount <= 0:
            return Decimal("0")
        chunk_qty = eff_amount / price
        if not chunk_qty.is_finite() or chunk_qty <= 0:
            return Decimal("0")

        try:
            min_usdt = Decimal(str(getattr(rules, "min_borrow_usdt", 0) or 0))
        except (TypeError, ValueError, ArithmeticError):
            return Decimal("0")
        if not min_usdt.is_finite() or min_usdt < 0:
            return Decimal("0")
        # Top-ups use direct BORROW and merge into an already executable idle
        # position. The operator's normal per-request floor still applies to
        # regular chunks, but the final quantity-lot-rounded cap tail may be
        # smaller; it is not a standalone dust position.
        required_notional = min_usdt
        confirmed_total = Decimal("0")
        first_chunk = True

        while confirmed_total < target_qty:
            # Stop starting chunks before the Redis lock enters its final
            # confirmation reserve. A chunk that crossed the durable boundary
            # below is always confirmed or quarantined before returning.
            if not _topup_before_submission_deadline(submission_deadline):
                break
            # Refresh the authoritative principal before each request. This
            # catches manual borrow/repay activity and avoids crossing the cap
            # if Binance's first response has not yet propagated.
            if first_chunk:
                current_recorded = recorded_notional
            else:
                try:
                    principal_before = _margin_borrowed_principal(
                        await client.get_margin_account(), base_asset
                    )
                    current_recorded = _recorded_active_borrow_notional(
                        db, sub_account_id, symbol
                    )
                except Exception as exc:
                    logger.warning("Top-up debt refresh failed %s: %s", symbol, exc)
                    break
            remaining_now = cap_usdt - max(current_recorded, principal_before * price)
            if remaining_now <= 0:
                break
            if first_chunk:
                max_now = max_borrowable
            else:
                try:
                    max_snapshot = await client.get_max_borrowable(base_asset)
                    raw_max_now = (
                        max_snapshot.get("amount")
                        if isinstance(max_snapshot, dict)
                        else max_snapshot
                    )
                    max_now = Decimal(str(raw_max_now))
                except BinanceAPIError as exc:
                    if getattr(exc, "api_code", None) == -3045 or "-3045" in str(exc):
                        try:
                            await _topup_redis_set(
                                redis_client,
                                no_inventory_key(sub_account_id, symbol), "1", ex=1800
                            )
                        except Exception:
                            logger.debug("Unable to persist top-up no-inventory marker", exc_info=True)
                    logger.warning("Top-up maxBorrowable stopped %s: %s", symbol, exc)
                    break
                except Exception as exc:
                    logger.warning("Top-up maxBorrowable refresh failed %s: %s", symbol, exc)
                    break
            if not max_now.is_finite() or max_now <= 0:
                try:
                    await _topup_redis_set(
                        redis_client,
                        borrow_capacity_key(
                            effective_user_id, sub_account_id, symbol
                        ),
                        "1",
                        ex=300,
                    )
                except Exception:
                    logger.debug(
                        "Unable to persist refreshed top-up capacity marker",
                        exc_info=True,
                    )
                break
            allowed_now = min(
                remaining_now / price,
                max_now * ratio,
                target_qty - confirmed_total,
            )
            this_qty = round_to_step(min(chunk_qty, allowed_now), step)
            if this_qty <= 0 or this_qty < min_qty:
                break
            cap_tail_qty = round_to_step(remaining_now / price, step)
            is_final_cap_tail = cap_tail_qty > 0 and this_qty == cap_tail_qty
            if (
                required_notional > 0
                and this_qty * price < required_notional
                and not is_final_cap_tail
            ):
                break

            chunk_submit_guard = _borrow_submit_guard(
                pre_submit_guard,
                inventory_guard,
                this_qty,
                position_guard=owns_topup_position,
                operation_lock_guard=operation_lock_guard,
                new_action_guard=new_action_guard,
            )

            if not _authoritative_borrow_enabled(
                db, sub_account_id, symbol, effective_user_id
            ) or not _pre_submit_guard_allows(chunk_submit_guard):
                break

            # Commit the durable submission boundary before network I/O. A
            # worker restart from this point is recovered as UNKNOWN, so it
            # cannot submit a duplicate top-up blindly.
            pre_submission_error = position.error_message
            submission_message = (
                "Borrow top-up submitting; outcome not yet confirmed: "
                f"principal_before={principal_before}; requested_qty={this_qty}"
            )
            if not _cas_topup_position(
                db,
                position,
                "BORROWED_IDLE",
                {
                    Position.status: BORROW_SUBMITTING,
                    Position.error_message: submission_message,
                },
            ):
                break
            _publish_position_update(position, effective_user_id, account_note)
            try:
                await _emit_borrow_submission_event(
                    submission_event_callback, BORROW_SUBMISSION_STARTED
                )
            except asyncio.CancelledError:
                try:
                    await _finish_borrow_submission_event(submission_event_callback)
                finally:
                    if _restore_topup_borrowed_idle(
                        db, position, pre_submission_error
                    ):
                        _publish_position_update(
                            position, effective_user_id, account_note
                        )
                raise
            if not _authoritative_borrow_enabled(
                db, sub_account_id, symbol, effective_user_id
            ) or not _pre_submit_guard_allows(chunk_submit_guard):
                try:
                    await _finish_borrow_submission_event(submission_event_callback)
                finally:
                    if _restore_topup_borrowed_idle(
                        db,
                        position,
                        "Borrow top-up cancelled: opening switch, rules, "
                        "deadline, or position state changed before network I/O",
                    ):
                        _publish_position_update(
                            position, effective_user_id, account_note
                        )
                return confirmed_total
            started_at = time.monotonic()
            try:
                # This row already owns confirmed free base-asset from an
                # earlier bite.  Repeating MARGIN_BUY can consume that free
                # balance without creating any new debt, so the cumulative
                # cap would remain stuck at the first chunk.  Use the direct
                # BORROW endpoint for top-ups; the initial bite still uses
                # the order-based route and its faster order-count pacing.
                await client.margin_borrow(
                    base_asset,
                    this_qty,
                    **_pre_submit_kwargs(chunk_submit_guard),
                )
            except BinancePreSubmitRejected as exc:
                if _restore_topup_borrowed_idle(
                    db,
                    position,
                    f"Borrow top-up cancelled before Binance submission: {exc}",
                ):
                    _publish_position_update(
                        position, effective_user_id, account_note
                    )
                return confirmed_total
            except BinanceAPIError as exc:
                elapsed = int((time.monotonic() - started_at) * 1000)
                if _borrow_outcome_is_unknown(exc):
                    _mark_borrow_topup_outcome_unknown(
                        db,
                        position,
                        user_id=effective_user_id,
                        account_note=account_note,
                        requested_qty=this_qty,
                        principal_before=principal_before,
                        reason=exc,
                        latency=elapsed,
                    )
                    return confirmed_total
                if _restore_topup_borrowed_idle(
                    db, position, f"Borrow top-up rejected: {exc}"
                ):
                    _publish_position_update(
                        position, effective_user_id, account_note
                    )
                if getattr(exc, "api_code", None) == -3045 or "-3045" in str(exc):
                    try:
                        await _topup_redis_set(
                            redis_client,
                            no_inventory_key(sub_account_id, symbol), "1", ex=1800
                        )
                    except Exception:
                        logger.debug("Unable to persist top-up no-inventory marker", exc_info=True)
                else:
                    _set_borrow_fail_guard(
                        effective_user_id,
                        sub_account_id,
                        symbol,
                        str(getattr(exc, "api_code", None) or "TOPUP_REJECTED"),
                        ttl=120,
                    )
                return confirmed_total
            except asyncio.CancelledError as exc:
                elapsed = int((time.monotonic() - started_at) * 1000)
                _mark_borrow_topup_outcome_unknown(
                    db,
                    position,
                    user_id=effective_user_id,
                    account_note=account_note,
                    requested_qty=this_qty,
                    principal_before=principal_before,
                    reason=exc,
                    latency=elapsed,
                )
                raise
            except Exception as exc:
                elapsed = int((time.monotonic() - started_at) * 1000)
                _mark_borrow_topup_outcome_unknown(
                    db,
                    position,
                    user_id=effective_user_id,
                    account_note=account_note,
                    requested_qty=this_qty,
                    principal_before=principal_before,
                    reason=exc,
                    latency=elapsed,
                )
                return confirmed_total
            finally:
                await _finish_borrow_submission_event(submission_event_callback)

            elapsed = int((time.monotonic() - started_at) * 1000)
            if _cas_topup_position(
                db,
                position,
                BORROW_SUBMITTING,
                {
                    Position.error_message: (
                        "Borrow top-up accepted; verifying margin debt"
                    ),
                },
            ):
                _publish_position_update(position, effective_user_id, account_note)
            try:
                actual_delta = await _confirm_margin_borrow_delta(
                    client, base_asset, principal_before
                )
            except MarginDebtVerificationUnavailable as exc:
                _mark_borrow_topup_outcome_unknown(
                    db,
                    position,
                    user_id=effective_user_id,
                    account_note=account_note,
                    requested_qty=this_qty,
                    principal_before=principal_before,
                    reason=exc,
                    latency=elapsed,
                )
                return confirmed_total

            if actual_delta <= 0:
                # This is a confirmed non-borrow (usually a free margin coin
                # satisfying MARGIN_BUY). Do not increase Position quantity or
                # claim success; leave the existing idle row intact.
                zero_delta_message = (
                    f"MARGIN_BUY created no new debt (principal delta={actual_delta}, "
                    f"request qty={this_qty})"
                )
                restored = _restore_topup_borrowed_idle(
                    db, position, zero_delta_message
                )
                if restored:
                    _publish_position_update(
                        position, effective_user_id, account_note
                    )
                try:
                    _log_trade(
                        db,
                        position.id,
                        sub_account_id,
                        "BORROW_TOPUP_VERIFY",
                        symbol,
                        quantity=Decimal("0"),
                        status="FAILED",
                        error=zero_delta_message,
                        latency=elapsed,
                    )
                except Exception:
                    logger.debug("Unable to record zero top-up delta", exc_info=True)
                _set_borrow_fail_guard(
                    effective_user_id,
                    sub_account_id,
                    symbol,
                    "TOPUP_DEBT_DELTA_ZERO",
                )
                return confirmed_total

            # A delta larger than the request proves that another debt change
            # raced the operation. Do not assign that debt to this row or
            # continue borrowing under an unverified cap.
            if actual_delta > this_qty + Decimal("0.00000001"):
                message = (
                    f"confirmed top-up debt delta {actual_delta} exceeds request qty {this_qty}"
                )
                _mark_borrow_topup_outcome_unknown(
                    db,
                    position,
                    user_id=effective_user_id,
                    account_note=account_note,
                    requested_qty=this_qty,
                    principal_before=principal_before,
                    reason=message,
                    latency=elapsed,
                )
                return confirmed_total

            # Persist only the authoritative delta. A partial fill is valid and
            # leaves a smaller remaining target for the next chunk.
            old_qty = Decimal(str(position.borrow_qty or "0"))
            old_notional_raw = getattr(position, "borrow_usdt_amount", None)
            if old_notional_raw is None:
                old_notional = old_qty * price
            else:
                try:
                    old_notional = Decimal(str(old_notional_raw))
                except (TypeError, ValueError, ArithmeticError):
                    old_notional = old_qty * price
            if not old_notional.is_finite() or old_notional < 0:
                old_notional = old_qty * price
            new_qty = old_qty + actual_delta
            new_notional = (
                old_notional + actual_delta * price
            ).quantize(Decimal("0.0001"), rounding=ROUND_UP)
            if not _cas_topup_position(
                db,
                position,
                BORROW_SUBMITTING,
                {
                    Position.borrow_qty: new_qty,
                    Position.borrow_usdt_amount: new_notional,
                    Position.status: "BORROWED_IDLE",
                    Position.error_message: None,
                },
            ):
                logger.error(
                    "Confirmed top-up for position %s could not be merged because state moved to %s",
                    position_id,
                    position.status,
                )
                _set_borrow_fail_guard(
                    effective_user_id,
                    sub_account_id,
                    symbol,
                    "TOPUP_STATE_CHANGED_AFTER_SUBMIT",
                )
                return confirmed_total
            try:
                _log_trade(
                    db,
                    position.id,
                    sub_account_id,
                    "BORROW_TOPUP",
                    symbol,
                    quantity=actual_delta,
                    status="SUCCESS",
                    latency=elapsed,
                )
            except Exception:
                logger.warning("Unable to record top-up trade %s", symbol, exc_info=True)
            _publish_balance_refresh(effective_user_id)
            _publish_position_update(position, effective_user_id, account_note)
            try:
                if notifier is not None:
                    await notifier.notify_new_borrow(
                        account_note,
                        symbol,
                        actual_delta,
                        actual_delta * price,
                    )
            except Exception:
                logger.debug("Top-up notification failed %s", symbol, exc_info=True)
            confirmed_total += actual_delta
            first_chunk = False

        return confirmed_total
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()


async def execute_borrow_topup(
    position_id: int,
    sub_account_id: int,
    symbol: str,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    user_id: int = None,
    *,
    redis_client=None,
    submission_event_callback=None,
    pre_submit_guard=None,
    inventory_guard=None,
    new_action_guard=None,
) -> Decimal:
    """Top up an existing ``BORROWED_IDLE`` position to its USDT cap.

    The public wrapper owns the shared account/asset lifecycle lock. Worker
    callers pass their long-lived asyncio Redis client; API/manual callers may
    omit it and the wrapper creates a short-lived client. Coordination errors
    fail closed and never issue a Binance request.
    """
    symbol = canonical_position_symbol(symbol)
    if not symbol:
        return Decimal("0")
    own_redis = False
    redis = redis_client
    if redis is None:
        try:
            import redis.asyncio as aioredis
            from app.config import settings

            redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            own_redis = True
        except Exception as exc:
            logger.warning("Top-up coordination unavailable for %s: %s", symbol, exc)
            return Decimal("0")

    try:
        owner = f"borrow-topup:{user_id if user_id is not None else 'unknown'}:{sub_account_id}"
        try:
            async with account_operation_lock(
                redis,
                sub_account_id,
                symbol,
                owner=owner,
                ttl_sec=ACCOUNT_OPERATION_LOCK_TTL_SEC,
            ) as operation_lock_token:
                submission_deadline = (
                    _topup_clock() + TOPUP_SUBMISSION_WINDOW_SEC
                )
                return await _execute_borrow_topup_locked(
                    position_id,
                    sub_account_id,
                    symbol,
                    spread,
                    rules,
                    client,
                    notifier,
                    account_note,
                    user_id=user_id,
                    redis_client=redis,
                    operation_lock_token=operation_lock_token,
                    submission_deadline=submission_deadline,
                    submission_event_callback=submission_event_callback,
                    pre_submit_guard=pre_submit_guard,
                    inventory_guard=inventory_guard,
                    new_action_guard=new_action_guard,
                )
        except (AccountOperationLockBusy, AccountOperationLockUnavailable) as exc:
            logger.info("Top-up deferred %s: %s", symbol, exc)
            return Decimal("0")
    finally:
        if own_redis and redis is not None:
            try:
                close = getattr(redis, "aclose", None)
                if callable(close):
                    result = close()
                    if inspect.isawaitable(result):
                        await result
                else:
                    close = getattr(redis, "close", None)
                    if callable(close):
                        result = close()
                        if inspect.isawaitable(result):
                            await result
            except Exception:
                logger.debug("Unable to close top-up Redis client", exc_info=True)


async def execute_hedge(
    position: Position,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    futures_client: BinanceTradingClient = None,
    user_id: int = None,
    pre_submit_guard=None,
    operation_lock_token: str | None = None,
    operation_lock_redis=None,
    operation_lock_ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
):
    """Phase 2: sell the borrowed coin on spot (short) + futures long (hedge).
    BORROWED_IDLE → SPOT_SOLD → OPEN. Full rollback on failure.
    futures_client: hedge_via_master 时传主账户 client(合约腿);None=合约同子账户(原行为)。"""
    # The Worker/API owns an account+symbol Redis lease while this lifecycle
    # transition runs.  Carry the exact token to every opening Binance POST;
    # checking it only before the DB CAS leaves a race where a lease expires
    # during preflight and a replacement worker submits the same hedge.
    operation_lock_guard = None
    if operation_lock_token is not None or operation_lock_redis is not None:
        operation_lock_guard = _OperationLockGuard(
            operation_lock_redis,
            getattr(position, "sub_account_id", 0),
            canonical_position_symbol(getattr(position, "symbol", "")),
            operation_lock_token or "",
            ttl_sec=operation_lock_ttl_sec,
        )
        if not await operation_lock_guard.async_check():
            logger.info(
                "Hedge %s blocked: account operation lock is not owned by caller",
                getattr(position, "symbol", "?"),
            )
            return False

    opening_guard = pre_submit_guard
    if operation_lock_guard is not None:
        # Reuse the same final-boundary adapter as borrow/top-up.  It keeps the
        # ordinary rules-generation callback and the async Redis fencing check
        # in one callback understood by BinanceTradingClient._request.
        opening_guard = _borrow_submit_guard(
            pre_submit_guard,
            None,
            Decimal("0"),
            operation_lock_guard=operation_lock_guard,
        )

    if not _pre_submit_guard_allows(opening_guard):
        return False
    if not _execution_spread_sane(spread, rules):
        logger.warning(
            "Hedge %s deferred: spread exceeds execution safety limits",
            getattr(position, "symbol", "?"),
        )
        return False
    master_mode = bool(getattr(rules, "hedge_via_master", False))
    if master_mode and futures_client is None:
        # Never sell the borrowed spot leg when the required master hedge
        # client is unavailable. Leave BORROWED_IDLE for a later retry.
        logger.error(
            "Hedge %s blocked: hedge_via_master is enabled but no master futures client was supplied",
            getattr(position, "symbol", "?"),
        )
        return
    if not master_mode and futures_client is not None:
        # A caller that supplies a second client while master mode is off is
        # almost certainly an account-routing bug; fail closed rather than
        # recording a misleading hedge_account=master position.
        logger.error(
            "Hedge %s blocked: futures client supplied while hedge_via_master is disabled",
            getattr(position, "symbol", "?"),
        )
        return
    if master_mode and futures_client is not None:
        # Production master clients use a negative synthetic account id. Do
        # not reject lightweight test doubles that do not expose this field.
        synthetic_id = getattr(futures_client, "_sub_account_id", None)
        if synthetic_id is not None and synthetic_id >= 0:
            logger.error(
                "Hedge %s blocked: supplied futures client is not the master client (synthetic id=%s)",
                getattr(position, "symbol", "?"), synthetic_id,
            )
            return
    if not is_spread_fresh(spread, max_age_ms=BORROW_FRESH_MS):
        # The spread supplies spot sizing and maker prices.  Leave the
        # position BORROWED_IDLE so the worker can retry on a fresh snapshot;
        # never sell a borrowed asset using a legacy/stale quote.
        logger.warning("Hedge %s deferred: spread snapshot is stale or legacy", getattr(position, "symbol", "?"))
        return
    fc = futures_client if futures_client is not None else client
    # ── C2 反插针二次确认: 卖现货/合约做多前,用独立 REST 盘口复核 WS 点差真伪 ──
    # WS 单源(Rust→Redis spreads)若某腿插针,重采同一路抓不住持久幻价;REST bookTicker
    # 是唯一不经该链路的独立源。用与 rust-engine/src/spread/calculator.rs 完全一致的公式
    # 从 REST 价重算两轴点差,任一轴与 WS 快照偏离超容差 → 判幻价;取价失败/超时同样
    # fail-closed → 不认领、不下单、return(留 BORROWED_IDLE 下轮重试)。仅生产 client 强制
    # (具备 rest_book_ticker);轻量 recovery/test 双桩无此方法 → 豁免,不破坏既有测试。
    # 该闸只会「多一个不开仓的理由」,绝不促成本不该开的仓,故对已修复功能零回退风险。
    if HEDGE_REST_CONFIRM_ENABLED and callable(getattr(client, "rest_book_ticker", None)):
        _c2_symbol = canonical_position_symbol(getattr(position, "symbol", ""))
        try:
            _c2_spot, _c2_fut = await asyncio.wait_for(
                asyncio.gather(
                    client.rest_book_ticker(_c2_symbol, "spot"),
                    fc.rest_book_ticker(_c2_symbol, "futures"),
                ),
                timeout=HEDGE_REST_CONFIRM_TIMEOUT_SEC,
            )
            _r_sb, _r_sa = _c2_spot["bid"], _c2_spot["ask"]
            _r_fb, _r_fa = _c2_fut["bid"], _c2_fut["ask"]
            if not all(v.is_finite() and v > 0 for v in (_r_sb, _r_sa, _r_fb, _r_fa)):
                raise ValueError("rest bookTicker returned non-positive price")
            # 与 Rust calculator 逐字一致:期空 (spot_bid-fut_ask)/fut_ask;期多 (fut_bid-spot_ask)/spot_ask
            _rest_ss = (_r_sb - _r_fa) / _r_fa * Decimal(100)
            _rest_sl = (_r_fb - _r_sa) / _r_sa * Decimal(100)
            _ws_ss = Decimal(str(spread.spread_short))
            _ws_sl = Decimal(str(spread.spread_long))
            _d_ss = abs(_rest_ss - _ws_ss)
            _d_sl = abs(_rest_sl - _ws_sl)
            if _d_ss > HEDGE_REST_CONFIRM_TOL_PP or _d_sl > HEDGE_REST_CONFIRM_TOL_PP:
                logger.warning(
                    "Hedge %s deferred: REST anti-spike mismatch "
                    "(ws_short=%s rest_short=%s d=%s | ws_long=%s rest_long=%s d=%s | tol=%s)",
                    _c2_symbol, _ws_ss, _rest_ss, _d_ss, _ws_sl, _rest_sl, _d_sl,
                    HEDGE_REST_CONFIRM_TOL_PP,
                )
                return False
        except Exception as _c2_exc:
            # fail-closed:独立复核拿不到/异常/超时 → 不认领不下单,留 BORROWED_IDLE 下轮重试
            logger.warning(
                "Hedge %s deferred: REST anti-spike confirm unavailable (%s)",
                _c2_symbol, _c2_exc,
            )
            return False
    db = SessionLocal()
    # 跨进程互斥(API 手动对冲 vs 引擎自动): DB 级 CAS 认领,只有一方能推进
    # Persist the hedge route together with the lifecycle claim, before any
    # spot or futures request.  If the process exits in the HEDGING/SPOT_SOLD
    # window, crash recovery must know which futures account owns the leg;
    # waiting until the first fill leaves the row permanently ambiguous.
    original_hedge_account = getattr(position, "hedge_account", None)
    # Worker/API callers normally pass a fully-loaded Position.  Keep the
    # identity predicates strict when those fields are present, while allowing
    # lightweight recovery/test callers that provide only an id and symbol;
    # the freshly loaded row is still validated before any exchange request.
    claim_query = db.query(Position).filter(
        Position.id == position.id,
        Position.status == "BORROWED_IDLE",
    )
    incoming_sub_account_id = getattr(position, "sub_account_id", None)
    if incoming_sub_account_id is not None:
        claim_query = claim_query.filter(
            Position.sub_account_id == incoming_sub_account_id
        )
    claim_user_id = user_id
    if claim_user_id is None:
        claim_user_id = getattr(position, "user_id", None)
    if claim_user_id is not None:
        claim_query = claim_query.filter(Position.user_id == claim_user_id)
    claimed = claim_query.update({
        "status": "HEDGING",
        "hedge_account": "master" if master_mode else "sub",
    }, synchronize_session=False)
    db.commit()
    if not claimed:
        db.close()
        return
    pos = db.query(Position).get(position.id)
    symbol = canonical_position_symbol(pos.symbol)
    sub_account_id = pos.sub_account_id
    # Resolve the tenant before reading any account-symbol override.  A
    # sub-account id is normally globally unique, but legacy rows can still
    # contain duplicate/mis-owned AccountSymbolRule records; execution sizing
    # must never depend on query insertion order across tenants.
    effective_user_id = user_id
    if effective_user_id is None:
        effective_user_id = getattr(pos, "user_id", None)
    if effective_user_id is None:
        effective_user_id = _resolve_user_id(db, sub_account_id)
    expected_hedge_account = "master" if master_mode else "sub"

    # Re-read the authoritative admission gate after claiming the row. A
    # delisting/blacklist event may arrive between borrow confirmation and
    # this hedge attempt; stale pushed rows must not create a new spot sale.
    if not _authoritative_borrow_enabled(
        db, sub_account_id, symbol, effective_user_id
    ):
        pos.error_message = (
            "Opening blocked by the current account/symbol admission gate; "
            "no new spot or futures order was submitted"
        )
        db.commit()
        _publish_position_update(pos, effective_user_id, account_note)
        db.close()
        return False

    def owns_hedge_position() -> bool:
        return _fresh_hedge_position_allows_submission(
            pos.id,
            sub_account_id,
            symbol,
            user_id=effective_user_id,
            hedge_account=expected_hedge_account,
        )

    # From this point onward every opening POST carries a fresh DB identity
    # check in addition to the Redis lease.  The pre-claim guard above only
    # protects the cheap preflight; it cannot validate the newly claimed row.
    opening_guard = _borrow_submit_guard(
        pre_submit_guard,
        None,
        Decimal("0"),
        position_guard=owns_hedge_position,
        operation_lock_guard=operation_lock_guard,
    )
    _publish_position_update(pos, user_id, account_note)

    def _restore_borrowed_idle() -> None:
        pos.status = "BORROWED_IDLE"
        pos.hedge_account = original_hedge_account
        db.commit()
        _publish_position_update(pos, user_id, account_note)

    async def _invalidate_master(reason: str) -> None:
        if futures_client is None:
            return
        try:
            from engine.trading.master_client import invalidate_master_futures_client

            await invalidate_master_futures_client(
                effective_user_id,
                futures_client,
                reason=reason,
            )
        except Exception:
            logger.warning(
                "Unable to invalidate master futures client after %s",
                reason,
                exc_info=True,
            )

    if not _pre_submit_guard_allows(opening_guard):
        _restore_borrowed_idle()
        db.close()
        return False

    # 每币种执行质量覆盖(slippage_pct / follow_type): 账户·币种 → 单币种 → 全局,空则跟随上层
    _asr = _sr = None
    try:
        import dataclasses
        from app.db.models import SymbolRule as _SR, AccountSymbolRule as _ASR
        _base = symbol.replace("USDT", "")
        ov_slip = ov_follow = None
        asr_query = db.query(_ASR).filter(
            _ASR.sub_account_id == sub_account_id, _ASR.symbol.in_([symbol, _base]),
        )
        if effective_user_id is None:
            asr_query = asr_query.filter(_ASR.user_id.is_(None))
        else:
            asr_query = asr_query.filter(_ASR.user_id == effective_user_id)
        _asr = asr_query.first()
        if _asr is not None:
            ov_slip, ov_follow = _asr.slippage_pct, _asr.follow_type
        if (ov_slip is None or not ov_follow) and user_id is not None:
            _sr = db.query(_SR).filter(
                _SR.user_id == user_id, _SR.symbol.in_([symbol, _base]),
            ).first()
            if _sr is not None:
                if ov_slip is None:
                    ov_slip = _sr.slippage_pct
                if not ov_follow:
                    ov_follow = _sr.follow_type
        _repl = {}
        if ov_slip is not None:
            _repl["slippage_pct"] = ov_slip
        if ov_follow:
            _repl["follow_type"] = ov_follow
        if _repl:
            rules = dataclasses.replace(rules, **_repl)
            logger.debug(f"per-symbol exec override {symbol}: {_repl}")
    except Exception as _e:
        logger.debug(f"per-symbol override resolve failed {symbol}: {_e}")
    pos_id = pos.id
    qty = pos.borrow_qty

    # Opening tranches have their own control. They must not inherit the
    # single-borrow request amount: the operator may borrow in 20U bites but
    # hedge in 50U tranches (or vice versa).
    try:
        effective_order_amount = _resolve_hedge_order_amount(
            db,
            sub_account_id,
            symbol,
            rules,
            effective_user_id,
            account_symbol_rule=_asr,
            symbol_rule=_sr,
        )
    except Exception as exc:
        # Sizing lookup must never sell more than the borrowed position. A
        # transient rule read therefore degrades to one full tranche.
        logger.warning("Hedge %s: single-order rule lookup failed: %s", symbol, exc)
        effective_order_amount = Decimal("0")

    # 主账户模式: 卖出前先预检+预留合约保证金,欠资不动现货(回到 BORROWED_IDLE 重试)
    reserved = None
    if futures_client is not None:
        if not _pre_submit_guard_allows(opening_guard):
            _restore_borrowed_idle()
            db.close()
            return False
        reserved = await _master_margin_precheck(
            futures_client,
            symbol,
            qty,
            spread,
            notifier,
            account_note,
            pre_submit_guard=opening_guard,
        )
        if reserved is None:
            _restore_borrowed_idle()
            db.close()
            return False

    fut_filled = {"qty": Decimal("0")}   # cumulative futures fill for rollback
    # Keep an in-memory marker for the narrow window where the spot response
    # has reported a fill but the durable state transition has not completed.
    # A final lock/rules rejection after that point must compensate the sold
    # quantity; treating it as an unsent request would strand a naked short.
    opening_spot_filled = Decimal("0")
    try:
        # One opening tranche is an atomic pair: sell one spot batch, then
        # immediately open the same futures quantity before selling the next
        # batch. This bounds both per-order notional and the naked-short window.
        spot_lot = await client.get_lot_size(symbol, "spot")
        futures_lot = await fc.get_lot_size(symbol, "futures")
        price_ref = spread.spot_ask if (spread.spot_ask and spread.spot_ask > 0) else Decimal("0")
        per_batch = _hedge_batch_size(
            qty,
            price_ref,
            effective_order_amount,
            spot_lot["stepSize"],
            getattr(pos, "borrow_usdt_amount", None),
        )
        if per_batch <= 0:
            per_batch = qty
        # Preserve the configurable stabilization delay without sleeping while
        # a spot batch is naked. Any delay happens before the first pair.
        stabilize = float(getattr(rules, "stabilize_sec", 0) or 0)
        if stabilize > 0:
            await asyncio.sleep(min(stabilize, 10))

        if not _pre_submit_guard_allows(opening_guard):
            _restore_borrowed_idle()
            return False

        # Either routing mode can drift after Worker startup. Revalidate the
        # account that will actually receive the futures leg immediately
        # before the first destructive spot sale. An unreadable or dual-side
        # result leaves the borrowed coin untouched.
        futures_route = "master" if futures_client is not None else "sub-account"
        try:
            position_mode_reader = getattr(fc, "get_position_mode")
            dual_side = await position_mode_reader()
        except Exception as exc:
            reason = (
                f"{futures_route} position mode unreadable before spot sell: {exc}"
            )
            logger.error("Hedge %s blocked: %s", symbol, reason)
            pos.error_message = reason
            _restore_borrowed_idle()
            await _invalidate_master(reason)
            try:
                await notifier.notify_error(
                    account_note,
                    f"hedge {symbol}",
                    f"{('主账户' if futures_client is not None else '子账户')}合约持仓模式读取失败，"
                    "已保留借币且未卖出现货；请检查 API 权限和 One-way 设置",
                )
            except Exception:
                pass
            return False
        if dual_side:
            reason = (
                f"{futures_route} futures account is in Hedge Mode; "
                "One-way mode is required"
            )
            logger.error("Hedge %s blocked: %s", symbol, reason)
            pos.error_message = reason
            _restore_borrowed_idle()
            await _invalidate_master(reason)
            try:
                await notifier.notify_error(
                    account_note,
                    f"hedge {symbol}",
                    f"{('主账户' if futures_client is not None else '子账户')}合约当前为 Hedge Mode，"
                    "已保留借币且未卖出现货；请切换为 One-way Mode",
                )
            except Exception:
                pass
            return False

        total_sold = Decimal("0")
        total_spot_value = Decimal("0")
        spot_price_unresolved = False
        total_hedged = Decimal("0")
        total_futures_value = Decimal("0")
        last_spot_oid = ""
        last_futures_oid = ""
        remaining = qty
        first = True
        while remaining > 0:
            b = round_to_step(per_batch if remaining > per_batch else remaining, spot_lot["stepSize"])
            if b <= 0:
                break
            # 尾批名义额低于现货 NOTIONAL 下限(5U)会被 -1013 拒掉并触发整单回滚 ——
            # 已卖出部分时直接收尾,剩余借币留在账户(净持平,还币时按全部负债买回)
            if price_ref > 0 and b * price_ref < Decimal("5.5"):
                if total_sold > 0:
                    # 尾批收尾(原行为): 已卖出部分成立,剩余借币留账,还币时按全部负债买回
                    logger.info(f"Hedge {symbol}: tail batch {b} below min notional, selling stops at {total_sold}")
                    break
                if remaining * price_ref >= Decimal("5.5"):
                    # 首批过小但整体足额: 抬批量到最小名义(合并小批),避免首批 -1013 整单回滚
                    _step_txt = spot_lot["stepSize"]
                    _step = Decimal(str(_step_txt))
                    bumped = round_to_step(Decimal("5.5") / price_ref, _step_txt)
                    while _step > 0 and bumped * price_ref < Decimal("5.5"):
                        bumped += _step
                    b = round_to_step(min(remaining, bumped), _step_txt)
                    if b <= 0 or b * price_ref < Decimal("5.5"):
                        logger.info(f"Hedge {symbol}: cannot form min-notional batch, keep borrowed idle")
                        _restore_borrowed_idle()
                        return False
                    logger.info(f"Hedge {symbol}: first batch bumped to {b} for min notional")
                else:
                    # 整体名义不足 5.5U: 不下注定失败的单,保持已借币待卖(等行情/追加借币)
                    logger.info(f"Hedge {symbol}: total {remaining} below min notional, keep borrowed idle")
                    _restore_borrowed_idle()
                    return False
            # Every opening batch is a fresh financial submission. Keep the
            # same rules-generation and account-operation fences on all
            # batches, not only the first one; otherwise a lease/rules change
            # during a multi-batch hedge could authorize an unpaired leg.
            # The durable Position identity fence applies even when a legacy
            # or direct caller did not provide a Redis lease.  The lease adds
            # an atomic cross-process fence, but it must not be the condition
            # that enables the database/status guard.
            batch_guard = opening_guard
            spot_guard = batch_guard
            if not _authoritative_borrow_enabled(
                db, sub_account_id, symbol, effective_user_id
            ):
                if total_sold > 0:
                    # Preserve already paired exchange fills for recovery. Do
                    # not submit a compensating order after the opening gate
                    # has closed, and do not publish an unowned OPEN row.
                    pos.status = "SPOT_SOLD"
                    pos.error_message = (
                        "Opening admission closed after a partial hedge; "
                        "new batches stopped and reconciliation is required"
                    )
                    db.commit()
                    _publish_position_update(pos, effective_user_id, account_note)
                else:
                    _restore_borrowed_idle()
                return False
            t0 = time.monotonic()
            # 现货腿 maker 化:spot_order_mode=maker 时挂 post-only 省手续费(超时撤单+市价兜底)
            _spot_mode = getattr(rules, "spot_order_mode", "market") or "market"
            if _spot_mode == "maker":
                sell_result = await _spot_maker_fill(
                    client,
                    symbol,
                    "SELL",
                    b,
                    spread,
                    spot_lot,
                    pre_submit_guard=spot_guard,
                )
                fqty = Decimal(str(sell_result["executedQty"]))
                fprice = sell_result["_avg"]
            else:
                sell_result = await client.spot_market_sell(
                    symbol,
                    b,
                    **_pre_submit_kwargs(spot_guard),
                )
                # A successful HTTP response is not enough: the futures leg
                # must not be submitted until the margin sell is exchange-
                # confirmed.  RESULT responses normally contain FILLED and
                # executedQty; an ACK/ambiguous response is queried by order
                # id and otherwise fails closed, leaving the row recoverable.
                sell_result = await _confirm_spot_result(client, symbol, sell_result)
                sell_status = str((sell_result or {}).get("status") or "").upper()
                if sell_status not in {"FILLED", "PARTIALLY_FILLED"}:
                    error = BinanceAPIError(
                        0,
                        0,
                        f"spot sell outcome not confirmed: status={sell_status or 'UNKNOWN'}",
                    )
                    # An ACK/NEW/unknown response may have reached Binance
                    # even when no fill is visible locally. Never repay the
                    # borrow as if the request definitely failed: that could
                    # leave a naked spot short. Preserve the order evidence
                    # and let reconciliation decide after an exchange read.
                    if sell_status not in {"CANCELED", "EXPIRED", "REJECTED"}:
                        error.spot_outcome_unknown = True
                        error.spot_order_id = (
                            str((sell_result or {}).get("orderId") or "") or None
                        )
                        error.spot_executed_qty = str(
                            (sell_result or {}).get("executedQty", "0") or "0"
                        )
                    raise error
                fqty = Decimal(str(sell_result["executedQty"]))
                fprice = _avg_fill_price(sell_result)
            if fqty > RECOVERY_EPSILON and fprice <= RECOVERY_EPSILON:
                # Keep pairing the already-confirmed quantity to avoid a naked
                # short, but prohibit the final OPEN transition until recovery
                # can verify the order's quote total/average price.
                spot_price_unresolved = True
                logger.error(
                    "Hedge %s: spot sell filled without a verifiable price; "
                    "OPEN transition will remain in SPOT_SOLD",
                    symbol,
                )
            opening_spot_filled = total_sold + fqty
            latency = int((time.monotonic() - t0) * 1000)
            total_sold += fqty
            total_spot_value += fqty * fprice
            last_spot_oid = str(sell_result["orderId"])
            if first:
                pos.status = "SPOT_SOLD"; first = False
            pos.spot_sell_qty = total_sold
            pos.spot_sell_price = (
                total_spot_value / total_sold if total_sold > 0 else fprice
            )
            pos.spot_sell_order_id = last_spot_oid
            db.commit()
            _log_trade(db, pos_id, sub_account_id, "SPOT_SELL", symbol, "SELL",
                        fqty, fprice, last_spot_oid, "SUCCESS", latency=latency)

            # Derive this order from the cumulative hedge target, not by
            # rounding each isolated spot fill. Otherwise four sub-step
            # remainders can accumulate into a material naked quantity.
            futures_qty = _cumulative_hedge_order_qty(
                total_sold,
                total_hedged,
                futures_lot["stepSize"],
            )
            if futures_qty <= 0:
                raise BinanceAPIError(0, 0, "futures hedge batch rounded to zero")
            batch_fut_filled = {"qty": Decimal("0")}
            t0 = time.monotonic()
            try:
                async with _fc_symbol_lock(fc, symbol):
                    if master_mode:
                        # A shared one-way master position has no exchange-side
                        # sub-account attribution.  Before each independent
                        # command, prove that the live net position equals the
                        # durable aggregate of all sibling rows plus this row's
                        # already-hedged batches.  Unknown/mismatched state is
                        # held for reconciliation instead of oversizing.
                        recorded_other = _master_recorded_futures_qty(
                            db,
                            user_id=effective_user_id,
                            symbol=symbol,
                            exclude_position_id=pos.id,
                        )
                        if recorded_other is None:
                            raise BinanceAPIError(0, 0, "master hedge aggregate unavailable")
                        reader = getattr(fc, "get_futures_position", None)
                        if callable(reader):
                            live = await reader(symbol)
                            if isinstance(live, list):
                                live = live[0] if live else {}
                            live_qty = Decimal(str((live or {}).get("positionAmt", "0") or "0"))
                            expected_live = recorded_other + total_hedged
                            if live_qty < 0 or abs(live_qty - expected_live) > RECOVERY_EPSILON:
                                raise BinanceAPIError(
                                    0,
                                    0,
                                    f"master hedge aggregate mismatch: live={live_qty} expected={expected_live}",
                                )
                    if (getattr(rules, "follow_type", "market") or "market") == "limit":
                        long_result = await _futures_entry_limit(
                            fc,
                            symbol,
                            futures_qty,
                            rules,
                            futures_lot,
                            db,
                            pos,
                            sub_account_id,
                            fill_tracker=batch_fut_filled,
                            pre_submit_guard=batch_guard,
                        )
                    else:
                        # A stable client id lets an ambiguous response recover
                        # the current batch's actual fill for cumulative rollback.
                        coid = f"hx{pos_id}t{int(time.time() * 1000) % 10**10}"
                        try:
                            long_result = await fc.futures_market_long(
                                symbol,
                                futures_qty,
                                new_client_order_id=coid,
                                **_pre_submit_kwargs(batch_guard),
                            )
                            long_result = await _confirm_futures_result(
                                fc, symbol, long_result
                            )
                            batch_fut_filled["qty"] = Decimal(
                                str(long_result.get("executedQty", "0"))
                            )
                        except BinanceAPIError as fe:
                            if fe.api_code == -1007 or fe.http_code >= 500:
                                batch_fut_filled["qty"] = (
                                    await _query_filled_by_client_id(fc, symbol, coid)
                                )
                            raise
            except Exception:
                fut_filled["qty"] = total_hedged + batch_fut_filled["qty"]
                raise

            latency = int((time.monotonic() - t0) * 1000)
            long_result, hedge_status, hedged_qty, hedged_price = _futures_fill_metrics(
                long_result
            )
            if (
                hedge_status != "FILLED"
                or hedged_qty + RECOVERY_EPSILON < futures_qty
                or hedged_price <= RECOVERY_EPSILON
            ):
                # A quantity by itself is not an accounting-quality futures
                # fill.  Keep the paired spot sale recoverable and route any
                # confirmed quantity through the existing compensation path;
                # never promote the row to OPEN with a zero/ambiguous price.
                confirmed_qty = max(Decimal("0"), hedged_qty)
                fut_filled["qty"] = total_hedged + max(
                    confirmed_qty, batch_fut_filled["qty"]
                )
                reason = (
                    f"futures hedge batch not fully confirmed: status={hedge_status or 'UNKNOWN'}, "
                    f"qty={hedged_qty}/{futures_qty}, avgPrice={hedged_price}"
                )
                raise BinanceAPIError(0, 0, reason)
            total_hedged += hedged_qty
            total_futures_value += hedged_qty * hedged_price
            fut_filled["qty"] = total_hedged
            last_futures_oid = str(long_result["orderId"])
            pos.hedge_account = "master" if futures_client is not None else "sub"
            pos.futures_long_qty = total_hedged
            pos.futures_long_price = (
                total_futures_value / total_hedged
                if total_hedged > 0
                else hedged_price
            )
            pos.futures_long_order_id = last_futures_oid
            db.commit()
            _log_trade(
                db,
                pos_id,
                sub_account_id,
                "FUTURES_LONG",
                symbol,
                "BUY",
                hedged_qty,
                hedged_price,
                last_futures_oid,
                "SUCCESS",
                latency=latency,
            )
            remaining = round_to_step(qty - total_sold, spot_lot["stepSize"])

        if total_sold <= 0:
            raise BinanceAPIError(0, 0, "spot sell filled 0")
        qty = total_sold
        # The opening POSTs are fenced individually, but the lease can still
        # be replaced in the narrow window after the final futures fill and
        # before the lifecycle row is committed as OPEN.  The final transition
        # therefore has two independent fences:
        #
        # 1. atomically compare-and-renew the Redis lease; and
        # 2. conditionally update the *fresh* database row only when its id,
        #    account, tenant, canonical symbol, route, and SPOT_SOLD state all
        #    still match this invocation.
        #
        # If the lease or identity fence fails before the CAS, preserve
        # SPOT_SOLD for exchange reconciliation instead of publishing an
        # unowned OPEN row.  After the CAS succeeds, OPEN is durable and a
        # stale caller is forbidden from downgrading or otherwise overwriting
        # it; the committed exchange-backed row is reconciled in place.
        expected_hedge_account = "master" if futures_client is not None else "sub"
        lock_lost_message = (
            "Hedge fills confirmed but account operation lock ownership "
            "was lost before OPEN commit; reconciliation required"
        )
        if (
            operation_lock_guard is not None
            and not await operation_lock_guard.async_check()
        ):
            preserved = _cas_hedge_spot_sold(
                db,
                pos,
                sub_account_id=sub_account_id,
                symbol=symbol,
                user_id=effective_user_id,
                hedge_account=expected_hedge_account,
                error_message=lock_lost_message,
            )
            if preserved:
                _publish_position_update(pos, effective_user_id, account_note)
            logger.error(
                "Hedge %s left SPOT_SOLD: operation lock lost before OPEN commit",
                symbol,
            )
            return False

        if not _fresh_hedge_position_allows_open(
            db,
            pos_id,
            sub_account_id,
            symbol,
            user_id=effective_user_id,
            hedge_account=expected_hedge_account,
        ):
            identity_message = (
                "Hedge fills confirmed but Position identity/status changed "
                "before OPEN commit; reconciliation required"
            )
            preserved = _cas_hedge_spot_sold(
                db,
                pos,
                sub_account_id=sub_account_id,
                symbol=symbol,
                user_id=effective_user_id,
                hedge_account=expected_hedge_account,
                error_message=identity_message,
            )
            if preserved:
                _publish_position_update(pos, effective_user_id, account_note)
            logger.error("Hedge %s left SPOT_SOLD: final Position identity check failed", symbol)
            return False

        # The identity check above deliberately uses a separate fresh
        # session.  Refresh the executor's ORM instance before deriving the
        # final accounting values; otherwise a concurrent fill/recovery write
        # could leave this session holding an older quantity or price and the
        # OPEN CAS would publish stale exposure numbers.
        try:
            db.refresh(pos)
        except Exception:
            identity_message = (
                "Hedge fills confirmed but Position refresh failed before "
                "OPEN commit; reconciliation required"
            )
            preserved = _cas_hedge_spot_sold(
                db,
                pos,
                sub_account_id=sub_account_id,
                symbol=symbol,
                user_id=effective_user_id,
                hedge_account=expected_hedge_account,
                error_message=identity_message,
            )
            if preserved:
                _publish_position_update(pos, effective_user_id, account_note)
            logger.error("Hedge %s left SPOT_SOLD: final Position refresh failed", symbol)
            return False

        try:
            refreshed_account_matches = (
                int(getattr(pos, "sub_account_id", -1)) == int(sub_account_id)
            )
        except (TypeError, ValueError, ArithmeticError):
            refreshed_account_matches = False
        if (
            str(getattr(pos, "status", "") or "").strip().upper() != "SPOT_SOLD"
            or not refreshed_account_matches
            or canonical_position_symbol(getattr(pos, "symbol", "")) != symbol
            or getattr(pos, "hedge_account", None) != expected_hedge_account
        ):
            identity_message = (
                "Hedge fills confirmed but refreshed Position identity/status "
                "changed before OPEN commit; reconciliation required"
            )
            preserved = _cas_hedge_spot_sold(
                db,
                pos,
                sub_account_id=sub_account_id,
                symbol=symbol,
                user_id=effective_user_id,
                hedge_account=expected_hedge_account,
                error_message=identity_message,
            )
            if preserved:
                _publish_position_update(pos, effective_user_id, account_note)
            logger.error("Hedge %s left SPOT_SOLD: refreshed Position identity changed", symbol)
            return False

        try:
            refreshed_spot_qty = Decimal(str(getattr(pos, "spot_sell_qty", "0") or "0"))
            refreshed_spot_price = Decimal(str(getattr(pos, "spot_sell_price", "0") or "0"))
        except (TypeError, ValueError, ArithmeticError):
            refreshed_spot_qty = Decimal("NaN")
            refreshed_spot_price = Decimal("NaN")
        spot_price_invalid = (
            not refreshed_spot_price.is_finite() or refreshed_spot_price <= 0
        )
        if (
            not refreshed_spot_qty.is_finite()
            or spot_price_invalid
            or refreshed_spot_qty <= 0
            or spot_price_unresolved
        ):
            if spot_price_unresolved or spot_price_invalid:
                identity_message = (
                    "Hedge fills confirmed but refreshed spot sell price is "
                    "unavailable before OPEN commit; reconciliation required"
                )
            else:
                identity_message = (
                    "Hedge fills confirmed but refreshed Position quantities are "
                    "invalid before OPEN commit; reconciliation required"
                )
            preserved = _cas_hedge_spot_sold(
                db,
                pos,
                sub_account_id=sub_account_id,
                symbol=symbol,
                user_id=effective_user_id,
                hedge_account=expected_hedge_account,
                error_message=identity_message,
            )
            if preserved:
                _publish_position_update(pos, effective_user_id, account_note)
            logger.error("Hedge %s left SPOT_SOLD: refreshed Position quantities invalid", symbol)
            return False

        opened_values = {
            Position.status: "OPEN",
            Position.open_spread: spread.spread_short,
            Position.open_usdt_amount: refreshed_spot_qty * refreshed_spot_price,
            Position.opened_at: datetime.now(timezone.utc),
            Position.error_message: None,
            Position.updated_at: datetime.now(timezone.utc),
        }
        if not _cas_hedge_open(
            db,
            pos,
            sub_account_id=sub_account_id,
            symbol=symbol,
            user_id=effective_user_id,
            hedge_account=expected_hedge_account,
            values=opened_values,
        ):
            identity_message = (
                "Hedge fills confirmed but final Position CAS lost a concurrent "
                "state/identity update; reconciliation required"
            )
            preserved = _cas_hedge_spot_sold(
                db,
                pos,
                sub_account_id=sub_account_id,
                symbol=symbol,
                user_id=effective_user_id,
                hedge_account=expected_hedge_account,
                error_message=identity_message,
            )
            if preserved:
                _publish_position_update(pos, effective_user_id, account_note)
            logger.error("Hedge %s left SPOT_SOLD: final Position CAS failed", symbol)
            return False

        # The CAS above is the durable source of truth for the already-filled
        # exchange legs.  Do not perform a second lock check that could revert
        # this OPEN row after a replacement Worker has legitimately acquired
        # the lease and started managing it.  A lease loss after commit is
        # observable through the normal reconciliation/heartbeat path; the
        # stale caller must not write a newer owner's state.
        if operation_lock_guard is not None:
            if not await operation_lock_guard.async_check():
                logger.error(
                    "Hedge %s OPEN committed after lease became invalid; leaving row for reconciliation",
                    symbol,
                )
                # The exchange legs and the durable lifecycle transition are
                # already committed.  Stop this stale caller here: it must
                # not publish a success notification or continue with any
                # owner-only bookkeeping after a replacement acquired the
                # lease.  Reconciliation will observe the OPEN row.
                _publish_position_update(pos, effective_user_id, account_note)
                return False
        # 状态即推 + 余额即刷:对冲腿成交 = 用户「第一时间确认对冲成功」的时刻,
        # OPEN 行秒级出现(含合约量/价),主账户合约列由 balance:refresh 即时重推
        _publish_position_update(pos, user_id, account_note)
        _publish_balance_refresh(user_id if user_id is not None else _resolve_user_id(db, sub_account_id))

        logger.info(f"Position opened: {symbol} qty={qty} spread={spread.spread_short}%")
        await notifier.notify_position_opened(
            account_note, symbol, spread.spread_short, qty, pos.open_usdt_amount,
        )

    except BinancePreSubmitRejected as e:
        # A rejection before any spot fill is safe to restore as idle.  Once
        # spot has filled (or a prior batch is durable SPOT_SOLD), route the
        # failure through the same tranche-scoped compensation used for API
        # errors: buy back only this Position's sale and repay only its debt.
        try:
            partial_qty = Decimal(str(getattr(e, "partial_spot_qty", "0") or "0"))
            partial_value = Decimal(str(getattr(e, "partial_spot_value", "0") or "0"))
        except (TypeError, ValueError, ArithmeticError):
            partial_qty = Decimal("0")
            partial_value = Decimal("0")
        if partial_qty.is_finite() and partial_qty > 0:
            # The maker helper can reject before returning its result, so the
            # normal SPOT_SOLD persistence block has not run yet.
            # ``partial_spot_qty`` is this batch's fill; include any earlier
            # paired batches that were already persisted in ``total_sold``.
            try:
                prior_total = Decimal(str(total_sold))
            except (NameError, TypeError, ValueError, ArithmeticError):
                prior_total = Decimal("0")
            cumulative_partial = prior_total + partial_qty
            opening_spot_filled = max(opening_spot_filled, cumulative_partial)
            try:
                recorded = Decimal(str(getattr(pos, "spot_sell_qty", "0") or "0"))
            except (TypeError, ValueError, ArithmeticError):
                recorded = Decimal("0")
            if cumulative_partial > recorded:
                pos.spot_sell_qty = cumulative_partial
                try:
                    prior_price = Decimal(
                        str(getattr(pos, "spot_sell_price", "0") or "0")
                    )
                except (TypeError, ValueError, ArithmeticError):
                    prior_price = Decimal("0")
                prior_value = recorded * prior_price
                if partial_value.is_finite() and partial_value > 0:
                    pos.spot_sell_price = (
                        prior_value + partial_value
                    ) / cumulative_partial
                partial_order_id = getattr(e, "partial_spot_order_id", None)
                if partial_order_id:
                    pos.spot_sell_order_id = str(partial_order_id)
        if (
            opening_spot_filled > 0
            or fut_filled["qty"] > 0
            or getattr(pos, "status", None) == "SPOT_SOLD"
        ):
            if getattr(pos, "status", None) not in ("SPOT_SOLD", "OPEN"):
                pos.status = "SPOT_SOLD"
                db.commit()
            await _handle_hedge_failure(
                db,
                pos,
                client,
                e,
                sub_account_id,
                symbol,
                notifier,
                account_note,
                futures_client=futures_client,
                futures_filled=fut_filled["qty"],
            )
        else:
            _restore_borrowed_idle()
        return False
    except BinanceAPIError as e:
        logger.error(f"Hedge failed at {pos.status}: {e}")
        if getattr(e, "spot_outcome_unknown", False):
            # Keep an ambiguous spot submission in a non-terminal recovery
            # state. A transport-level unknown is not proof that the borrow
            # can be repaid; no compensating order is sent from this handler.
            try:
                ambiguous_qty = Decimal(str(getattr(e, "spot_executed_qty", "0") or "0"))
            except (TypeError, ValueError, ArithmeticError):
                ambiguous_qty = Decimal("0")
            if ambiguous_qty.is_finite() and ambiguous_qty > 0:
                pos.status = "SPOT_SOLD"
                pos.spot_sell_qty = ambiguous_qty
                pos.spot_sell_order_id = getattr(e, "spot_order_id", None)
            pos.error_message = (
                f"Spot sell outcome is ambiguous; exchange reconciliation required: {e}"
            )
            db.commit()
            _publish_position_update(pos, effective_user_id, account_note)
            try:
                await notifier.notify_error(
                    account_note, f"hedge {symbol}", pos.error_message
                )
            except Exception:
                pass
            return False
        await _handle_hedge_failure(db, pos, client, e, sub_account_id, symbol, notifier, account_note,
                                    futures_client=futures_client, futures_filled=fut_filled["qty"])
        if futures_client is not None and getattr(e, "api_code", None) == -4061:
            await _invalidate_master("Binance -4061 position-side mismatch")
        return False
    except Exception as e:
        # 非 API 异常同样走回滚(可能已卖出现货/已部分成交合约,只置 FAILED 会裸留敞口)
        logger.error(f"Hedge failed unexpectedly: {e}", exc_info=True)
        await _handle_hedge_failure(db, pos, client, e, sub_account_id, symbol, notifier, account_note,
                                    futures_client=futures_client, futures_filled=fut_filled["qty"])
        return False
    finally:
        _release_margin_reserve(futures_client, reserved)
        db.close()


async def _handle_hedge_failure(db, pos, client, error, sub_account_id, symbol, notifier, account_note,
                                futures_client=None, futures_filled: Decimal = Decimal("0")):
    current = pos.status
    if current in ("BORROWED_IDLE", "HEDGING"):
        # spot sell failed — repay borrow
        try:
            await client.margin_repay(pos.base_asset, pos.borrow_qty)
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol,
                        quantity=pos.borrow_qty, status="SUCCESS")
        except Exception as re:
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol, status="FAILED", error=str(re))
        pos.status = "FAILED"
        pos.error_message = f"Spot sell failed: {error}. Borrow rolled back."
        db.commit()
        _publish_position_update(pos, account_note=account_note)
    elif current == "SPOT_SOLD":
        # futures long failed — close any partial futures fill first (master 残腿不平会污染共享净仓),
        # then buy back spot + repay
        if futures_filled and futures_filled > 0:
            fcr = futures_client if futures_client is not None else client
            try:
                async with _fc_symbol_lock(fcr, symbol):
                    await fcr.futures_market_close(symbol, futures_filled)
                _log_trade(db, pos.id, sub_account_id, "ROLLBACK_FUTURES_CLOSE", symbol, "SELL",
                            futures_filled, status="SUCCESS")
            except Exception as re:
                _log_trade(db, pos.id, sub_account_id, "ROLLBACK_FUTURES_CLOSE", symbol,
                            status="FAILED", error=str(re))
        # A margin account's debt is asset-level and may include older OPEN
        # tranches for the same symbol.  This rollback owns only this Position:
        # buy back no more than its recorded spot sale and repay no more than
        # its confirmed borrow.  Using the account's total debt here would let
        # a failed incremental tranche consume an older hedge's spot leg.
        try:
            position_borrow_qty = Decimal(str(pos.borrow_qty or "0"))
            position_sold_qty = Decimal(str(pos.spot_sell_qty or "0"))
        except (TypeError, ValueError, ArithmeticError):
            position_borrow_qty = Decimal("0")
            position_sold_qty = Decimal("0")
        if not position_borrow_qty.is_finite() or position_borrow_qty < 0:
            position_borrow_qty = Decimal("0")
        if not position_sold_qty.is_finite() or position_sold_qty < 0:
            position_sold_qty = Decimal("0")
        rollback_qty = min(position_borrow_qty, position_sold_qty)
        try:
            if rollback_qty > 0:
                await client.spot_market_buy_qty(symbol, rollback_qty)
                _log_trade(db, pos.id, sub_account_id, "ROLLBACK_SPOT_BUY", symbol, "BUY", rollback_qty, status="SUCCESS")
        except Exception as re:
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_SPOT_BUY", symbol, status="FAILED", error=str(re))
        debt_before = Decimal("0")
        repay_amount = Decimal("0")
        try:
            debt_before, _ = await _get_asset_debt(client, pos.base_asset)
            repay_amount = min(position_borrow_qty, max(Decimal("0"), debt_before))
            if repay_amount > 0:
                await client.margin_repay(pos.base_asset, repay_amount)
                _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol, quantity=repay_amount, status="SUCCESS")
        except Exception as re:
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol, status="FAILED", error=str(re))
        # Verify this tranche's debt reduction, not an impossible account-zero
        # target. Older OPEN tranches legitimately leave asset-level debt.
        pos.status = "FAILED"
        try:
            residual_debt, _ = await _get_asset_debt(client, pos.base_asset)
            expected_other_debt = max(Decimal("0"), debt_before - repay_amount)
            attributable_residual = min(
                position_borrow_qty,
                max(Decimal("0"), residual_debt - expected_other_debt),
            )
            if attributable_residual > position_borrow_qty * Decimal("0.02"):
                pos.error_message = (f"Futures long failed: {error}. 回滚未清账(残留债务 "
                                     f"{attributable_residual} {pos.base_asset})— 裸空,guard 收口中")
                logger.error(f"NAKED SHORT after rollback {symbol}: attributable residual debt "
                             f"{attributable_residual} {pos.base_asset}")
                try:
                    await notifier.notify_naked_short(account_note, symbol, attributable_residual, Decimal("0"), futures_filled)
                except Exception:
                    pass
            else:
                pos.error_message = f"Futures long failed: {error}. Rolled back."
        except Exception as _ve:
            pos.error_message = f"Futures long failed: {error}. 回滚结果未核实({_ve}),guard 将复核"
        db.commit()
        _publish_position_update(pos, account_note=account_note)
    else:
        pos.status = "FAILED"
        pos.error_message = str(error)
        db.commit()
        _publish_position_update(pos, account_note=account_note)
    await notifier.notify_error(account_note, f"hedge {symbol} (rollback from {current})", str(error))


async def execute_open(
    sub_account_id: int,
    symbol: str,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    spread_feed: SpreadFeed = None,
    futures_client: BinanceTradingClient = None,
    user_id: int = None,
    new_action_guard=None,
    operation_lock_token: str | None = None,
    operation_lock_redis=None,
    operation_lock_ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
):
    """Atomic open (borrow + hedge in one shot) — used by manual-open and as a fallback."""
    if getattr(rules, "hedge_via_master", False) and futures_client is None:
        logger.error(
            "Open %s blocked: hedge_via_master is enabled but no master futures client was supplied",
            symbol,
        )
        return
    pos_id = await execute_borrow(
        sub_account_id, symbol, spread, rules, client, notifier, account_note,
        spread_feed=spread_feed, min_spread=rules.open_spread, user_id=user_id,
        new_action_guard=new_action_guard,
        operation_lock_token=operation_lock_token,
        operation_lock_redis=operation_lock_redis,
        operation_lock_ttl_sec=operation_lock_ttl_sec,
    )
    if pos_id is None:
        return
    db = SessionLocal()
    pos = db.query(Position).get(pos_id)
    db.close()
    if pos and pos.status == "BORROWED_IDLE":
        cur = spread_feed.get_symbol(symbol) if spread_feed else None
        await execute_hedge(pos, cur or spread, rules, client, notifier, account_note,
                            futures_client=futures_client, user_id=user_id,
                            operation_lock_token=operation_lock_token,
                            operation_lock_redis=operation_lock_redis,
                            operation_lock_ttl_sec=operation_lock_ttl_sec)


def _resolve_close_slice_amount(db, sub_account_id: int, symbol: str, user_id) -> Decimal:
    """Single buy-back slice in USDT: the same "single-order open amount"
    five-level resolution as the opening sell side (account-symbol ->
    user-symbol -> sub-account -> global open_order_amount -> legacy
    order_amount). Any failure falls back to 0 = no slicing (single order)."""
    try:
        from app.db.models import GlobalRules
        gr = None
        if user_id is not None:
            gr = db.query(GlobalRules).filter(GlobalRules.user_id == user_id).first()
        if gr is None:
            gr = db.query(GlobalRules).filter(GlobalRules.user_id.is_(None)).first()
        if gr is None:
            return Decimal("0")
        return _resolve_hedge_order_amount(db, sub_account_id, symbol, gr, user_id)
    except Exception:
        return Decimal("0")


async def execute_unhedge(
    position: Position,
    spread: SpreadSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    futures_client: BinanceTradingClient = None,
    user_id: int | None = None,
    spot_order_mode: str = "market",   # 现货买回腿:market/maker(post-only省手续费)
    allow_emergency_close: bool = False,
    emergency: bool | None = None,
    pre_submit_guard=None,
    operation_lock_token: str | None = None,
    operation_lock_redis=None,
    operation_lock_ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
):
    """Close one hedge: buy back spot first, then close the futures leg.
    in the margin account awaiting repay. OPEN → PENDING_REPAY (net-flat, no exposure).
    合约腿按开仓归属(pos.hedge_account)选 client —— master 开的仓必须用 master 平,
    与全局开关当前值无关;master client 缺失时不动仓位,留 OPEN 等重试。"""
    # ``emergency`` alias keeps direct engine callers compatible with the
    # worker-level naming while the public API uses ``allow_emergency_close``.
    if emergency is not None:
        allow_emergency_close = bool(emergency)
    operation_lock_guard = None
    if operation_lock_token is not None or operation_lock_redis is not None:
        operation_lock_guard = _OperationLockGuard(
            operation_lock_redis,
            getattr(position, "sub_account_id", 0),
            canonical_position_symbol(getattr(position, "symbol", "")),
            operation_lock_token or "",
            ttl_sec=operation_lock_ttl_sec,
        )
        if not await operation_lock_guard.async_check():
            logger.info(
                "Unhedge %s blocked: account operation lock is not owned by caller",
                getattr(position, "symbol", "?"),
            )
            return False
    close_guard = _borrow_submit_guard(
        pre_submit_guard,
        None,
        Decimal("0"),
        operation_lock_guard=operation_lock_guard,
    )
    if not _pre_submit_guard_allows(close_guard):
        return False
    # A stop-loss/manual market close is risk reducing and does not use the
    # spread for pricing.  Permit it to proceed through a stale snapshot, but
    # keep maker exits freshness-gated because they do use the quote price.
    if not _close_snapshot_ok(
        spread,
        spot_order_mode=spot_order_mode,
        allow_emergency_close=allow_emergency_close,
        max_age_ms=BORROW_FRESH_MS,
    ):
        # Close uses the spread trigger and may use it for maker buy-back
        # pricing.  Keep OPEN until both local WS legs are fresh.
        logger.warning("Unhedge %s deferred: spread snapshot is stale or legacy", getattr(position, "symbol", "?"))
        return False
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    _msg0 = str(getattr(pos, "error_message", "") or "") if pos is not None else ""
    _cap_resume = bool(
        pos is not None
        and pos.status == "CLOSING_SPOT"
        and "抵押额度受限" in _msg0
    )
    if _cap_resume and "重试中 @" in _msg0:
        # another process claimed this resume less than 180s ago; do not race it
        try:
            _t0r = int(_msg0.rsplit("@", 1)[1].strip())
        except (TypeError, ValueError):
            _t0r = 0
        if time.time() - _t0r < 180:
            _cap_resume = False
    if not pos or (pos.status != "OPEN" and not _cap_resume):
        db.close()
        return False
    on_master = getattr(pos, "hedge_account", None) == "master"
    if on_master and futures_client is None:
        logger.warning(f"Unhedge {pos.symbol}: hedged on master but master client unavailable; retry later")
        db.close()
        return False
    fc = futures_client if on_master else client

    if not _pre_submit_guard_allows(close_guard):
        db.close()
        return False

    # 跨进程互斥(API 手动平仓 vs 引擎自动): DB 级 CAS 认领 —— master 共享净仓下
    # 双平会误吃其他子账户的对冲腿,留下账面无感知的裸现货空头
    if _cap_resume:
        # single-flight claim (worker periodic resume vs manual click): an
        # optimistic CAS on the exact error text; the loser bounces. A crash
        # leaves "重试中 @epoch" which expires after 180s at the entry gate.
        _resume_claim = db.query(Position).filter(
            Position.id == pos.id, Position.status == "CLOSING_SPOT",
            Position.error_message == pos.error_message,
        ).update(
            {"error_message": "交易所抵押额度受限重试中 @%d" % int(time.time())},
            synchronize_session=False,
        )
        db.commit()
        if not _resume_claim:
            db.close()
            return False
        db.refresh(pos)
    else:
        claimed = db.query(Position).filter(
            Position.id == pos.id, Position.status == "OPEN",
        ).update({"status": "CLOSING_SPOT"}, synchronize_session=False)
        db.commit()
        if not claimed:
            db.close()
            return False
        db.refresh(pos)
    _publish_position_update(pos, account_note=account_note)

    def _restore_open() -> None:
        pos.status = "OPEN"
        db.commit()
        _publish_position_update(pos, account_note=account_note)

    def _preserve_spot_buy_evidence(exc) -> bool:
        """Persist maker acceptance evidence carried by an exception."""
        try:
            partial_qty = Decimal(str(getattr(exc, "partial_spot_qty", "0") or "0"))
            partial_value = Decimal(str(getattr(exc, "partial_spot_value", "0") or "0"))
        except (TypeError, ValueError, ArithmeticError):
            partial_qty = Decimal("0")
            partial_value = Decimal("0")
        partial_order_id = str(getattr(exc, "partial_spot_order_id", "") or "").strip()
        evidence = (
            bool(partial_order_id)
            or (partial_qty.is_finite() and partial_qty > RECOVERY_EPSILON)
            or (partial_value.is_finite() and partial_value > RECOVERY_EPSILON)
        )
        if not evidence or getattr(pos, "status", None) != "CLOSING_SPOT":
            return False
        if partial_order_id:
            pos.spot_buy_order_id = partial_order_id
        if partial_qty.is_finite() and partial_qty > RECOVERY_EPSILON:
            pos.spot_buy_qty = partial_qty
            if partial_value.is_finite() and partial_value > RECOVERY_EPSILON:
                pos.spot_buy_price = partial_value / partial_qty
        pos.error_message = (
            "spot maker buy-back was accepted but final submission was rejected; "
            "exchange order reconciliation required"
        )
        db.commit()
        _publish_position_update(pos, account_note=account_note)
        return True

    if not _pre_submit_guard_allows(close_guard):
        _restore_open()
        db.close()
        return False

    try:
        # New close contract: buy back the spot leg first, confirm its actual
        # fill, then submit this Position's reduce-only futures close.  The
        # previous futures-first implementation remains below as dead source
        # during this rolling edit and is removed after the focused tests pass.
        if not _pre_submit_guard_allows(close_guard):
            _restore_open()
            return False
        # C3 rework (function independence): a close NEVER touches debt or
        # the account's un-deployed borrowed inventory -- that coin is user
        # stock managed only by the borrow/repay features (incl. their own
        # rules such as manual-push repay bans). The close buys back this
        # position's FULL borrow (fee-buffered), slicing orders by the same
        # configured single-order open amount as the opening sell side. When
        # the exchange pledge cap (-3087) rejects a slice, confirmed progress
        # is already persisted on the row and the close waits in CLOSING_SPOT
        # for the worker's periodic resume (or a manual click); every retry
        # buys only the recorded remainder, so no path can over-buy or touch
        # the stock.
        target = pos.borrow_qty * FEE_BUFFER
        spot_lot = await client.get_lot_size(pos.symbol, "spot")
        _step_d = Decimal(str(spot_lot["stepSize"]))
        _bought_qty = Decimal("0")
        _bought_quote = Decimal("0")
        _last_slice_oid = None
        if _cap_resume:
            _bought_qty = _recovery_decimal(
                getattr(pos, "spot_buy_qty", None), allow_negative=False
            ) or Decimal("0")
            _prior_px = _recovery_decimal(
                getattr(pos, "spot_buy_price", None), allow_negative=False
            ) or Decimal("0")
            _bought_quote = _bought_qty * _prior_px
            _last_slice_oid = str(getattr(pos, "spot_buy_order_id", "") or "") or None
        _slice_amount = _resolve_close_slice_amount(
            db,
            pos.sub_account_id,
            pos.symbol,
            user_id if user_id is not None else getattr(pos, "user_id", None),
        )
        _price_ref = Decimal("0")
        try:
            if spread is not None and getattr(spread, "spot_ask", None):
                _price_ref = Decimal(str(spread.spot_ask))
        except (TypeError, ValueError, ArithmeticError):
            _price_ref = Decimal("0")
        _per_slice = _hedge_batch_size(
            target,
            _price_ref,
            _slice_amount,
            spot_lot["stepSize"],
            getattr(pos, "borrow_usdt_amount", None),
        )
        _sliced = not (
            _bought_qty <= RECOVERY_EPSILON
            and (
                _per_slice <= 0
                or _per_slice + _step_d + RECOVERY_EPSILON >= target
            )
        )
        if _sliced:
            while True:
                _remaining = target - _bought_qty
                if _remaining <= RECOVERY_EPSILON:
                    break
                if _bought_qty + RECOVERY_EPSILON >= pos.borrow_qty:
                    # debt covered; the leftover fee-buffer tail may be
                    # unbuyable (below one lot step / min notional) -- treat
                    # the buy-back as complete instead of spamming -1013.
                    if _remaining <= _step_d:
                        break
                    try:
                        _ref_px = Decimal(str(pos.spot_buy_price or 0))
                    except (TypeError, ValueError, ArithmeticError):
                        _ref_px = Decimal("0")
                    if _ref_px > 0 and _remaining * _ref_px < Decimal("6"):
                        break
                if not _pre_submit_guard_allows(close_guard):
                    if _bought_qty <= RECOVERY_EPSILON and not _cap_resume:
                        _restore_open()
                        return False
                    pos.error_message = (
                        f"交易所抵押额度受限,已买回 {_bought_qty}/{target},等待自动重试"
                    )
                    db.commit()
                    _publish_position_update(pos, account_note=account_note)
                    return False
                _slice = _per_slice if _per_slice > 0 else _remaining
                if _slice > _remaining:
                    _slice = _remaining
                _slice_q = round_to_step(_slice, spot_lot["stepSize"])
                if _slice_q < _slice:
                    _slice_q += _step_d
                _t_s = time.monotonic()
                try:
                    _s_res = await client.spot_market_buy_qty(
                        pos.symbol, _slice_q, **_pre_submit_kwargs(close_guard),
                    )
                except BinanceAPIError as _cap_exc:
                    if getattr(_cap_exc, "api_code", None) != -3087:
                        raise
                    _emsg = str(_cap_exc)
                    _room = "?"
                    _key = "max transfer in quantity is "
                    _ki = _emsg.find(_key)
                    if _ki >= 0:
                        _num = ""
                        for _ch in _emsg[_ki + len(_key):]:
                            if _ch.isdigit() or _ch == ".":
                                _num += _ch
                            else:
                                break
                        _room = _num or "?"
                    pos.error_message = (
                        f"交易所抵押额度受限(实时余量 {_room}),"
                        f"已买回 {_bought_qty}/{target},等待自动重试"
                    )
                    pos.retry_count = (pos.retry_count or 0) + 1
                    db.commit()
                    _publish_position_update(pos, account_note=account_note)
                    return False
                _s_res = await _confirm_spot_result(client, pos.symbol, _s_res)
                _s_qty = _recovery_decimal(
                    (_s_res or {}).get("executedQty"), allow_negative=False
                ) or Decimal("0")
                _s_px = _avg_fill_price(_s_res or {})
                _s_oid = str((_s_res or {}).get("orderId") or "") or None
                if _s_qty <= RECOVERY_EPSILON or _s_px <= RECOVERY_EPSILON:
                    pos.error_message = (
                        f"交易所抵押额度受限?切片无确认成交,"
                        f"已买回 {_bought_qty}/{target},等待自动重试"
                    )
                    pos.retry_count = (pos.retry_count or 0) + 1
                    db.commit()
                    _publish_position_update(pos, account_note=account_note)
                    return False
                _bought_qty += _s_qty
                _bought_quote += _s_qty * _s_px
                _last_slice_oid = _s_oid
                pos.spot_buy_qty = _bought_qty
                pos.spot_buy_price = _bought_quote / _bought_qty
                pos.spot_buy_order_id = _s_oid
                pos.error_message = None
                db.commit()
                _log_trade(
                    db, pos.id, pos.sub_account_id, "SPOT_BUY", pos.symbol,
                    "BUY", _s_qty, _s_px, _s_oid, "SUCCESS",
                    latency=int((time.monotonic() - _t_s) * 1000),
                )
        spot_lot = await client.get_lot_size(pos.symbol, "spot")
        buy_qty = round_to_step(target, spot_lot["stepSize"])
        if buy_qty < target:
            buy_qty += Decimal(str(spot_lot["stepSize"]))
        if not _pre_submit_guard_allows(close_guard):
            _restore_open()
            return False
        t0 = time.monotonic()
        if _sliced:
            # slices already bought and persisted the full target; hand the
            # cumulative evidence to the unchanged validation path below.
            bought_qty = _bought_qty
            buy_price = (
                _bought_quote / _bought_qty if _bought_qty > 0 else Decimal("0")
            )
            buy_order_id = _last_slice_oid
            buy_result = None
            buy_latency = int((time.monotonic() - t0) * 1000)
        else:
            if (spot_order_mode or "market") == "maker":
                buy_result = await _spot_maker_fill(
                    client, pos.symbol, "BUY", buy_qty, spread, spot_lot,
                    pre_submit_guard=close_guard,
                )
            else:
                buy_result = await client.spot_market_buy_qty(
                    pos.symbol, buy_qty, **_pre_submit_kwargs(close_guard),
                )
            buy_result = await _confirm_spot_result(client, pos.symbol, buy_result)
            bought_qty = _recovery_decimal(
                (buy_result or {}).get("executedQty"), allow_negative=False
            ) or Decimal("0")
            buy_price = _avg_fill_price(buy_result or {})
            buy_order_id = str((buy_result or {}).get("orderId") or "") or None
            buy_latency = int((time.monotonic() - t0) * 1000)
        pos.spot_buy_qty = bought_qty
        pos.spot_buy_price = buy_price
        pos.spot_buy_order_id = buy_order_id
        if bought_qty > RECOVERY_EPSILON and buy_price <= RECOVERY_EPSILON:
            # The buy quantity is exchange-confirmed, but its quote value is
            # not.  Keep CLOSING_SPOT with the order id for reconciliation;
            # advancing would persist a zero buy price and corrupt close PnL.
            pos.error_message = (
                "spot buy-back fill price unavailable; "
                "exchange order reconciliation required before futures close"
            )
            db.commit()
            _publish_position_update(pos, account_note=account_note)
            _log_trade(
                db, pos.id, pos.sub_account_id, "SPOT_BUY", pos.symbol, "BUY",
                bought_qty, buy_price, buy_order_id, "UNKNOWN", latency=buy_latency,
            )
            return False
        # Keep this state if the response is partial or ambiguous.  Recovery
        # can query the exact order and must never issue an unkeyed duplicate.
        if (
            bought_qty + RECOVERY_EPSILON < target
            and bought_qty + RECOVERY_EPSILON < pos.borrow_qty
        ):
            pos.error_message = (
                f"spot buy-back incomplete: {bought_qty}/{target}; "
                "futures close held until the margin leg is confirmed"
            )
            db.commit()
            _publish_position_update(pos, account_note=account_note)
            _log_trade(
                db, pos.id, pos.sub_account_id, "SPOT_BUY", pos.symbol, "BUY",
                bought_qty, buy_price, buy_order_id, "PARTIAL", latency=buy_latency,
            )
            return False
        pos.close_spread = (
            spread.spread_short
            if spread is not None and getattr(spread, "spread_short", None) is not None
            else (pos.close_spread or Decimal("0"))
        )
        pos.status = "SPOT_BOUGHT"
        db.commit()
        _publish_position_update(pos, account_note=account_note)
        _log_trade(
            db, pos.id, pos.sub_account_id, "SPOT_BUY", pos.symbol, "BUY",
            bought_qty, buy_price, buy_order_id, "SUCCESS", latency=buy_latency,
        )

        futures_qty = _recovery_decimal(pos.futures_long_qty, allow_negative=False) or Decimal("0")
        if futures_qty <= RECOVERY_EPSILON:
            pos.error_message = "spot buy-back confirmed but futures quantity is missing"
            db.commit()
            return False
        if not _pre_submit_guard_allows(close_guard):
            return False
        t0 = time.monotonic()
        async with _fc_symbol_lock(fc, pos.symbol):
            if not _pre_submit_guard_allows(close_guard):
                return False
            if on_master:
                recorded_other = _master_recorded_futures_qty(
                    db,
                    user_id=(user_id if user_id is not None else getattr(pos, "user_id", None)),
                    symbol=pos.symbol,
                    exclude_position_id=pos.id,
                )
                if recorded_other is None:
                    pos.error_message = "master hedge aggregate unavailable; close held"
                    db.commit()
                    return False
                reader = getattr(fc, "get_futures_position", None)
                if callable(reader):
                    live = await reader(pos.symbol)
                    if isinstance(live, list):
                        live = live[0] if live else {}
                    live_qty = Decimal(str((live or {}).get("positionAmt", "0") or "0"))
                    expected_live = recorded_other + futures_qty
                    if live_qty < 0 or abs(live_qty - expected_live) > RECOVERY_EPSILON:
                        pos.error_message = (
                            f"master hedge aggregate mismatch: live={live_qty} "
                            f"expected={expected_live}; close held"
                        )
                        db.commit()
                        return False
            close_result = await fc.futures_market_close(
                pos.symbol, futures_qty, **_pre_submit_kwargs(close_guard),
            )
            close_result = await _confirm_futures_result(fc, pos.symbol, close_result)
        close_result, close_status, close_qty, close_price = _futures_fill_metrics(
            close_result
        )
        close_order_id = str((close_result or {}).get("orderId") or "") or None
        close_latency = int((time.monotonic() - t0) * 1000)
        if (
            close_status != "FILLED"
            or close_qty + RECOVERY_EPSILON < futures_qty
            or close_price <= RECOVERY_EPSILON
        ):
            pos.futures_close_order_id = close_order_id
            pos.error_message = (
                f"futures close not fully confirmed: status={close_status or 'UNKNOWN'}, "
                f"qty={close_qty}/{futures_qty}, avgPrice={close_price}; "
                "spot buy-back is confirmed and reconciliation is required"
            )
            db.commit()
            _publish_position_update(pos, account_note=account_note)
            _log_trade(
                db, pos.id, pos.sub_account_id, "FUTURES_CLOSE", pos.symbol,
                "SELL", close_qty,
                close_price,
                close_order_id,
                "PARTIAL" if close_qty + RECOVERY_EPSILON < futures_qty else "UNKNOWN",
                latency=close_latency,
            )
            return False
        pos.futures_close_price = close_price
        pos.futures_close_order_id = close_order_id
        pos.status = "FUTURES_CLOSED"
        db.commit()
        _publish_position_update(pos, account_note=account_note)
        _publish_balance_refresh(
            getattr(pos, "user_id", None) or _resolve_user_id(db, pos.sub_account_id)
        )
        _log_trade(
            db, pos.id, pos.sub_account_id, "FUTURES_CLOSE", pos.symbol, "SELL",
            futures_qty, pos.futures_close_price, pos.futures_close_order_id,
            "SUCCESS", latency=close_latency,
        )
        pos.status = "PENDING_REPAY"
        db.commit()
        _publish_position_update(pos, account_note=account_note)
        logger.info("Unhedged (pending repay): %s", pos.symbol)
        return True

    except BinancePreSubmitRejected as exc:
        # A guard rejection before the spot request is safe to restore.  A
        # maker order may, however, have filled before its market fallback was
        # fenced.  Persist every piece of evidence carried by the helper so a
        # restart can query that exact order instead of buying the full amount
        # a second time.
        preserved = _preserve_spot_buy_evidence(exc)
        if not preserved and (
            getattr(pos, "status", None) == "CLOSING_SPOT"
            and not getattr(pos, "spot_buy_order_id", None)
        ):
            _restore_open()
        return False
    except BinanceAPIError as e:
        if _preserve_spot_buy_evidence(e):
            return False
        logger.error(f"Unhedge failed at {pos.status}: {e}")
        pos.error_message = str(e)
        pos.retry_count = (pos.retry_count or 0) + 1
        db.commit()
        _publish_position_update(pos, account_note=account_note)
        _log_trade(db, pos.id, pos.sub_account_id, "CLOSE_ERROR", pos.symbol, status="FAILED", error=str(e))
        await notifier.notify_error(account_note, f"unhedge {pos.symbol}", str(e))
        return False
    except Exception as e:
        if _preserve_spot_buy_evidence(e):
            return False
        logger.error(f"Unhedge failed unexpectedly: {e}", exc_info=True)
        pos.error_message = str(e)
        db.commit()
        _publish_position_update(pos, account_note=account_note)
        await notifier.notify_error(account_note, f"unhedge {pos.symbol}", str(e))
        return False
    finally:
        db.close()


async def sell_residual_spot(client: BinanceTradingClient, symbol: str, base_asset: str, qty) -> tuple[Decimal, str]:
    """把杠杆户 base_asset 现币残留市价卖回 USDT(NO_SIDE_EFFECT,不借币)。残留来源=平仓买回按
    FEE_BUFFER 超买/开仓尾批不足额,还清债务后无人消费。qty 向下对齐 stepSize;名义 < minNotional
    时币安不接单,如实返回原因。返回 (实际卖出数量, 说明)。
    ⚠调用方必须自行保证: 该账户该币债务已清 且 无其它非终态持仓 —— 否则会把别的仓等待还币的
    买回币卖掉,制造裸债。该函数只供用户显式「卖回」操作使用；自动还币不能证明现币归属，禁止调用。"""
    q = Decimal(str(qty))
    info = await client._request("GET", "https://api.binance.com/api/v3/exchangeInfo",
                                 {"symbol": symbol}, signed=False)
    sp = info.get("symbols", [{}])[0]
    flt = {f["filterType"]: f for f in sp.get("filters", [])}
    step = str(flt.get("LOT_SIZE", {}).get("stepSize", "0.01") or "0.01")
    # Binance has used both filter names over time. Prefer the first valid
    # positive value so a malformed/empty NOTIONAL entry cannot hide a valid
    # legacy MIN_NOTIONAL constraint.
    min_notional = Decimal("5")
    for filter_name in ("NOTIONAL", "MIN_NOTIONAL"):
        raw_min = (flt.get(filter_name) or {}).get("minNotional")
        try:
            candidate = Decimal(str(raw_min))
        except (TypeError, ValueError, InvalidOperation):
            continue
        if candidate.is_finite() and candidate > 0:
            min_notional = candidate
            break
    # Use the same fresh WS quote as the spread engine.  A residual sale must
    # never be sized from a separate/stale public REST ticker.
    try:
        price = await client.ws_spot_price(symbol, "bid")
    except Exception as exc:
        logger.warning("residual sell skipped: %s WS price unavailable", symbol)
        return Decimal("0"), f"无法获取 {symbol} WS 现货价格, 稍后重试"
    if price <= 0:
        return Decimal("0"), "取价失败,稍后重试"
    sell_qty = round_to_step(q, step)
    if sell_qty <= 0 or sell_qty * price < min_notional:
        return Decimal("0"), (f"残留 {q:.6f} 名义价值 {float(q * price):.2f}U "
                              f"低于币安最小卖出额 {min_notional}U,暂留账")
    order = await client._request(
        "POST", "https://api.binance.com/sapi/v1/margin/order",
        {"symbol": symbol, "side": "SELL", "type": "MARKET",
         "quantity": f"{sell_qty:.8f}", "sideEffectType": "NO_SIDE_EFFECT", "isIsolated": "FALSE"},
    )
    status = str((order or {}).get("status") or "UNKNOWN").upper()
    try:
        executed_qty = Decimal(str((order or {}).get("executedQty") or "0"))
    except Exception:
        executed_qty = Decimal("0")
    if not executed_qty.is_finite() or executed_qty < 0:
        executed_qty = Decimal("0")
    # Never report more than this request could have sold, even if an invalid
    # exchange/mock response claims a larger execution.
    executed_qty = min(sell_qty, executed_qty)
    if executed_qty <= 0:
        return Decimal("0"), (
            f"卖回单未成交(status={status}, executedQty=0)，{base_asset} 仍留在账户"
        )
    if status != "FILLED" or executed_qty < sell_qty:
        return executed_qty, (
            f"卖回单部分成交 {executed_qty:.6f}/{sell_qty:.6f} {base_asset} "
            f"(status={status})，剩余数量仍留账"
        )
    return executed_qty, f"已卖回 {executed_qty:.6f} {base_asset}"


async def _cleanup_proven_position_residual(
    client: BinanceTradingClient,
    pos: Position,
    *,
    debt_before: Decimal,
    debt_after: Decimal,
    free_after: Decimal,
    repaid_now: Decimal,
    repay_record_before: Decimal,
) -> tuple[Decimal, str]:
    """Sell only a residual that this close cycle can prove it created.

    Margin ``free`` is account-level and may contain the user's own coin, so
    it is only a cap, never the source amount. Provenance requires a recorded
    buy-back order, no earlier partial repayment on this Position, this
    Position owning the complete pre-repay debt, and Binance confirming zero
    debt. The attributable excess is then buy-back fill minus actual repay.

    Sub-minimum-notional amounts remain in margin. Binance dust conversion is
    asset-wide in the spot wallet and cannot distinguish this residual from a
    user's pre-existing coin, so it is intentionally not automatic.
    """
    zero = Decimal("0")
    bought = Decimal(str(getattr(pos, "spot_buy_qty", None) or 0))
    borrowed = Decimal(str(getattr(pos, "borrow_qty", None) or 0))
    if (
        debt_after > REPAY_DEBT_EPSILON
        or repaid_now <= REPAY_DEBT_EPSILON
        or repay_record_before > REPAY_DEBT_EPSILON
        or not getattr(pos, "spot_buy_order_id", None)
        or bought <= REPAY_DEBT_EPSILON
        or debt_before + REPAY_DEBT_EPSILON < borrowed
        or debt_before > borrowed * FEE_BUFFER + REPAY_DEBT_EPSILON
    ):
        return zero, "residual ownership is not provable; left untouched"

    attributable = max(zero, bought - repaid_now)
    sell_cap = min(attributable, max(zero, free_after))
    if sell_cap <= REPAY_DEBT_EPSILON:
        return zero, "no position-owned residual"
    return await sell_residual_spot(client, pos.symbol, pos.base_asset, sell_cap)


async def execute_repay(
    position: Position,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    fee_spot: Decimal = None,
    fee_futures: Decimal = None,
    pre_submit_guard=None,
    operation_lock_token: str | None = None,
    operation_lock_redis=None,
    operation_lock_ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
):
    """Phase 2 of close: repay the margin debt and finalize PnL. PENDING_REPAY → CLOSED.
    fee_spot/fee_futures: 可配双腿吃单费率(仅影响 PnL 口径);None 时回退 TAKER_FEE_RATE,保留旧行为。"""
    operation_lock_guard = None
    if operation_lock_token is not None or operation_lock_redis is not None:
        operation_lock_guard = _OperationLockGuard(
            operation_lock_redis,
            getattr(position, "sub_account_id", 0),
            canonical_position_symbol(getattr(position, "symbol", "")),
            operation_lock_token or "",
            ttl_sec=operation_lock_ttl_sec,
        )
        if not await operation_lock_guard.async_check():
            return False
    repay_guard = _borrow_submit_guard(
        pre_submit_guard,
        None,
        Decimal("0"),
        operation_lock_guard=operation_lock_guard,
    )
    if not _pre_submit_guard_allows(repay_guard):
        return False
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    if not pos or pos.status != "PENDING_REPAY":
        db.close()
        return False
    if not _pre_submit_guard_allows(repay_guard):
        db.close()
        return False
    # 跨进程互斥: CAS 认领,防手动还币与引擎自动还币双发(双倍 repay 会动用账户其他资产)
    claimed = db.query(Position).filter(
        Position.id == pos.id, Position.status == "PENDING_REPAY",
    ).update({"status": "REPAYING"}, synchronize_session=False)
    db.commit()
    if not claimed:
        db.close()
        return False
    db.refresh(pos)
    _publish_position_update(pos, account_note=account_note)

    def _restore_pending_repay() -> None:
        pos.status = "PENDING_REPAY"
        db.commit()
        _publish_position_update(pos, account_note=account_note)

    if not _pre_submit_guard_allows(repay_guard):
        _restore_pending_repay()
        db.close()
        return False

    try:
        # 买回的币入杠杆账户有结算延迟 —— 轮询等 free 覆盖负债(最长 ~8s),
        # 再决定全额还/按 free 封顶,避免把settlement-lag误判成粉尘留下整笔欠债
        async def _read_debt_free():
            mi = await client.get_margin_account()
            for a in mi.get("userAssets", []):
                if a["asset"] == pos.base_asset:
                    return (Decimal(str(a.get("borrowed", "0"))) + Decimal(str(a.get("interest", "0"))),
                            Decimal(str(a.get("interest", "0"))),
                            Decimal(str(a.get("free", "0"))))
            return Decimal("0"), Decimal("0"), Decimal("0")

        total_debt, interest_amount, free_bal = await _read_debt_free()
        debt_before = total_debt
        repay_record_before = Decimal(str(pos.repay_qty or 0))
        pos_owed = pos.borrow_qty * FEE_BUFFER   # 本仓应还额(先算,等待循环用)
        for _ in range(6):
            if total_debt <= 0 or free_bal >= pos_owed:
                break
            await asyncio.sleep(1.3)
            total_debt, interest_amount, free_bal = await _read_debt_free()
        # 按仓分配债务:本仓应还 = 本仓借量 × FEE_BUFFER(覆盖利息+扣币),与 unhedge 买回口径一致。
        # 多仓并存时 total_debt 是账户总债,会被首个还币的仓"全额还清",后续仓 repay_qty=0 记账失真。
        # min(pos_owed, total_debt) 防止最后一仓超还(前面仓已归还部分,剩余 < pos_owed 时封顶)。
        # 币安真实债务已为0(用户在App/持币汇总手动还过、或他仓还币已清账)= 没有可还的了 → 直接
        # 零额收口。原回退分支拿 DB borrow_qty 当应还额,对着不存在的债务用粉尘 free 反复还 →
        # -3015"还款超过借款"→ 异常回 PENDING_REPAY → 1s级无限重试(实测012卡死+告警轰炸)。
        def _defer_repay(reason: str) -> None:
            pos.status = "PENDING_REPAY"
            pos.closed_at = None
            pos.error_message = reason
            pos.retry_count = (pos.retry_count or 0) + 1
            db.commit()
            _publish_balance_refresh(
                pos.user_id if getattr(pos, "user_id", None) is not None
                else _resolve_user_id(db, pos.sub_account_id)
            )
            _publish_position_update(pos, account_note=account_note)

        if not _pre_submit_guard_allows(repay_guard):
            _restore_pending_repay()
            return False
        t0 = time.monotonic()
        repay_target = Decimal("0")
        if total_debt <= REPAY_DEBT_EPSILON:
            logger.info(f"Repay {pos.symbol}: 币安债务已为0(外部已清),零额收口不发还币")
            repay_amount = Decimal("0")
        else:
            repay_target = min(pos_owed, total_debt)
            repay_amount = repay_target
            # 等满后 free 仍不足(手续费扣币的真实小额缺口): 按 free 封顶,真·粉尘留账
            if Decimal("0") < free_bal < repay_amount:
                logger.warning(f"Repay {pos.symbol}: free {free_bal} < debt {repay_amount} after settle wait, "
                               f"repaying free (dust {repay_amount - free_bal} stays)")
                repay_amount = free_bal
            if free_bal <= REPAY_DEBT_EPSILON:
                reason = (
                    f"Residual margin debt {total_debt} {pos.base_asset} remains; "
                    "no free balance is available to repay it"
                )
                logger.warning("Repay %s deferred: %s", pos.symbol, reason)
                _defer_repay(reason)
                return False
            # 买回后立即还币会踩杠杆账户结算延迟(-3041 Balance is not enough)—— 重试等结算
            for attempt in range(4):
                try:
                    if not _pre_submit_guard_allows(repay_guard):
                        _restore_pending_repay()
                        return False
                    await client.margin_repay(
                        pos.base_asset,
                        repay_amount,
                        **_pre_submit_kwargs(repay_guard),
                    )
                    break
                except BinanceAPIError as re_err:
                    if re_err.api_code == -3041 and attempt < 3:
                        await asyncio.sleep(1.5)
                        continue
                    if re_err.api_code == -3015:
                        # 还款超过借款=债务在我们读数后被外部清掉(竞态)。复核:确实≈0 → 零额收口
                        _d2, _i2, _f2 = await _read_debt_free()
                        if _d2 <= Decimal("0.00000001"):
                            logger.info(f"Repay {pos.symbol}: -3015后复核债务=0,零额收口")
                            repay_amount = Decimal("0")
                            break
                    raise
        latency = int((time.monotonic() - t0) * 1000)
        pos.repay_qty = (pos.repay_qty or Decimal("0")) + repay_amount
        pos.repay_interest = interest_amount
        _log_trade(db, pos.id, pos.sub_account_id, "REPAY", pos.symbol,
                    quantity=repay_amount, status="SUCCESS", latency=latency)

        # A successful Binance response only confirms the submitted amount.
        # It does not prove this position's debt was fully cleared. In
        # particular, fee/interest can make free balance slightly smaller than
        # the debt. Verify the authoritative margin balance before CLOSED.
        expected_other_debt = max(Decimal("0"), total_debt - repay_target)
        debt_after = total_debt
        free_after = free_bal
        verify_delays = (
            (0.0,)
            if repay_amount + REPAY_DEBT_EPSILON < repay_target
            else REPAY_DEBT_VERIFY_DELAYS
        )
        for delay in verify_delays:
            if delay > 0:
                await asyncio.sleep(delay)
            debt_after, _interest_after, free_after = await _read_debt_free()
            if debt_after <= expected_other_debt + REPAY_DEBT_EPSILON:
                break
        if debt_after > expected_other_debt + REPAY_DEBT_EPSILON:
            reason = (
                f"Residual margin debt {debt_after} {pos.base_asset} remains "
                f"after repaying {repay_amount}"
            )
            logger.warning("Repay %s incomplete: %s", pos.symbol, reason)
            _defer_repay(reason)
            return False

        if debt_after <= REPAY_DEBT_EPSILON:
            try:
                residual_sold, residual_note = await _cleanup_proven_position_residual(
                    client,
                    pos,
                    debt_before=debt_before,
                    debt_after=debt_after,
                    free_after=free_after,
                    repaid_now=repay_amount,
                    repay_record_before=repay_record_before,
                )
                if residual_sold > REPAY_DEBT_EPSILON:
                    _log_trade(
                        db, pos.id, pos.sub_account_id, "SPOT_RESIDUAL_SELL", pos.symbol,
                        side="SELL", quantity=residual_sold, status="SUCCESS",
                    )
                    logger.info(
                        "Position-owned residual cleaned: %s qty=%s",
                        pos.symbol, residual_sold,
                    )
                elif residual_note:
                    logger.info("Residual cleanup skipped %s: %s", pos.symbol, residual_note)
            except Exception as cleanup_error:
                # Debt and both hedge legs are already closed. Cleanup failure
                # must not restart repayment; retain the harmless asset for a
                # later explicit cleanup.
                logger.warning(
                    "Residual cleanup deferred %s: %s", pos.symbol, cleanup_error,
                )

        # Finalize PnL (fees + interest)
        # 腿字段 None 归零:BORROWED_IDLE(借了未开腿)直转 PENDING_REPAY 还币时,现/期四腿字段
        # 全 NULL → None*None TypeError,margin_repay 已成功但状态写不回 → 卡 REPAYING 二次卡死。
        _z = Decimal("0")
        _ssq = pos.spot_sell_qty or _z; _ssp = pos.spot_sell_price or _z
        _sbq = pos.spot_buy_qty or _z;  _sbp = pos.spot_buy_price or _z
        _flq = pos.futures_long_qty or _z; _flp = pos.futures_long_price or _z
        _fcp = pos.futures_close_price or _z
        spot_pnl = (_ssq * _ssp) - (_sbq * _sbp)
        futures_pnl = (_fcp - _flp) * _flq
        spot_sell_notional = _ssq * _ssp
        spot_buy_notional = _sbq * _sbp
        futures_open_notional = _flq * _flp
        futures_close_notional = _flq * _fcp
        # 双腿吃单费率(可配): 现货腿与合约腿分开,None 回退硬编码常量(旧行为)
        f_spot = Decimal(str(fee_spot)) if fee_spot is not None else TAKER_FEE_RATE
        f_fut = Decimal(str(fee_futures)) if fee_futures is not None else TAKER_FEE_RATE
        total_fee = (spot_sell_notional + spot_buy_notional) * f_spot \
            + (futures_open_notional + futures_close_notional) * f_fut
        interest_cost = interest_amount * _sbp if interest_amount else Decimal("0")
        pos.fee_total = total_fee + interest_cost
        pos.realized_pnl = spot_pnl + futures_pnl - total_fee - interest_cost
        # P0-3 逐回路净损益:realized_pnl 不含资金费(资金费单独落 cumulative_funding_fee),
        # 本回路真实净 = realized + 已结算资金费。这是"这一轮开平到底赚没赚"的唯一真值,
        # 与 expected_e(开仓预期)同 USDT 口径,供 dashboard/admin 历史逐笔展示 + 事后校准 E 闸准度。
        _funding = pos.cumulative_funding_fee or Decimal("0")
        pos.round_net_pnl = pos.realized_pnl + _funding
        pos.closed_at = datetime.now(timezone.utc)
        pos.status = "CLOSED"
        pos.error_message = None
        db.commit()

        logger.info(f"Position closed (repaid): {pos.symbol} pnl={pos.realized_pnl}")

        # 写后即时刷新:还币平仓(引擎自动 / manual-repay 端点都走此函数)→ 该用户余额秒级刷新
        _publish_balance_refresh(
            pos.user_id if getattr(pos, "user_id", None) is not None
            else _resolve_user_id(db, pos.sub_account_id))
        _publish_position_update(pos, account_note=account_note)   # CLOSED → 前端秒级删行
        await notifier.notify_position_closed(account_note, pos.symbol, pos.realized_pnl, pos.close_spread or Decimal("0"))
        return True

    except BinancePreSubmitRejected:
        _restore_pending_repay()
        return False
    except BinanceAPIError as e:
        logger.error(f"Repay failed: {e}")
        pos.status = "PENDING_REPAY"   # 回退可重试态(REPAYING 无人消费会永久卡死)
        pos.error_message = str(e)
        pos.retry_count = (pos.retry_count or 0) + 1
        db.commit()
        _publish_position_update(pos, account_note=account_note)
        _log_trade(db, pos.id, pos.sub_account_id, "REPAY", pos.symbol, status="FAILED", error=str(e))
        await notifier.notify_error(account_note, f"repay {pos.symbol}", str(e))
        return False
    except Exception as e:
        logger.error(f"Repay failed unexpectedly: {e}", exc_info=True)
        if pos.status == "REPAYING":
            pos.status = "PENDING_REPAY"
            pos.retry_count = (pos.retry_count or 0) + 1
        pos.error_message = str(e)
        db.commit()
        _publish_position_update(pos, account_note=account_note)
        await notifier.notify_error(account_note, f"repay {pos.symbol}", str(e))
        return pos.status == "CLOSED"
    finally:
        db.close()


async def execute_close(
    position: Position,
    spread: SpreadSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    futures_client: BinanceTradingClient = None,
    spot_order_mode: str = "market",
    allow_emergency_close: bool = False,
    emergency: bool | None = None,
    user_id: int | None = None,
    operation_lock_token: str | None = None,
    operation_lock_redis=None,
    operation_lock_ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
):
    """Atomic close (unhedge + repay in one shot) — used by manual-close / tail cleanup."""
    if emergency is not None:
        allow_emergency_close = bool(emergency)
    unhedged = await execute_unhedge(
        position,
        spread,
        client,
        notifier,
        account_note,
        futures_client=futures_client,
        user_id=user_id,
        spot_order_mode=spot_order_mode,
        allow_emergency_close=allow_emergency_close,
        operation_lock_token=operation_lock_token,
        operation_lock_redis=operation_lock_redis,
        operation_lock_ttl_sec=operation_lock_ttl_sec,
    )
    if not unhedged:
        return False
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    db.close()
    if pos and pos.status == "PENDING_REPAY":
        return bool(await execute_repay(
            pos,
            client,
            notifier,
            account_note,
            operation_lock_token=operation_lock_token,
            operation_lock_redis=operation_lock_redis,
            operation_lock_ttl_sec=operation_lock_ttl_sec,
        ))
    return bool(pos and pos.status == "CLOSED")


async def execute_borrow_only_repay(
    sub_account_id: int,
    symbol: str,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    user_id: int = None,
    pre_submit_guard=None,
    operation_lock_token: str | None = None,
    operation_lock_redis=None,
    operation_lock_ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
):
    """Repay an untracked debt and record it only after Binance confirms zero debt."""
    operation_lock_guard = None
    if operation_lock_token is not None or operation_lock_redis is not None:
        operation_lock_guard = _OperationLockGuard(
            operation_lock_redis,
            sub_account_id,
            canonical_position_symbol(symbol),
            operation_lock_token or "",
            ttl_sec=operation_lock_ttl_sec,
        )
        if not await operation_lock_guard.async_check():
            return False
    repay_guard = _borrow_submit_guard(
        pre_submit_guard,
        None,
        Decimal("0"),
        operation_lock_guard=operation_lock_guard,
    )
    if not _pre_submit_guard_allows(repay_guard):
        return False
    base_asset = symbol.replace("USDT", "")
    db = SessionLocal()
    try:
        total_debt, interest_amount = await _get_asset_debt(client, base_asset)
        if total_debt <= REPAY_DEBT_EPSILON:
            return True

        if not _pre_submit_guard_allows(repay_guard):
            return False
        await client.margin_repay(
            base_asset,
            total_debt,
            **_pre_submit_kwargs(repay_guard),
        )

        debt_after = total_debt
        for delay in REPAY_DEBT_VERIFY_DELAYS:
            if delay > 0:
                await asyncio.sleep(delay)
            debt_after, _interest_after = await _get_asset_debt(client, base_asset)
            if debt_after <= REPAY_DEBT_EPSILON:
                break
        if debt_after > REPAY_DEBT_EPSILON:
            message = (
                f"Residual margin debt {debt_after} {base_asset} remains after "
                f"borrow-only repay {total_debt}"
            )
            logger.warning("Borrow-only repay incomplete %s: %s", symbol, message)
            _log_trade(
                db, None, sub_account_id, "BORROW_ONLY_REPAY", symbol,
                quantity=total_debt, status="FAILED", error=message,
            )
            _publish_balance_refresh(
                user_id if user_id is not None else _resolve_user_id(db, sub_account_id)
            )
            return False

        position = Position(
            sub_account_id=sub_account_id,
            symbol=symbol,
            base_asset=base_asset,
            status="CLOSED",
            user_id=user_id,
            borrow_qty=total_debt - interest_amount,
            repay_qty=total_debt,
            repay_interest=interest_amount,
            cumulative_interest=interest_amount,
            realized_pnl=-interest_amount,
            fee_total=interest_amount,
            opened_at=datetime.now(timezone.utc),
            closed_at=datetime.now(timezone.utc),
            error_message="borrow-only repay (no position opened)",
        )
        db.add(position)
        db.commit()

        _log_trade(db, position.id, sub_account_id, "BORROW_ONLY_REPAY", symbol,
                    quantity=total_debt, status="SUCCESS")
        # 债务已清 → 现币/借币列即时刷新(不等 10s 轮询)
        _publish_balance_refresh(user_id if user_id is not None else _resolve_user_id(db, sub_account_id))

        logger.info(f"Borrow-only repay: {symbol} debt={total_debt} interest={interest_amount}")
        try:
            await notifier.send(
                "借币还币记录",
                f"账户: {account_note}\n币种: {symbol}\n借币: {total_debt - interest_amount}\n利息: {interest_amount}",
            )
        except Exception:
            logger.warning("Borrow-only repay notification failed %s", symbol, exc_info=True)
        return True
    except BinancePreSubmitRejected:
        return False
    except Exception as e:
        logger.error(f"Borrow-only repay failed {symbol}: {e}")
        _log_trade(db, None, sub_account_id, "BORROW_ONLY_REPAY", symbol,
                    status="FAILED", error=str(e))
        return False
    finally:
        db.close()


def _avg_fill_price(order_result: dict) -> Decimal:
    """Return a reliable average execution price from a Binance order payload.

    Spot ``MARKET`` orders returned with ``newOrderRespType=RESULT`` do not
    consistently include ``fills``.  In that shape Binance can report
    ``price=0`` while ``executedQty`` and ``cummulativeQuoteQty`` are already
    populated.  Treat the cumulative quote amount as the source of truth
    before falling back to the less reliable display price fields.  Malformed
    or non-positive values are ignored so a zero price can never masquerade as
    a valid accounting value.
    """
    if not isinstance(order_result, dict):
        return Decimal("0")

    def _positive(value) -> Decimal | None:
        try:
            parsed = Decimal(str(value))
        except (TypeError, ValueError, ArithmeticError):
            return None
        if not parsed.is_finite() or parsed <= 0:
            return None
        return parsed

    # A response containing fills is the most precise representation.  Ignore
    # malformed individual rows and continue to the cumulative response shape
    # when no usable fill remains.
    fills = order_result.get("fills")
    if isinstance(fills, (list, tuple)):
        total_qty = Decimal("0")
        total_quote = Decimal("0")
        fills_complete = True
        for fill in fills:
            if not isinstance(fill, dict):
                fills_complete = False
                continue
            fill_qty = _positive(fill.get("qty", fill.get("quantity")))
            fill_price = _positive(fill.get("price"))
            if fill_qty is None or fill_price is None:
                fills_complete = False
                continue
            total_qty += fill_qty
            total_quote += fill_qty * fill_price
        if fills_complete and total_qty > 0 and total_quote > 0:
            # A few gateways expose a partial ``fills`` array while the
            # cumulative response already covers the complete order.  Use the
            # weighted rows only when they agree with executedQty (within
            # exchange rounding tolerance); otherwise fall through to quote
            # quantity instead of silently under-valuing the order.
            executed_for_fills = _positive(order_result.get("executedQty"))
            if executed_for_fills is None or abs(total_qty - executed_for_fills) <= max(
                Decimal("0.00000001"), executed_for_fills * Decimal("0.0000001")
            ):
                return total_quote / total_qty

    executed_qty = _positive(order_result.get("executedQty"))
    if executed_qty is not None:
        # Binance has used all of these spellings across spot, margin and
        # futures-compatible gateways.  Keep the order-specific cumulative
        # fields ahead of ``avgPrice``/``price`` because those fields are often
        # zero in an otherwise successful RESULT response.
        for quote_key in (
            "cummulativeQuoteQty",
            "cumQuote",
            "quoteQty",
            "cumulativeQuoteQty",
        ):
            quote_qty = _positive(order_result.get(quote_key))
            if quote_qty is not None:
                return quote_qty / executed_qty

    for price_key in ("avgPrice", "price"):
        price = _positive(order_result.get(price_key))
        if price is not None:
            return price
    return Decimal("0")


def _recovery_decimal(value, *, allow_negative: bool = True) -> Decimal | None:
    """Parse an exchange quantity for the crash-recovery path.

    ``None`` means unknown.  Recovery must never turn malformed exchange data
    into a zero balance and then advance a lifecycle row.
    """
    try:
        result = Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return None
    if not result.is_finite() or (not allow_negative and result < 0):
        return None
    return result


async def _recovery_call(client, method: str, *args):
    """Invoke a safety reader while supporting old sync test doubles."""
    fn = getattr(client, method, None) if client is not None else None
    if not callable(fn):
        raise RuntimeError(f"recovery reader unavailable: {method}")
    result = fn(*args)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _recovery_futures_snapshot(client, symbol: str) -> tuple[bool, Decimal, dict | None]:
    """Return ``(known, signed_position_qty, raw_row)`` for one symbol."""
    payload = None
    reader = getattr(client, "get_futures_position", None)
    if callable(reader):
        payload = await _recovery_call(client, "get_futures_position", symbol)
    else:
        payload = await _recovery_call(client, "futures_position_risk", symbol)
    if payload is None:
        return True, Decimal("0"), None
    if not isinstance(payload, dict):
        return False, Decimal("0"), None
    if str(payload.get("symbol") or "").upper() != str(symbol).upper():
        return False, Decimal("0"), None
    amount = _recovery_decimal(payload.get("positionAmt"))
    if amount is None:
        return False, Decimal("0"), None
    return True, amount, payload


async def _recovery_orders_snapshot(client, method: str, symbol: str) -> tuple[bool, list[dict]]:
    try:
        payload = await _recovery_call(client, method, symbol)
    except Exception:
        return False, []
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        return False, []
    return True, payload


def _recovery_asset_state(payload, asset: str) -> tuple[Decimal, Decimal, Decimal] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("userAssets"), list):
        return None
    for item in payload["userAssets"]:
        if not isinstance(item, dict) or str(item.get("asset") or "").upper() != asset.upper():
            continue
        borrowed = _recovery_decimal(item.get("borrowed"), allow_negative=False)
        interest = _recovery_decimal(item.get("interest"), allow_negative=False)
        free = _recovery_decimal(item.get("free"), allow_negative=False)
        if borrowed is None or interest is None or free is None:
            return None
        return borrowed, interest, free
    # A missing asset row is a valid zero-debt response from Binance.
    return Decimal("0"), Decimal("0"), Decimal("0")


async def _recovery_spot_order_fill(client, symbol: str, order_id) -> tuple[bool, Decimal, Decimal, str]:
    """Read a recorded margin order; unknown responses fail closed."""
    if not order_id:
        return True, Decimal("0"), Decimal("0"), ""
    try:
        result = await _recovery_call(client, "spot_query_order", symbol, str(order_id), True)
    except Exception:
        return False, Decimal("0"), Decimal("0"), ""
    if not isinstance(result, dict):
        return False, Decimal("0"), Decimal("0"), ""
    qty = _recovery_decimal(result.get("executedQty"), allow_negative=False)
    if qty is None:
        return False, Decimal("0"), Decimal("0"), ""
    # Spot order-query responses commonly omit ``avgPrice`` and report a zero
    # display ``price``.  Reuse the same fills/quote-total parser as the live
    # path so a confirmed market fill is not recorded with a zero price.
    avg = _avg_fill_price(result)
    if qty > RECOVERY_EPSILON and avg <= RECOVERY_EPSILON:
        # Quantity alone is insufficient accounting evidence.  Keep the row in
        # its transitional state until a later exchange read contains a real
        # quote total/fill price; never promote it with a zero notional.
        return False, qty, Decimal("0"), str(result.get("status") or "").upper()
    return True, qty, avg, str(result.get("status") or "").upper()


def _recovery_spot_sell_order_ids(db, position_id: int, fallback=None) -> list[str]:
    """Collect all durable spot-sell order ids for one position.

    A Position stores only the latest tranche order id, while TradeLog keeps
    each tranche.  Reading both lets crash recovery reconstruct a cumulative
    average when an earlier response wrote a zero price.
    """
    values: list[str] = []

    def _add(value) -> None:
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)

    _add(fallback)
    try:
        rows = db.query(TradeLog).filter(
            TradeLog.position_id == position_id,
            TradeLog.action == "SPOT_SELL",
        ).all()
    except Exception:
        rows = []
    for row in rows or []:
        _add(getattr(row, "order_id", None))
    return values


async def _recovery_spot_sell_fill(
    client,
    symbol: str,
    recorded_qty: Decimal,
    recorded_price: Decimal | None,
    order_ids: list[str],
) -> tuple[Decimal, Decimal] | None:
    """Reconstruct a cumulative spot-sale quantity/price from exchange fills."""
    try:
        qty = recorded_qty if recorded_qty is not None else Decimal("0")
        price = recorded_price if recorded_price is not None else Decimal("0")
    except (TypeError, ValueError, ArithmeticError):
        return None
    if not qty.is_finite() or qty < 0 or not price.is_finite() or price < 0:
        return None
    if qty > RECOVERY_EPSILON and price > RECOVERY_EPSILON:
        return qty, price
    if not order_ids:
        return None

    total_qty = Decimal("0")
    total_value = Decimal("0")
    for order_id in order_ids:
        known, filled, avg, status = await _recovery_spot_order_fill(
            client, symbol, order_id
        )
        if (
            not known
            or status not in {"FILLED", "PARTIALLY_FILLED"}
            or filled <= RECOVERY_EPSILON
            or avg <= RECOVERY_EPSILON
        ):
            return None
        total_qty += filled
        total_value += filled * avg

    if total_qty <= RECOVERY_EPSILON or total_value <= RECOVERY_EPSILON:
        return None
    if qty <= RECOVERY_EPSILON:
        qty = total_qty
    else:
        # The durable quantity is cumulative across tranches.  A small
        # exchange/rounding difference is tolerated, but a materially
        # different amount is ambiguous and must remain recoverable/manual.
        tolerance = max(RECOVERY_EPSILON, qty * Decimal("0.005"))
        if abs(total_qty - qty) > tolerance:
            return None
    return qty, total_value / total_qty


def _recovery_stale(position, now: datetime | None = None, stale_after_sec: int = TRANSITIONAL_RECOVERY_STALE_SEC) -> bool:
    stamp = getattr(position, "updated_at", None) or getattr(position, "created_at", None)
    if not isinstance(stamp, datetime):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    try:
        return (now - stamp).total_seconds() >= max(1, int(stale_after_sec))
    except (TypeError, ValueError, OverflowError):
        return False


def _recovery_managed_other_futures_qty(
    db,
    *,
    position_id: int,
    sub_account_id: int,
    user_id: int | None,
    symbol: str,
    route: str,
) -> Decimal | None:
    """Return the recorded futures quantity owned by other live positions.

    Binance one-way mode exposes one net quantity per account/symbol.  When
    several sub-accounts hedge through the same master account, that total is
    not the quantity owned by the row being recovered.  Subtract only other
    rows with a durable recorded futures leg; any malformed quantity or an
    unknown master tenant makes the recovery decision ambiguous.
    """
    if route == "master" and user_id is None:
        return None
    try:
        query = db.query(Position).filter(
            Position.id != position_id,
            Position.symbol == symbol,
            Position.hedge_account == route,
            Position.status.in_(RECOVERY_FUTURES_OWNING_STATUSES),
        )
        if route == "master":
            query = query.filter(Position.user_id == user_id)
        else:
            query = query.filter(Position.sub_account_id == sub_account_id)
        rows = query.all()
    except Exception:
        logger.warning(
            "Interrupted position %s blocked: unable to load managed futures baseline",
            position_id,
            exc_info=True,
        )
        return None

    total = Decimal("0")
    for row in rows:
        qty = _recovery_decimal(
            getattr(row, "futures_long_qty", None), allow_negative=False
        )
        if qty is None:
            return None
        total += qty
    return total


def _recovery_qty_matches(actual: Decimal, expected: Decimal) -> bool:
    return abs(actual - expected) <= RECOVERY_EPSILON


async def recover_interrupted_position(
    position_id: int,
    *,
    sub_account_id: int,
    user_id: int | None,
    margin_client,
    futures_client,
    notifier=None,
    account_note: str = "",
    stale_after_sec: int = TRANSITIONAL_RECOVERY_STALE_SEC,
    operation_lock_token: str | None = None,
    operation_lock_redis=None,
    operation_lock_ttl_sec: int = ACCOUNT_OPERATION_LOCK_TTL_SEC,
) -> str | None:
    """Resume a position left in a mid-pipeline state after a crash.

    Only stale rows are considered and every transition is guarded by a
    second ``status`` predicate.  Positive/unknown exchange responses leave
    the row untouched.  Risk-reducing spot buy-back or futures close is
    attempted only after the corresponding order book is proven empty.
    """
    operation_lock_guard = None
    db = SessionLocal()
    try:
        pos = db.query(Position).filter(
            Position.id == position_id,
            Position.sub_account_id == sub_account_id,
            Position.status.in_(TRANSITIONAL_POSITION_STATUSES),
        ).first()
        if not pos or not _recovery_stale(pos, stale_after_sec=stale_after_sec):
            return None
        route = str(getattr(pos, "hedge_account", "") or "").strip().lower()
        if route not in {"sub", "master"} or futures_client is None or margin_client is None:
            logger.error(
                "Interrupted position %s blocked: unknown hedge route or client unavailable",
                position_id,
            )
            return None
        symbol = str(pos.symbol or "").upper()
        if not symbol:
            return None
        if operation_lock_token is not None or operation_lock_redis is not None:
            operation_lock_guard = _OperationLockGuard(
                operation_lock_redis,
                sub_account_id,
                canonical_position_symbol(symbol),
                operation_lock_token or "",
                ttl_sec=operation_lock_ttl_sec,
            )
            if not await operation_lock_guard.async_check():
                return None
        owner_user_id = getattr(pos, "user_id", None)
        if owner_user_id is None:
            owner_user_id = user_id
        other_futures_qty = _recovery_managed_other_futures_qty(
            db,
            position_id=position_id,
            sub_account_id=sub_account_id,
            user_id=owner_user_id,
            symbol=symbol,
            route=route,
        )
        if other_futures_qty is None:
            return None
        # Detach the minimal immutable values before exchange I/O.  The final
        # DB mutation below is a CAS so a concurrent worker/API cannot be
        # overwritten by this recovery pass.
        state = {
            "status": str(pos.status or "").upper(),
            "base_asset": str(pos.base_asset or symbol.removesuffix("USDT")).upper(),
            "borrow_qty": _recovery_decimal(getattr(pos, "borrow_qty", 0), allow_negative=False),
            "spot_sell_qty": _recovery_decimal(getattr(pos, "spot_sell_qty", 0), allow_negative=False),
            "spot_sell_price": _recovery_decimal(getattr(pos, "spot_sell_price", 0), allow_negative=False),
            "spot_sell_order_id": getattr(pos, "spot_sell_order_id", None),
            "spot_sell_order_ids": _recovery_spot_sell_order_ids(
                db,
                position_id,
                getattr(pos, "spot_sell_order_id", None),
            ),
            "spot_buy_qty": _recovery_decimal(getattr(pos, "spot_buy_qty", 0), allow_negative=False),
            "spot_buy_price": _recovery_decimal(getattr(pos, "spot_buy_price", 0), allow_negative=False),
            "futures_long_qty": _recovery_decimal(getattr(pos, "futures_long_qty", 0), allow_negative=False),
            "futures_long_price": _recovery_decimal(getattr(pos, "futures_long_price", 0), allow_negative=False),
            "futures_long_order_id": getattr(pos, "futures_long_order_id", None),
            "spot_buy_order_id": getattr(pos, "spot_buy_order_id", None),
            "futures_close_order_id": getattr(pos, "futures_close_order_id", None),
            "other_futures_qty": other_futures_qty,
        }
    finally:
        db.close()

    # All recovery states need a fresh, authoritative futures position and
    # empty order book.  A negative (short) position is never treated as a
    # completed long hedge.
    fut_known, fut_qty, fut_row = await _recovery_futures_snapshot(futures_client, symbol)
    fut_orders_known, fut_orders = await _recovery_orders_snapshot(
        futures_client, "get_futures_open_orders", symbol
    )
    margin_orders_known, margin_orders = await _recovery_orders_snapshot(
        margin_client, "get_margin_open_orders", symbol
    )
    if not fut_known or not fut_orders_known or not margin_orders_known:
        return None
    if fut_qty < -RECOVERY_EPSILON:
        return None
    other_futures_qty = state["other_futures_qty"]
    if fut_qty + RECOVERY_EPSILON < other_futures_qty:
        return None
    current_futures_qty = fut_qty - other_futures_qty
    if abs(current_futures_qty) <= RECOVERY_EPSILON:
        current_futures_qty = Decimal("0")

    async def _cas(expected: str, values: dict, *, action: str) -> str | None:
        values = dict(values)
        values.setdefault("updated_at", datetime.now(timezone.utc))
        session = SessionLocal()
        try:
            changed = session.query(Position).filter(
                Position.id == position_id,
                Position.sub_account_id == sub_account_id,
                Position.status == expected,
            ).update(values, synchronize_session=False)
            if not changed:
                session.rollback()
                return None
            session.commit()
            row = session.query(Position).filter(Position.id == position_id).first()
            if row is not None:
                _publish_position_update(row, user_id, account_note)
            return action
        except Exception:
            session.rollback()
            logger.warning("Interrupted position CAS failed %s", position_id, exc_info=True)
            return None
        finally:
            session.close()

    state_name = state["status"]
    sold = state["spot_sell_qty"]
    sold = sold if sold is not None else Decimal("0")
    borrowed = state["borrow_qty"]
    borrowed = borrowed if borrowed is not None else Decimal("0")

    async def _finish_close_after_spot() -> str | None:
        """Close this row's futures share after spot buy-back is proven."""
        known, current, _ = await _recovery_futures_snapshot(futures_client, symbol)
        orders_known, orders = await _recovery_orders_snapshot(
            futures_client, "get_futures_open_orders", symbol
        )
        if not known or not orders_known or orders:
            return None
        if current < other_futures_qty - RECOVERY_EPSILON:
            return None
        current_owned = current - other_futures_qty
        target_qty = state["futures_long_qty"] or current_owned
        if target_qty <= RECOVERY_EPSILON:
            return None
        if current_owned <= RECOVERY_EPSILON:
            closed = await _cas(
                "SPOT_BOUGHT",
                {
                    "status": "FUTURES_CLOSED",
                    "error_message": "futures close already confirmed after restart",
                },
                action="futures_closed",
            )
            if closed:
                return await _cas(
                    "FUTURES_CLOSED",
                    {"status": "PENDING_REPAY"},
                    action="pending_repay",
                )
            return None
        if not _recovery_qty_matches(current_owned, target_qty):
            return None
        if operation_lock_guard is not None and not await operation_lock_guard.async_check():
            return None
        try:
            close_fn = getattr(futures_client, "futures_market_close")
            try:
                result = await close_fn(
                    symbol,
                    target_qty,
                    **_pre_submit_kwargs(operation_lock_guard),
                )
            except TypeError:
                if operation_lock_guard is not None:
                    return None
                result = await _recovery_call(
                    futures_client, "futures_market_close", symbol, target_qty
                )
            result = await _confirm_futures_result(
                futures_client, symbol, result
            )
            result, close_status, close_qty, close_price = _futures_fill_metrics(
                result
            )
            close_id = str((result or {}).get("orderId") or "") or None
            known_after, qty_after, _ = await _recovery_futures_snapshot(
                futures_client, symbol
            )
            if not known_after or not _recovery_qty_matches(qty_after, other_futures_qty):
                return None
            # A few legacy gateways omit executedQty/status from a close
            # response.  Only in recovery, and only after the authoritative
            # net-position delta proves this row's exact share was removed,
            # may we fill those missing fields.  An explicit zero or a
            # non-terminal status is never upgraded this way.
            if (
                "executedQty" not in result
                and not close_status
                and close_price > RECOVERY_EPSILON
            ):
                close_status = "FILLED"
                close_qty = target_qty
            if (
                close_status != "FILLED"
                or close_qty + RECOVERY_EPSILON < target_qty
                or close_price <= RECOVERY_EPSILON
            ):
                await _cas(
                    "SPOT_BOUGHT",
                    {
                        "status": "SPOT_BOUGHT",
                        "futures_close_order_id": close_id,
                        "error_message": (
                            f"futures close not fully confirmed after spot buy-back: "
                            f"status={close_status or 'UNKNOWN'}, qty={close_qty}/{target_qty}, "
                            f"avgPrice={close_price}"
                        ),
                    },
                    action="futures_close_pending",
                )
                return None
            closed = await _cas(
                "SPOT_BOUGHT",
                {
                    "status": "FUTURES_CLOSED",
                    "futures_close_price": close_price,
                    "futures_close_order_id": close_id,
                    "error_message": "futures close reconciled after spot buy-back",
                },
                action="futures_closed",
            )
            if closed:
                return await _cas(
                    "FUTURES_CLOSED",
                    {"status": "PENDING_REPAY"},
                    action="pending_repay",
                )
            return None
        except Exception:
            logger.warning("Interrupted futures close after spot buy-back failed %s", symbol, exc_info=True)
            return None

    # Opening recovery: a completed long plus a recorded spot sale is enough
    # to safely promote the row to OPEN.  Partial/mismatched legs stay visible
    # for the naked-short guard rather than being declared healthy.
    if state_name in {"HEDGING", "SPOT_SOLD"}:
        recovered_sold = sold
        recovered_spot_price = state["spot_sell_price"]
        # A prior MARKET RESULT may have persisted a zero display price even
        # though the sale filled.  Re-query every durable sell order before
        # promoting the row; without a positive price the OPEN notional would
        # be zero and subsequent PnL/repay decisions would be corrupt.
        if (
            current_futures_qty > RECOVERY_EPSILON
            and not fut_orders
            and not margin_orders
            and (
                recovered_sold is None
                or recovered_sold <= RECOVERY_EPSILON
                or recovered_spot_price is None
                or recovered_spot_price <= RECOVERY_EPSILON
            )
        ):
            repaired = await _recovery_spot_sell_fill(
                margin_client,
                symbol,
                recovered_sold or Decimal("0"),
                recovered_spot_price,
                state.get("spot_sell_order_ids") or [],
            )
            if repaired is None:
                logger.error(
                    "Interrupted hedge %s blocked: spot sell fill/price could not be verified",
                    symbol,
                )
                return None
            recovered_sold, recovered_spot_price = repaired

        if current_futures_qty > RECOVERY_EPSILON and not fut_orders and not margin_orders:
            borrow_tolerance = max(
                RECOVERY_EPSILON,
                borrowed * Decimal("0.005"),
            )
            if (
                borrowed <= RECOVERY_EPSILON
                or recovered_sold <= RECOVERY_EPSILON
                or recovered_spot_price is None
                or recovered_spot_price <= RECOVERY_EPSILON
                or abs(recovered_sold - borrowed) > borrow_tolerance
            ):
                # Opening can run in several paired tranches.  Equal recorded
                # spot/futures legs may represent only the last committed
                # tranche while a later spot sale filled before its DB commit.
                # Require the durable sale to cover the whole borrowed amount
                # before declaring the position fully open.
                return None
            if recovered_sold <= RECOVERY_EPSILON or abs(current_futures_qty - recovered_sold) > max(
                RECOVERY_EPSILON, recovered_sold * Decimal("0.005")
            ):
                return None
            fut_price = _recovery_decimal(
                (fut_row or {}).get("entryPrice") if fut_row else None,
                allow_negative=False,
            ) or state["futures_long_price"] or Decimal("0")
            if fut_price <= RECOVERY_EPSILON:
                logger.error(
                    "Interrupted hedge %s blocked: futures entry price could not be verified",
                    symbol,
                )
                return None
            return await _cas(
                state_name,
                {
                    "status": "OPEN",
                    "hedge_account": route,
                    "spot_sell_qty": recovered_sold,
                    "spot_sell_price": recovered_spot_price,
                    "futures_long_qty": current_futures_qty,
                    "futures_long_price": fut_price,
                    "open_usdt_amount": recovered_sold * recovered_spot_price,
                    "opened_at": datetime.now(timezone.utc),
                    "error_message": "interrupted hedge reconciled from Binance position",
                },
                action="opened",
            )
        if current_futures_qty <= RECOVERY_EPSILON and not fut_orders and not margin_orders:
            if sold <= RECOVERY_EPSILON:
                # HEDGING is persisted before the spot request.  A zero DB
                # quantity cannot distinguish "request not sent" from "market
                # sell filled but process died before commit"; retrying would
                # risk selling the same borrowed inventory twice.
                return None
            # SPOT_SOLD is also the state used while the ordinary hedge-failure
            # handler buys back the spot leg.  A crash after that buy but before
            # its final commit is indistinguishable from a crash before it.
            # Never issue an unkeyed replacement order from this ambiguous row.
            logger.error(
                "Interrupted hedge %s requires manual spot reconciliation: "
                "recorded sale exists without a futures leg",
                symbol,
            )
            return None

    # New close recovery: CLOSING_SPOT means the margin buy-back was submitted
    # (or is about to be submitted).  Require its recorded order to be
    # terminal and fully filled before touching the shared futures position.
    if state_name == "CLOSING_SPOT":
        order_id = state["spot_buy_order_id"]
        if not order_id:
            return None
        known, filled, avg, order_status = await _recovery_spot_order_fill(
            margin_client, symbol, order_id
        )
        if not known:
            return None
        required_buy = borrowed * FEE_BUFFER
        if (
            order_status != "FILLED"
            or filled <= RECOVERY_EPSILON
            or (
                required_buy > RECOVERY_EPSILON
                and filled + RECOVERY_EPSILON < required_buy
                and filled + RECOVERY_EPSILON < borrowed
            )
        ):
            return None
        promoted = await _cas(
            "CLOSING_SPOT",
            {
                "status": "SPOT_BOUGHT",
                "spot_buy_qty": filled,
                "spot_buy_price": avg,
                "error_message": "spot buy-back fill reconciled after restart",
            },
            action="spot_bought",
        )
        if not promoted:
            return None
        return await _finish_close_after_spot()

    # SPOT_BOUGHT is the durable checkpoint after the first leg.  It is safe
    # to retry only the reduce-only futures close; never buy the spot leg again.
    if state_name == "SPOT_BOUGHT":
        order_id = state["spot_buy_order_id"]
        if not order_id:
            return None
        known, filled, avg, order_status = await _recovery_spot_order_fill(
            margin_client, symbol, order_id
        )
        if not known or order_status != "FILLED":
            return None
        required_buy = borrowed * FEE_BUFFER
        if (
            required_buy > RECOVERY_EPSILON
            and filled + RECOVERY_EPSILON < required_buy
            and filled + RECOVERY_EPSILON < borrowed
        ):
            return None
        return await _finish_close_after_spot()

    # Closing recovery for rows written by the pre-upgrade futures-first
    # state machine.  A flat futures account with no working order proves
    # that this row's managed share reached its terminal state.  The account
    # total may legitimately remain non-zero because other rows share it.
    if state_name == "CLOSING_FUTURES":
        if current_futures_qty <= RECOVERY_EPSILON and not fut_orders:
            return await _cas(
                state_name,
                {"status": "FUTURES_CLOSED", "error_message": "futures close confirmed after restart"},
                action="futures_closed",
            )
        if current_futures_qty > RECOVERY_EPSILON and not fut_orders:
            target = state["futures_long_qty"] or current_futures_qty
            if not _recovery_qty_matches(current_futures_qty, target):
                return None
            close_qty = target
            if close_qty <= RECOVERY_EPSILON:
                return None
            try:
                if operation_lock_guard is not None and not await operation_lock_guard.async_check():
                    return None
                close_fn = getattr(futures_client, "futures_market_close")
                try:
                    result = await close_fn(
                        symbol, close_qty,
                        **_pre_submit_kwargs(operation_lock_guard),
                    )
                except TypeError:
                    if operation_lock_guard is not None:
                        return None
                    result = await _recovery_call(
                        futures_client, "futures_market_close", symbol, close_qty
                    )
                result = await _confirm_futures_result(
                    futures_client, symbol, result
                )
                result, close_status, filled_qty, close_price = _futures_fill_metrics(
                    result
                )
                close_id = str((result or {}).get("orderId") or "") or None
                # Re-read before changing DB state; an ACK alone is not proof.
                # Other managed positions are expected to remain open.
                known_after, qty_after, _ = await _recovery_futures_snapshot(futures_client, symbol)
                if not known_after or not _recovery_qty_matches(qty_after, other_futures_qty):
                    return None
                if (
                    "executedQty" not in result
                    and not close_status
                    and close_price > RECOVERY_EPSILON
                ):
                    # The exact managed net-position delta is an exchange-side
                    # fill proof for legacy responses that omit quantity and
                    # status.  Explicit zero/non-terminal fields remain
                    # rejected below.
                    close_status = "FILLED"
                    filled_qty = close_qty
                if (
                    close_status != "FILLED"
                    or filled_qty + RECOVERY_EPSILON < close_qty
                    or close_price <= RECOVERY_EPSILON
                ):
                    await _cas(
                        state_name,
                        {
                            "status": state_name,
                            "futures_close_order_id": close_id,
                            "error_message": (
                                f"futures close not fully confirmed after restart: "
                                f"status={close_status or 'UNKNOWN'}, qty={filled_qty}/{close_qty}, "
                                f"avgPrice={close_price}"
                            ),
                        },
                        action="futures_close_pending",
                    )
                    return None
                return await _cas(
                    state_name,
                    {"status": "FUTURES_CLOSED", "futures_close_price": close_price,
                     "futures_close_order_id": close_id,
                     "error_message": "futures close reconciled after restart"},
                    action="futures_closed",
                )
            except Exception:
                logger.warning("Interrupted futures close retry failed %s", symbol, exc_info=True)
                return None
        return None

    if state_name in {"FUTURES_CLOSED", "CLOSING_SPOT", "SPOT_BOUGHT"}:
        if current_futures_qty > RECOVERY_EPSILON or fut_orders:
            return None
        order_id = state["spot_buy_order_id"]

        # Existing attempts are reconciliation-only.  A non-terminal, partial,
        # canceled or unreadable order must never fall through to a full-size
        # replacement buy.
        if order_id:
            known, filled, avg, order_status = await _recovery_spot_order_fill(
                margin_client, symbol, order_id
            )
            if not known:
                return None
            required_buy = borrowed * FEE_BUFFER
            fill_is_sufficient = (
                required_buy <= RECOVERY_EPSILON
                or filled + RECOVERY_EPSILON >= required_buy
                or (
                    borrowed > RECOVERY_EPSILON
                    and filled + RECOVERY_EPSILON >= borrowed
                )
            )
            if (
                order_status == "FILLED"
                and filled > RECOVERY_EPSILON
                and fill_is_sufficient
            ):
                return await _cas(
                    state_name,
                    {"status": "PENDING_REPAY", "spot_buy_qty": filled,
                     "spot_buy_price": avg,
                     "error_message": "spot buy fill reconciled after restart"},
                    action="pending_repay",
                )
            return None

        # CLOSING_SPOT is committed before the ordinary market buy.  With no
        # queryable order id, it cannot distinguish pre-submit from an
        # unrecorded fill.  SPOT_BOUGHT without an id is equally unverifiable.
        if state_name != "FUTURES_CLOSED":
            return None
        if margin_orders:
            return None

        # FUTURES_CLOSED proves the spot buy has not started in the current
        # state machine.  Claim it with a real state transition before the one
        # permitted recovery order.  If this process dies after submission,
        # the durable CLOSING_SPOT row is held for manual reconciliation and a
        # later pass cannot buy again.
        claimed = await _cas(
            "FUTURES_CLOSED",
            {
                "status": "CLOSING_SPOT",
                "error_message": "spot buy-back recovery claimed",
            },
            action="spot_buy_claimed",
        )
        if claimed != "spot_buy_claimed":
            return None
        try:
            target = borrowed * FEE_BUFFER
            lot = await _recovery_call(margin_client, "get_lot_size", symbol, "spot")
            step_text = str((lot or {}).get("stepSize") or "0")
            step = Decimal(step_text)
            buy_qty = round_to_step(target, step_text) if step > 0 else target
            if buy_qty < target and step > 0:
                buy_qty += step
            if buy_qty <= RECOVERY_EPSILON:
                return None
            if operation_lock_guard is not None and not await operation_lock_guard.async_check():
                return None
            buy_fn = getattr(margin_client, "spot_market_buy_qty")
            try:
                result = await buy_fn(
                    symbol, buy_qty,
                    **_pre_submit_kwargs(operation_lock_guard),
                )
            except TypeError:
                if operation_lock_guard is not None:
                    return None
                result = await _recovery_call(
                    margin_client, "spot_market_buy_qty", symbol, buy_qty
                )
            filled = _recovery_decimal((result or {}).get("executedQty"), allow_negative=False)
            if filled is None or filled <= RECOVERY_EPSILON:
                return None
            avg = _recovery_decimal((result or {}).get("avgPrice"), allow_negative=False) or _avg_fill_price(result or {})
            if avg <= RECOVERY_EPSILON:
                # The order was submitted but its quote value is not yet
                # provable.  Keep CLOSING_SPOT and let the next recovery pass
                # query the durable order id instead of writing zero price.
                logger.error(
                    "Interrupted spot buy-back %s filled without a verifiable price",
                    symbol,
                )
                return None
            return await _cas(
                "CLOSING_SPOT",
                {"status": "PENDING_REPAY", "spot_buy_qty": filled,
                 "spot_buy_price": avg,
                 "spot_buy_order_id": str((result or {}).get("orderId") or "") or None,
                 "error_message": "spot buy-back resumed after restart"},
                action="pending_repay",
            )
        except Exception:
            logger.warning("Interrupted spot buy-back retry failed %s", symbol, exc_info=True)
            return None
    return None


# ─── Limit / tiered futures entry (hedge-safe: always reconciles to full hedge) ───

LIMIT_WAIT_SEC = 2.0       # max wait per limit tranche before fallback
LIMIT_POLL_SEC = 0.3


def _parse_tiers(tier_ratios: str) -> list[tuple[Decimal, Decimal]]:
    """Parse "0.5:30,0.8:30,1.2:40" -> [(offset_pct, qty_pct), ...].
    Returns [] when empty/invalid (caller falls back to a single tranche)."""
    if not tier_ratios or not tier_ratios.strip():
        return []
    out: list[tuple[Decimal, Decimal]] = []
    try:
        for part in tier_ratios.split(","):
            off, q = part.split(":")
            out.append((Decimal(off.strip()), Decimal(q.strip())))
    except Exception:
        return []
    total = sum(q for _, q in out)
    if total <= 0:
        return []
    return out


async def _poll_fill(client: BinanceTradingClient, symbol: str, order_id: str,
                      timeout: float) -> tuple[Decimal, Decimal]:
    """Poll a futures order until FILLED or timeout. Returns (executedQty, avgPrice)."""
    waited = 0.0
    eq, ap = Decimal("0"), Decimal("0")
    while waited < timeout:
        try:
            o = _normalize_futures_result(
                await client.futures_get_order(symbol, order_id)
            )
            _normalized, _status, eq, ap = _futures_fill_metrics(o)
            if o.get("status") in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
                break
        except Exception:
            pass
        await asyncio.sleep(LIMIT_POLL_SEC)
        waited += LIMIT_POLL_SEC
    return eq, ap


async def _futures_entry_limit(client: BinanceTradingClient, symbol: str, total_qty: Decimal,
                               rules, futures_lot: dict, db, pos, sub_account_id,
                               fill_tracker: dict = None,
                               pre_submit_guard=None) -> dict:
    """Marketable-limit (+ optional tiered) futures long, capping slippage but
    ALWAYS reconciling any unfilled remainder with a market order so the spot leg
    is never left unhedged. Returns a dict shaped like a market-order result."""
    step = futures_lot["stepSize"]
    min_qty = Decimal(str(futures_lot.get("minQty", "0")))
    slippage = (rules.slippage_pct or Decimal("0.1")) / Decimal("100")

    # fresh ask for accurate limit pricing
    try:
        book = await client.futures_book_ticker(symbol)
        ask = Decimal(str(book.get("askPrice") or book.get("a") or "0"))
    except Exception:
        ask = Decimal("0")
    tick = await client.get_futures_tick_size(symbol)

    tiers = _parse_tiers(rules.tier_ratios)
    if not tiers:
        tiers = [(rules.slippage_pct or Decimal("0.1"), Decimal("100"))]

    fills: list[tuple[Decimal, Decimal]] = []
    filled = Decimal("0")
    price_evidence_complete = True

    if ask > 0:
        for offset_pct, qty_pct in tiers:
            qty_i = round_to_step(total_qty * qty_pct / Decimal("100"), step)
            if qty_i <= 0:
                continue
            # marketable limit: ask uplifted by max(offset, slippage cap)
            uplift = max(offset_pct / Decimal("100"), slippage)
            price = round_to_step(ask * (Decimal("1") + uplift), tick)
            try:
                res = await client.futures_limit_long(
                    symbol,
                    qty_i,
                    price,
                    **_pre_submit_kwargs(pre_submit_guard),
                )
                oid = str(res["orderId"])
                eq, ap = await _poll_fill(client, symbol, oid, LIMIT_WAIT_SEC)
                if eq < qty_i:
                    try:
                        cres = await client.futures_cancel_order(symbol, oid)
                        cres = _normalize_futures_result(cres)
                        _normalized, _status, cancel_eq, cancel_ap = _futures_fill_metrics(cres)
                        eq = cancel_eq if cancel_eq > 0 else eq
                        ap = cancel_ap if cancel_ap > 0 else ap
                    except Exception:
                        pass
                    # 最后一次轮询与撤单生效之间可能有新成交 —— 以订单终态为准,
                    # 否则 filled 低估 → 市价兜底超买 + 回滚平不净(master 共仓残腿)
                    for _ in range(3):
                        try:
                            o = await client.futures_get_order(symbol, oid)
                            o = _normalize_futures_result(o)
                            _normalized, _status, eq, ap = _futures_fill_metrics(o)
                            break
                        except Exception:
                            await asyncio.sleep(0.3)
                if eq > 0:
                    if ap <= RECOVERY_EPSILON:
                        price_evidence_complete = False
                    fills.append((eq, ap)); filled += eq
                    if fill_tracker is not None:
                        fill_tracker["qty"] = filled
                    _log_trade(db, pos.id, sub_account_id, "FUTURES_LIMIT_FILL", symbol, "BUY",
                                eq, ap, oid, "SUCCESS")
            except Exception as e:
                logger.warning(f"Limit tranche failed {symbol} {qty_i}@{price}: {e}")

    # Reconcile to full hedge with a market order (safety invariant).
    remaining = round_to_step(total_qty - filled, step)
    last_id = None
    if remaining >= min_qty and remaining > 0:
        mres = await client.futures_market_long(
            symbol,
            remaining,
            **_pre_submit_kwargs(pre_submit_guard),
        )
        mres = _normalize_futures_result(mres)
        _normalized, _status, meq, map_ = _futures_fill_metrics(mres)
        last_id = str(mres.get("orderId", ""))
        if meq > 0:
            if map_ <= RECOVERY_EPSILON:
                price_evidence_complete = False
            fills.append((meq, map_)); filled += meq
            if fill_tracker is not None:
                fill_tracker["qty"] = filled
            _log_trade(db, pos.id, sub_account_id, "FUTURES_MARKET_FALLBACK", symbol, "BUY",
                        meq, map_, last_id, "SUCCESS")

    avg = (sum(q * p for q, p in fills) / filled) if filled > 0 else Decimal("0")
    return {
        "executedQty": str(filled),
        "avgPrice": str(avg),
        "status": (
            "FILLED"
            if filled + RECOVERY_EPSILON >= total_qty
            and price_evidence_complete
            and avg > RECOVERY_EPSILON
            else ("PARTIALLY_FILLED" if filled > RECOVERY_EPSILON else "NEW")
        ),
        "orderId": last_id or (str(int(pos.id)) if not fills else "limit"),
    }
