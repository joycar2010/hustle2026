import asyncio
import fnmatch
import inspect
import json
import logging
import math
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import redis.asyncio as aioredis

from app.config import settings
from app.db.models import SubAccount, Symbol, SymbolRule, AccountSymbolRule
from app.db.session import SessionLocal
from app.services.pushed_symbols import (
    auto_global_rule_account_field,
    auto_global_rules_key,
    clear_auto_global_rule_account_markers_async,
    custom_monitor_candidate_key,
    custom_monitor_id_from_candidate,
    custom_monitor_source_key,
    is_custom_monitor_candidate,
    manual_push_marker_key,
    mutate_pushed_symbols_async,
)
from app.services.custom_monitor_feed import (
    custom_snapshot_is_fresh,
    load_user_snapshots,
)
from app.services.custom_monitor_push import (
    custom_monitor_block_reason,
    load_active_custom_monitor_infos,
)
from engine.models import Position, EngineState
from engine.config_loader import ConfigLoader
from engine.trading.borrow_coordination import (
    ACCOUNT_OPERATION_LOCK_TTL_SEC,
    AccountOperationLockBusy,
    AccountOperationLockUnavailable,
    account_operation_lock_key,
    borrow_capacity_key,
    borrow_failure_read_keys,
    borrow_lock_key,
    master_symbol_lock,
    no_inventory_key,
    normalize_asset,
)
from engine.trading.inventory_probe import (
    DEFAULT_INVENTORY_PROBE_RATE,
    InventoryProbe,
    InventoryProbeError,
    InventorySnapshot,
    parse_inventory_snapshot,
)
from engine.spread_feed import (
    SpreadFeed,
    SpreadSnapshot,
    is_spread_fresh,
)
from engine.freshness import configured_spread_max_age_ms
from engine.thresholds import (
    downward_reached,
    effective_remove_threshold,
    open_close_conflict,
    upward_reached,
)

logger = logging.getLogger(__name__)

MAX_POSITIONS_PER_ACCOUNT = 10
MAX_PER_SYMBOL = 3
BORROW_LOCK_TTL_SEC = 30
BORROW_LOCK_GRACE_SEC = 120
NO_INVENTORY_TTL_SEC = 1800
BORROW_CAPACITY_TTL_SEC = 300
REPAY_RETRY_COOLDOWN_SEC = 60
STALE_REPAY_RECOVERY_INTERVAL_SEC = 60
AUTO_PUSH_MIN_NOTIONAL_USDT = Decimal("5.5")
AUTO_PUSH_PREFLIGHT_OK_TTL_SEC = 60
AUTO_PUSH_PREFLIGHT_ERROR_TTL_SEC = 120
try:
    # maxBorrowable is a private SAPI endpoint with non-trivial IP weight.
    # A small per-account budget lets candidates make progress without a
    # spread spike causing every worker to fan out across the full market.
    AUTO_PUSH_PREFLIGHT_BUDGET = max(
        1, int(os.getenv("AUTO_PUSH_PREFLIGHT_BUDGET", "2"))
    )
except (TypeError, ValueError):
    AUTO_PUSH_PREFLIGHT_BUDGET = 2
try:
    PUSHED_STALE_EVICT_SEC = max(60, int(os.getenv("PUSHED_STALE_EVICT_SEC", "600")))
except (TypeError, ValueError):
    PUSHED_STALE_EVICT_SEC = 600
# Keep the worker gate configurable, but base it on the same local-receive
# timestamp contract as the Rust publisher.  Exchange event ``ts`` is not a
# liveness signal and must never authorize a new order.
SPREAD_FRESH_MS = configured_spread_max_age_ms()
STALE_PENDING_BORROW_SEC = 120   # stale pending fails; stale submitting becomes outcome-unknown
NAKED_CHECK_INTERVAL = 0.5       # 裸空安全网检查周期(秒):0.5s 准实时发现「孤儿债务」(借币未对冲)
IDLE_GIVEUP_MINUTES = 30         # BORROWED_IDLE 超时放弃:正阈值仓借后超此分钟仍达不到对冲阈值 → 还币止损(负阈值囤券不适用)
AUTO_REMEDIATE = True            # 裸空全自动收口(用户已选):检测+告警+自动买回还币;False=仅检测告警


def _canonical_symbol_key(value: object) -> str:
    """Return the canonical USDT pair key used by market and rule snapshots."""
    asset = normalize_asset(value)
    return f"{asset}USDT" if asset else ""


def _scan_keys(
    redis_client,
    pattern: str,
    *,
    count: int = 128,
    max_keys: int = 4096,
) -> list[str]:
    """Read matching Redis keys incrementally without issuing ``KEYS``.

    ``redis-py`` exposes ``scan_iter`` on current synchronous clients, while
    older clients and small test doubles may expose only the cursor-based
    ``scan`` API.  A final ``keys`` fallback is deliberately limited to
    clients with neither scan API; this keeps legacy mocks working without
    putting the production Redis client on the blocking path.
    """
    collected: list[str] = []
    seen: set[str] = set()

    def add_batch(batch) -> bool:
        for key in batch or ():
            key_text = key.decode() if isinstance(key, bytes) else str(key)
            if not fnmatch.fnmatchcase(key_text, pattern) or key_text in seen:
                continue
            seen.add(key_text)
            collected.append(key_text)
            if max_keys and len(collected) >= max_keys:
                logger.warning("Redis key scan reached %s-key limit for %s", max_keys, pattern)
                return True
        return False

    scan_iter = getattr(redis_client, "scan_iter", None)
    if callable(scan_iter):
        iterator = None
        # Lightweight doubles are not always keyword-compatible with
        # redis-py's scan_iter, so retain the common positional variants.
        for args, kwargs in (
            ((), {"match": pattern, "count": count}),
            ((pattern,), {"count": count}),
            ((), {"match": pattern}),
            ((pattern,), {}),
        ):
            try:
                iterator = scan_iter(*args, **kwargs)
                break
            except TypeError:
                continue
        if iterator is not None:
            add_batch(iterator)
            return collected

    scan = getattr(redis_client, "scan", None)
    if callable(scan):
        cursor = 0
        while True:
            response = None
            for args, kwargs in (
                ((cursor,), {"match": pattern, "count": count}),
                ((), {"cursor": cursor, "match": pattern, "count": count}),
                ((cursor, pattern, count), {}),
            ):
                try:
                    response = scan(*args, **kwargs)
                    break
                except TypeError:
                    continue
            if response is None:
                break
            if isinstance(response, dict):
                next_cursor = response.get("cursor", 0)
                batch = response.get("keys", ())
            else:
                try:
                    next_cursor, batch = response
                except (TypeError, ValueError):
                    break
            if add_batch(batch):
                return collected
            try:
                cursor = int(next_cursor or 0)
            except (TypeError, ValueError):
                break
            if cursor == 0:
                break
        return collected

    # Compatibility-only path for old unit-test doubles. Real redis-py
    # clients always expose scan_iter, so production never reaches KEYS.
    legacy_keys = getattr(redis_client, "keys", None)
    if callable(legacy_keys):
        try:
            add_batch(legacy_keys(pattern))
        except TypeError:
            add_batch(legacy_keys())
    return collected


class Worker:
    def __init__(
        self,
        sub_account_id: int,
        config: ConfigLoader,
        spread_feed: SpreadFeed,
        user_id: int | None = None,
    ):
        self.sub_account_id = sub_account_id
        self.config = config
        self.spread_feed = spread_feed
        self._running = False
        self._repay_ban: dict[str, datetime] = {}
        self._repay_retry_after: dict[int, float] = {}
        self._borrow_only_repay_retry_after: dict[str, float] = {}
        self._last_repay_recovery_at = 0.0
        self._last_transitional_recovery_at = 0.0
        self._last_borrow_at: dict[str, datetime] = {}
        self._cycle_count = 0
        self._trading_client = None
        self._notifier = None
        self._margin_safe = True
        self._symbol_rules: dict[str, dict] = {}
        # Symbols inserted by an automatic push inherit the global rule
        # snapshot until the user explicitly saves a single-symbol/account
        # override.  This set is refreshed from Redis at the start of every
        # decision cycle so all sibling Workers share the same source state.
        self._auto_global_rule_symbols: set[str] = set()
        self._symbol_statuses: dict[str, str] = {}
        self._last_pushed_statuses: dict[str, str] = {}   # 上次已广播的状态快照(变化即发去重用)
        self._glitch_logged: dict[str, datetime] = {}
        self._symbol_volumes: dict[str, float] = {}   # symbol -> 现货24h成交量(USDT),交易护栏用
        self._symbol_futures_volumes: dict[str, float] = {}   # symbol -> 合约24h成交量(USDT),双腿量过滤用
        self._above_since: dict[str, datetime] = {}   # symbol -> 点差首次超借币阈时间(filter_duration_ms 防抖)
        self._removed_ban: dict[str, datetime] = {}   # symbol -> 退出时间(removed_cooldown_minutes 再借冷却)
        self._shared_removed_bans: set[str] = set()
        # Account ownership is needed before the first DB lookup in run().
        self._user_id: int | None = user_id
        self._account_max_borrow: Decimal | None = None
        self._account_max_positions: int | None = None
        self._account_borrow_rate: Decimal | None = None
        self._account_inventory_probe_rate: Decimal | None = None
        self._account_opening_enabled = True
        self._account_enabled_checked_at = 0.0
        self._execution_preflight_probes = 0
        self._redis: aioredis.Redis | None = None
        # Website maintenance pauses admission only.  Exit/repay paths below
        # deliberately continue while this flag is true.
        self._maintenance_blocks_new = False
        self._inventory_probe: InventoryProbe | None = None
        self._inventory_probe_task: asyncio.Task | None = None
        self._inventory_candidates: frozenset[str] = frozenset()
        # Candidate snapshots are consumed by the dashboard health endpoint.
        # Keep a generation so a failed Redis publish is retried on the next
        # cycle instead of silently leaving the previous denominator visible.
        self._inventory_candidates_generation = 0
        self._inventory_candidates_published_generation = -1
        self._inventory_positive_assets: frozenset[str] = frozenset()
        self._inventory_snapshot: InventorySnapshot | None = None
        self._inventory_candidates_event = asyncio.Event()
        self._inventory_ready_event = asyncio.Event()
        # A committed rule event wakes the decision loop immediately. The
        # one-second cadence remains the fallback when pub/sub is unavailable.
        self._rules_reload_event = asyncio.Event()
        # Pushed-list mutations are also edge-triggered.  Wake the cycle so
        # the candidate reconciliation can publish the new denominator without
        # waiting for the normal one-second cadence.
        self._pushed_symbols_event = asyncio.Event()
        self._pushed_symbols_task: asyncio.Task | None = None
        self._rules_state_lock = asyncio.Lock()
        self._rules_generation = 0
        self._startup_complete = False

    @staticmethod
    def _lifecycle_error(exc: BaseException, phase: str) -> str:
        """Return a bounded, single-line diagnostic safe for EngineState."""
        detail = " ".join(str(exc or "").split())
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
            f"worker {phase} failed ({type(exc).__name__})"
            + (f": {detail}" if detail else "")
        )

    async def _safe_update_state(self, status: str, error: str | None = None) -> None:
        """Persist a terminal state without masking the lifecycle failure."""
        try:
            result = self._update_state(status, error)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error(
                "Unable to persist %s state for sub-account %s",
                status,
                self.sub_account_id,
                exc_info=True,
            )

    async def _cleanup_runtime_resources(self) -> None:
        """Cancel listener tasks and close this worker's Redis client."""
        tasks = []
        for attr in (
            "_rules_reload_task",
            "_pushed_symbols_task",
            "_naked_guard_task",
            "_inventory_probe_task",
        ):
            task = getattr(self, attr, None)
            if task is not None:
                tasks.append(task)
                done = getattr(task, "done", None)
                is_done = bool(done()) if callable(done) else False
                cancel = getattr(task, "cancel", None)
                if not is_done and callable(cancel):
                    cancel()
                setattr(self, attr, None)
        awaitables = [task for task in tasks if inspect.isawaitable(task)]
        if awaitables:
            await asyncio.gather(*awaitables, return_exceptions=True)

        # ``BinanceTradingClient`` owns an httpx client that is normally
        # closed by its async context manager.  A failure while entering that
        # context can leave the underlying client allocated, so close it as a
        # best effort during startup/error cleanup as well.  httpx close is
        # idempotent after the normal context exit.
        trading_client = self._trading_client
        http_client = getattr(trading_client, "_client", None) if trading_client else None
        close_http = getattr(http_client, "aclose", None) if http_client else None
        if callable(close_http):
            try:
                result = close_http()
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Unable to close HTTP client for sub-account %s",
                    self.sub_account_id,
                    exc_info=True,
                )

        redis_client = self._redis
        self._redis = None
        close = getattr(redis_client, "aclose", None) if redis_client else None
        if callable(close):
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Unable to close Redis client for sub-account %s",
                    self.sub_account_id,
                    exc_info=True,
                )

    async def run(self):
        """Run the worker behind a lifecycle-safe startup boundary."""
        self._startup_complete = False
        self._running = True
        try:
            result = await self._run_impl()
            if not self._startup_complete:
                # ``_run_impl`` historically returned quietly when the
                # account disappeared.  Treat that as a terminal startup
                # failure so STARTING/RUNNING rows cannot outlive the worker.
                message = f"sub-account {self.sub_account_id} not found"
                self._running = False
                await self._safe_update_state("ERROR", message)
            return result
        except asyncio.CancelledError:
            self._running = False
            await self._safe_update_state("STOPPED")
            await self._cleanup_runtime_resources()
            raise
        except Exception as exc:  # noqa: BLE001 - worker lifecycle boundary
            self._running = False
            phase = "initialization" if not self._startup_complete else "runtime"
            await self._safe_update_state(
                "ERROR",
                self._lifecycle_error(exc, phase),
            )
            await self._cleanup_runtime_resources()
            raise
        finally:
            self._running = False
            # The implementation owns the trading-context cleanup.  This
            # closes Redis and also handles startup failures that never reach
            # its inner ``try/finally``.
            await self._cleanup_runtime_resources()

    async def _run_impl(self):
        self._running = True
        account_info = await asyncio.to_thread(self._load_account)
        if not account_info:
            logger.error(f"Sub-account {self.sub_account_id} not found")
            return

        account_note = account_info["note"]
        self._user_id = account_info.get("user_id")
        self._account_max_borrow = account_info.get("max_borrow_amount")
        self._account_max_positions = account_info.get("max_positions")
        self._account_borrow_rate = account_info.get("borrow_rate_per_sec")
        self._account_inventory_probe_rate = account_info.get(
            "inventory_probe_rate_per_sec"
        )
        self._account_opening_enabled = bool(account_info.get("is_enabled", True))
        self._account_enabled_checked_at = time.monotonic()
        logger.info(f"Worker started for sub-account {self.sub_account_id} ({account_note})")

        await asyncio.to_thread(self._load_symbol_rules)

        from engine.trading.binance_trading import BinanceTradingClient
        self._trading_client = BinanceTradingClient(
            account_info["api_key"], account_info["api_secret"],
            sub_account_id=self.sub_account_id,
        )
        configured_probe_rate = (
            self._account_inventory_probe_rate
            if self._account_inventory_probe_rate is not None
            else getattr(
                self.config.global_rules,
                "inventory_probe_rate_per_sec",
                DEFAULT_INVENTORY_PROBE_RATE,
            )
        )
        try:
            self._inventory_probe = InventoryProbe(
                self._trading_client,
                account_id=self.sub_account_id,
                rate_per_sec=configured_probe_rate,
                wake_event=self._inventory_candidates_event,
            )
        except ValueError:
            logger.error(
                "Invalid initial inventory probe rate for account %s: %r; using %.1f/s",
                self.sub_account_id,
                configured_probe_rate,
                DEFAULT_INVENTORY_PROBE_RATE,
            )
            self._inventory_probe = InventoryProbe(
                self._trading_client,
                account_id=self.sub_account_id,
                rate_per_sec=DEFAULT_INVENTORY_PROBE_RATE,
                wake_event=self._inventory_candidates_event,
            )

        from engine.notify.feishu_sender import FeishuSender
        self._notifier = FeishuSender()
        self._notifier.user_id = self._user_id   # 飞书机器人告警按本 user 的 feishu_open_id 路由

        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)

        # 事件驱动 0 秒规则热重载:订阅 Redis 频道 rules:reload:{user_id},
        # /dashboard 保存逐币/逐账户挂单点差的 API publish 后,本协程立即 _load_symbol_rules,
        # 不必等主循环 3s 轮询 → 保存即生效、立刻按新阈值借币。3s 轮询保留作兜底。
        self._rules_reload_task = asyncio.create_task(self._rules_reload_listener())
        self._pushed_symbols_task = asyncio.create_task(
            self._pushed_symbols_listener()
        )

        # 裸空/单腿安全网:0.5s 周期对账币安真实债务,发现「孤儿债务」(借币未对冲、现货已卖/合约未开)
        # 即告警(跑马灯+飞书)+ 自动买回还币收口。独立兜底协程,不碰主交易路径。
        # 见 engine/fund/reconcile_checker.py;根因背景=hustle-011 裸空事故。
        self._naked_guard_task = asyncio.create_task(self._naked_short_loop(account_note))

        await self._update_state("RUNNING")

        tradable_symbols = await asyncio.to_thread(self._load_tradable_symbols)
        last_bnb_check = 0
        last_debt_check = 0
        last_risk_check = 0
        last_health_check = 0
        last_funding_check = 0
        last_borrow_scan = 0
        last_clock_check = 0
        last_inspection = 0
        last_futmargin_check = 0
        last_balance_check = 0
        last_debtconv_check = 0
        last_masterfund_check = 0
        last_rule_reload = 0
        final_status = "STOPPED"
        self._startup_complete = True

        try:
            async with self._trading_client:
                if getattr(self.config.global_rules, "hedge_via_master", False):
                    # Validate the master futures leg before allowing any
                    # sub-account borrow/spot action.  A dual-mode or missing
                    # master must never leave a naked margin short.
                    from engine.trading.master_client import get_master_futures_client
                    master_client = await get_master_futures_client(self._user_id)
                    if master_client is None:
                        mode_error = (
                            "主账户合约对冲不可用：未配置、API 不可用或仍为双向持仓；"
                            "已阻止子账户借币，请将主账户 linxiaoyun2026@gmail.com 切换为单向持仓后重试"
                        )
                        logger.error("Worker %s blocked: %s", self.sub_account_id, mode_error)
                        final_status = "ERROR"
                        await self._update_state("ERROR", mode_error)
                        return
                self._inventory_probe_task = asyncio.create_task(
                    self._inventory_probe_loop()
                )
                while self._running:
                    await self._cycle(tradable_symbols, account_note)
                    self._cycle_count += 1
                    if self._cycle_count % 300 == 0:
                        tradable_symbols = await asyncio.to_thread(self._load_tradable_symbols)

                    # periodic fund tasks
                    now = asyncio.get_event_loop().time()
                    fund_rules = self.config.fund_rules

                    # 单一规则热重载(每 3s):用户在 /dashboard 保存逐币/逐账户挂单点差(borrow_spread=-1 等)
                    # 后,引擎须尽快读到才会按新阈值借币。轻量(两条按 user/account 过滤的 DB 查询),
                    # 与 _load_tradable_symbols(全市场重查,仍每 300 周期)解耦,避免保存后等几分钟才借币。
                    if now - last_rule_reload > 3:
                        await self._reload_rule_snapshots(fence_current_cycle=False)
                        last_rule_reload = now

                    if now - last_risk_check > 30:
                        from engine.fund.risk_monitor import check_margin_risk
                        self._margin_safe = await check_margin_risk(
                            self._trading_client, fund_rules, self._notifier, account_note,
                            sub_account_id=self.sub_account_id,
                        )
                        last_risk_check = now

                    if now - last_futmargin_check > 30:
                        await self._check_futures_margin(account_note)
                        last_futmargin_check = now

                    # 主→子 保证金自动平衡(仅 hedge_via_master;子账户设了单笔划才动钱)
                    if now - last_balance_check > 30 and getattr(self.config.global_rules, "hedge_via_master", False):
                        from engine.fund.margin_balancer import auto_balance_margin
                        _open = await asyncio.to_thread(self._load_open_positions)
                        await auto_balance_margin(
                            self._trading_client, self.sub_account_id, self._user_id,
                            fund_rules, self._notifier, account_note, bool(_open),
                        )
                        last_balance_check = now

                    if now - last_bnb_check > fund_rules.bnb_convert_interval_sec:
                        from engine.fund.bnb_manager import run_bnb_check
                        await run_bnb_check(
                            self._trading_client, fund_rules, self._notifier, account_note,
                            bnb_burn_enabled=getattr(self.config.global_rules, "bnb_burn_enabled", None),
                        )
                        last_bnb_check = now

                    if now - last_debt_check > fund_rules.usdt_debt_interval_sec:
                        from engine.fund.debt_repayer import run_usdt_debt_check
                        await run_usdt_debt_check(self._trading_client, fund_rules, self._notifier, account_note)
                        last_debt_check = now

                    if now - last_debtconv_check > fund_rules.debt_convert_interval_sec:
                        from engine.fund.debt_converter import run_debt_convert
                        await run_debt_convert(self._trading_client, self.sub_account_id,
                                               self.spread_feed, self._notifier, account_note)
                        last_debtconv_check = now

                    # 主账户资金纳管(hedge_via_master):BNB维护/USDT欠款/小额兑换也覆盖主账户。
                    # Redis 锁保证每 user 每周期只一个 worker 真正执行(防 5 worker 重复打主账户)。
                    if (now - last_masterfund_check > fund_rules.bnb_convert_interval_sec
                            and getattr(self.config.global_rules, "hedge_via_master", False)):
                        from engine.fund.master_fund import run_master_fund_check
                        await run_master_fund_check(
                            self._user_id, self._redis, fund_rules,
                            self.config.global_rules, self._notifier,
                            ttl_sec=fund_rules.bnb_convert_interval_sec,
                        )
                        last_masterfund_check = now

                    if now - last_health_check > 300:
                        from engine.fund.health_monitor import run_health_check
                        await run_health_check(self._notifier)
                        last_health_check = now

                    if now - last_clock_check > 300:
                        from engine.fund.clock_monitor import run_clock_check
                        await run_clock_check(self._notifier, self._redis)
                        last_clock_check = now

                    if now - last_inspection > 1800:   # 抗延迟巡检每 30min(redis 锁内部去重)
                        from engine.fund.inspection import run_inspection
                        await run_inspection(self._redis, self._notifier)
                        last_inspection = now

                    if now - last_funding_check > 1800:
                        from engine.fund.funding_collector import collect_funding_fees
                        await collect_funding_fees(self._trading_client, self.sub_account_id,
                                                   user_id=self._user_id)
                        last_funding_check = now

                    # C5: scan for manually borrowed assets every 60 seconds
                    if now - last_borrow_scan > 60:
                        from engine.fund.borrow_scanner import scan_manual_borrows
                        pushed = set(tradable_symbols)
                        open_positions = await asyncio.to_thread(self._load_open_positions)
                        pushed.update(p.symbol for p in open_positions)
                        new_borrows = await scan_manual_borrows(
                            self._trading_client, self.sub_account_id, self._user_id, pushed,
                        )
                        if new_borrows:
                            await self._reload_rule_snapshots(fence_current_cycle=False)
                            logger.info(f"Borrow scan found {len(new_borrows)} new symbols: {new_borrows}")
                        last_borrow_scan = now

                    await self._wait_for_next_cycle()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Worker {self.sub_account_id} error: {e}", exc_info=True)
            final_status = "ERROR"
            await self._update_state("ERROR", str(e))
            raise
        finally:
            t = getattr(self, "_rules_reload_task", None)
            if t:
                t.cancel()
            pushed_task = getattr(self, "_pushed_symbols_task", None)
            if pushed_task:
                pushed_task.cancel()
            ng = getattr(self, "_naked_guard_task", None)
            if ng:
                ng.cancel()
            inventory_task = self._inventory_probe_task
            if inventory_task:
                inventory_task.cancel()
                await asyncio.gather(inventory_task, return_exceptions=True)
                self._inventory_probe_task = None
            # Preserve a terminal configuration/runtime error.  The previous
            # unconditional STOPPED write hid the actual cause immediately
            # after the master hedge precheck or an unexpected worker error.
            if final_status == "STOPPED":
                await self._update_state("STOPPED")
            logger.info(f"Worker stopped for sub-account {self.sub_account_id}")

    async def stop(self):
        self._running = False
        self._inventory_candidates_event.set()
        self._inventory_ready_event.set()

    async def _cycle(self, tradable_symbols: set[str], account_note: str):
        # Do not start a new decision snapshot while the listener is replacing
        # its global and account-symbol rule layers.
        async with self._rules_state_lock:
            rules = self.config.global_rules
            blacklist = self.config.blacklist
            rules_generation = self._rules_generation
        # A clear request disables the account while retaining this worker for
        # close/repay. Refresh the DB flag periodically so a command cannot
        # race a borrow decision for more than a few seconds. The same poll
        # refreshes fund limits because that API does not publish rules:reload.
        now_mono = time.monotonic()
        await self._refresh_account_runtime(now_mono)
        try:
            from engine.maintenance_gate import maintenance_blocks_new_async
            self._maintenance_blocks_new = await maintenance_blocks_new_async(self._redis)
        except Exception:
            # A gate read failure is conservative once a Redis client exists;
            # unit-test workers without Redis retain the legacy open behaviour.
            self._maintenance_blocks_new = bool(self._redis)
        # Apply per-account borrow pacing: account override else global (live-updates)
        from engine.trading.binance_trading import set_borrow_rate
        eff_rate = self._account_borrow_rate if self._account_borrow_rate else getattr(rules, "borrow_rate_per_sec", Decimal("3.9"))
        set_borrow_rate(self.sub_account_id, eff_rate)
        if self._inventory_probe is not None:
            configured_probe_rate = (
                self._account_inventory_probe_rate
                if self._account_inventory_probe_rate is not None
                else getattr(
                    rules,
                    "inventory_probe_rate_per_sec",
                    DEFAULT_INVENTORY_PROBE_RATE,
                )
            )
            try:
                self._inventory_probe.set_rate(configured_probe_rate)
            except ValueError:
                logger.error(
                    "Invalid inventory probe rate for account %s: %r",
                    self.sub_account_id,
                    configured_probe_rate,
                )

        # Recover stale pre-submit rows and quarantine interrupted submissions.
        # 会让下方借币循环误判该币在途而永不重借(根因②脆弱点)。须在加载 positions/statuses 之前。
        await asyncio.to_thread(self._reclaim_stale_pending_borrow)

        # A process can die after execute_repay's REPAYING claim and before
        # its exception handler restores PENDING_REPAY.  Retry that state only
        # through the locked, exchange-flat recovery helper; never blindly
        # rewrite every REPAYING row in the hot loop.
        if now_mono - self._last_repay_recovery_at >= STALE_REPAY_RECOVERY_INTERVAL_SEC:
            await self._recover_stale_repaying()
            self._last_repay_recovery_at = now_mono

        # A restart can strand a row between the lifecycle CAS and an
        # exchange request (HEDGING/CLOSING_*).  Recover only after the lock
        # expiry window; the helper performs authoritative REST safety reads
        # and leaves ambiguous rows untouched.
        if now_mono - self._last_transitional_recovery_at >= STALE_REPAY_RECOVERY_INTERVAL_SEC:
            await self._recover_stale_transitional_positions(account_note)
            self._last_transitional_recovery_at = now_mono

        open_positions = await asyncio.to_thread(self._load_open_positions)
        idle_positions = await asyncio.to_thread(self._load_positions_by_status, "BORROWED_IDLE")
        pending_repay = await asyncio.to_thread(self._load_positions_by_status, "PENDING_REPAY")
        pushed = {
            str(symbol).strip().upper()
            for symbol in await asyncio.to_thread(self._load_pushed_symbols)
            if str(symbol).strip() and not is_custom_monitor_candidate(symbol)
        }
        # The dashboard pause set is a tenant-scoped borrow-admission control.
        # An unavailable read blocks inventory polling, first borrow, and
        # BORROWED_IDLE top-up, but an amount that is already borrowed must
        # still reach its hedge/close/repay lifecycle.
        paused_symbols = await asyncio.to_thread(self._load_paused_symbols)
        pause_gate_unavailable = paused_symbols is None
        if paused_symbols is None:
            paused_symbols = set()
        await self._refresh_auto_global_rule_symbols(pushed)

        open_symbol_counts: dict[str, int] = {}
        repayable_symbols: set[str] = set()
        for p in open_positions:
            open_symbol_counts[p.symbol] = open_symbol_counts.get(p.symbol, 0) + 1
            if self._is_repay_allowed(p.symbol):
                repayable_symbols.add(p.symbol)
        # symbols already in-flight (any active state) — do not re-borrow
        active_symbols = ({p.symbol for p in open_positions} |
                          {p.symbol for p in idle_positions} |
                          {p.symbol for p in pending_repay})
        # Capacity accounting includes both hedged and idle debt.  An idle row
        # is topped up in place before it is hedged; an already hedged OPEN row
        # owns the sole lifecycle slot and never receives a second tranche.
        # Transitional/closing rows remain exclusive.
        additive_positions = open_positions + idle_positions
        idle_symbols = {p.symbol for p in idle_positions}
        statuses: dict[str, str] = {}
        for pos in open_positions:
            sym = pos.symbol
            if sym in statuses:
                continue
            if not self._is_repay_allowed(sym):
                statuses[sym] = "还币暂停"
            elif self._is_repay_banned(pos):
                statuses[sym] = "还币冷却"
            else:
                sp = self.spread_feed.get_symbol(sym)
                if sp and downward_reached(sp.spread_short, self._sym_threshold(sym, "close_spread", rules.close_spread)):
                    statuses[sym] = "还币中"
                else:
                    statuses[sym] = "点差不符"
        # P1: overlay in-flight execution states (排队中/待对冲/开仓中/待还币...)
        active = await asyncio.to_thread(self._load_active_statuses)
        for sym, label in active.items():
            if label:
                statuses[sym] = label

        # ``available-inventory`` returns one full account snapshot, but its
        # logical members are only symbols that can reach the inventory gate
        # in this cycle. A low-spread/disabled/untradable pushed symbol must
        # neither keep the GET loop alive nor dilute the displayed per-symbol
        # cadence. Existing no-inventory markers deliberately do not suppress
        # polling, because a later positive snapshot is what clears them.
        topup_mode = getattr(rules, "borrow_mode", None) or (
            "otoco" if getattr(rules, "borrow_via_otoco", False) else "repay"
        )
        topup_path_enabled = topup_mode in ("single", "multi", "otoco", "repay")
        inventory_sources = self._inventory_source_symbols(
            pushed,
            open_positions,
            idle_positions,
            pending_repay,
            active,
            topup_path_enabled=topup_path_enabled,
        )
        eligible_inventory = set()
        if not pause_gate_unavailable and not self._maintenance_blocks_new:
            eligible_inventory = self._eligible_inventory_candidates(
                inventory_sources,
                tradable_symbols=tradable_symbols,
                blacklist=blacklist,
                rules=rules,
                paused_symbols=paused_symbols,
            )
        candidates_changed = self._set_inventory_candidates(eligible_inventory)
        # Publish the candidate denominator immediately after it changes.
        # Waiting for the end-of-cycle status publication made a pushed/removed
        # symbol appear in the health rate for up to the polling interval (and
        # could be much longer while a cycle was busy with exchange calls).
        if (
            candidates_changed
            or self._inventory_candidates_published_generation
            != self._inventory_candidates_generation
        ):
            await self._publish_inventory_candidates()
        # 注:挂单中(未持仓)币种的逐账户状态在下方借币循环里补入 statuses,
        # 之后统一赋给 self._symbol_statuses 并发布(见借币循环末尾)。

        # ── UNHEDGE: OPEN → PENDING_REPAY at close_spread (or funding ratio) ──
        for pos in open_positions:
            spread = self.spread_feed.get_symbol(pos.symbol)
            if not self._spread_sane(spread):            # 行情 glitch 护栏(PnL 也需 sane 价)
                continue
            # ── STOP-LOSS: 单仓最大亏损 — 盯市浮亏达上限即强制平仓(优先于点差/资费/冷却)──
            max_loss = getattr(rules, "max_loss_per_position", None)
            if max_loss is not None and max_loss > 0:
                upnl = self._position_unrealized_pnl(pos, spread)
                if upnl is not None and upnl <= -Decimal(str(max_loss)):
                    logger.warning(f"Stop-loss {pos.symbol}#{pos.id}: 浮亏 {upnl:.2f} <= -{max_loss} USDT, 强制平仓")
                    try:
                        await self._notifier.notify_error(
                            account_note, f"止损 {pos.symbol}",
                            f"单仓浮亏 {upnl:.2f} USDT 触及上限 -{max_loss},强制平仓(合约平+现货买回,余下按还币规则)",
                        )
                    except Exception:
                        pass
                    # Stop-loss is risk reducing.  It may use a market exit
                    # even when the cached quote has just gone stale; the
                    # executor still keeps maker exits behind the freshness
                    # gate.
                    unhedged = await self._unhedge_position(
                        pos,
                        spread,
                        account_note,
                        emergency=True,
                        expected_rules_generation=rules_generation,
                    )
                    # ``_unhedge_position`` releases its account-operation
                    # lock before returning.  Repay immediately after a
                    # confirmed close so a newly-created PENDING_REPAY row
                    # does not wait for the next cycle (or the post-close
                    # borrow cooldown).  Only the literal success value may
                    # trigger this risk-reducing follow-up; test doubles and
                    # ambiguous failures must retain the normal retry path.
                    if unhedged is True and self._repay_is_immediate(pos.symbol, rules):
                        await self._repay_position(
                            pos,
                            account_note,
                            expected_rules_generation=None,
                        )
                    continue
            # Ordinary spread/funding closes and maker pricing remain gated by
            # both local WS receive timestamps.
            if not self._spread_fresh(spread):
                statuses[pos.symbol] = "行情陈旧"
                continue
            if not self._is_repay_allowed(pos.symbol):   # C3
                continue
            # ``repay_ban_minutes`` is a post-close/reborrow cooldown. It
            # must never block a risk-reducing close of an already OPEN row:
            # a position can reach its close spread during the configured
            # hold window (the former gate left FIL and similar rows stuck
            # until the cooldown expired). Keep the cooldown in the opening
            # admission path and retain the status label above for visibility.
            close_sp = self._sym_threshold(pos.symbol, "close_spread", rules.close_spread)
            if downward_reached(spread.spread_short, close_sp):
                if not self._rules_are_current(rules_generation):
                    return
                unhedged = await self._unhedge_position(
                    pos,
                    spread,
                    account_note,
                    expected_rules_generation=rules_generation,
                )
                if unhedged is True and self._repay_is_immediate(pos.symbol, rules):
                    await self._repay_position(
                        pos,
                        account_note,
                        expected_rules_generation=rules_generation,
                    )
                continue
            close_fr = self._sym_threshold(pos.symbol, "close_funding_ratio", rules.close_funding_ratio)
            if getattr(pos, 'funding_rate_ratio', None) is not None and \
               close_fr > 0 and pos.funding_rate_ratio >= close_fr:
                logger.info(f"Unhedge {pos.symbol}: funding ratio {pos.funding_rate_ratio} >= {close_fr}")
                if not self._rules_are_current(rules_generation):
                    return
                unhedged = await self._unhedge_position(
                    pos,
                    spread,
                    account_note,
                    expected_rules_generation=rules_generation,
                )
                if unhedged is True and self._repay_is_immediate(pos.symbol, rules):
                    await self._repay_position(
                        pos,
                        account_note,
                        expected_rules_generation=rules_generation,
                    )

        # ── REPAY: PENDING_REPAY → CLOSED ──
        # PENDING_REPAY 已彻底去对冲(现货已买回+合约已平,借来的币在手),还币只是把持有的币还回 margin。
        # 未配 repay_spread → 立即还:持币不还只会累积借币利息+拖低 marginLevel,无任何延迟收益。
        # 历史坑:用 repay_funding_ratio 闸还币 —— 去对冲后的仓位 funding 已无意义、几乎永不达标,会把
        # 已平仓位永久钉在 PENDING_REPAY(实测 FIL 卡 2.5h 把 ml 拖到 1.36)。故无 repay_spread 即不看 funding 直接还;
        # 仅当显式配了 repay_spread 时才保留「挑点差/ funding 再还」的优化语义。
        g_repay_spread = getattr(rules, "repay_spread", None)
        g_repay_fr = getattr(rules, "repay_funding_ratio", None)
        for pos in pending_repay:
            if not self._repay_retry_ready(pos.id):
                continue
            if not self._is_repay_allowed(pos.symbol):
                continue
            # 逐币/逐账户覆盖(空=回退全局)
            repay_spread = self._sym_threshold(pos.symbol, "repay_spread", g_repay_spread)
            if repay_spread is None or repay_spread <= 0:
                if not self._rules_are_current(rules_generation):
                    return
                await self._repay_position(
                    pos,
                    account_note,
                    expected_rules_generation=rules_generation,
                )   # 无阈值 → 立即还(不看点差/funding)
                continue
            spread = self.spread_feed.get_symbol(pos.symbol)
            if spread is not None and not self._spread_sane(spread):  # glitch → 本轮不还
                continue
            spread_fresh = self._spread_fresh(spread)
            repay_fr = self._sym_threshold(pos.symbol, "repay_funding_ratio", g_repay_fr)
            do_repay = False
            # A configured repay-spread trigger is quote-dependent and must
            # fail closed on stale data. Funding-only repayment remains
            # allowed, and the no-spread branch above stays immediate because
            # debt cleanup is risk-reducing and needs no market quote.
            if spread and spread_fresh and downward_reached(spread.spread_short, repay_spread):
                do_repay = True
            elif repay_fr is not None and repay_fr > 0 and getattr(pos, 'funding_rate_ratio', None) is not None \
                    and pos.funding_rate_ratio >= repay_fr:
                do_repay = True
            if do_repay:
                if not self._rules_are_current(rules_generation):
                    return
                await self._repay_position(
                    pos,
                    account_note,
                    expected_rules_generation=rules_generation,
                )

        # C6: auto-repay for borrow-only (scan) assets with no open position
        for sym, rule in self._symbol_rules.items():
            if rule.get("source") != "scan":
                continue
            if not rule.get("allow_repay", True):
                continue
            # A scan rule may coexist with a managed lifecycle row.  Only a
            # truly unowned balance is eligible for the borrow-only cleanup;
            # BORROWED_IDLE must be allowed to reach the hedge phase first.
            # Checking only OPEN here previously repaid a freshly borrowed
            # FIL/other canary row before its negative open threshold could be
            # evaluated.
            if sym in active_symbols or sym in active:
                continue
            if not self._borrow_only_repay_retry_ready(sym):
                continue
            spread = self.spread_feed.get_symbol(sym)
            if not self._spread_sane(spread):
                continue
            if not self._spread_fresh(spread):
                continue
            if downward_reached(spread.spread_short, self._sym_threshold(sym, "close_spread", rules.close_spread)):
                if not self._rules_are_current(rules_generation):
                    return
                await self._borrow_only_repay(
                    sym,
                    account_note,
                    expected_rules_generation=rules_generation,
                )

        # Fill the one BORROWED_IDLE row before evaluating its open line. If
        # hedging runs first, a 36.8U row becomes OPEN and a later cap tail can
        # only be represented by an unsafe duplicate Position.
        if (
            self._running
            and self._account_opening_enabled
            and self._margin_safe
            and self._trading_client is not None
            and self._redis is not None
            and topup_path_enabled
            and not self._maintenance_blocks_new
            and not (
                self._account_max_borrow is not None
                and self._account_max_borrow == 0
            )
        ):
            topup_global = getattr(rules, "borrow_spread", rules.open_spread)
            topup_buffer = float(getattr(rules, "open_spread_buffer", 0) or 0)
            for idle in idle_positions:
                symbol = str(getattr(idle, "symbol", "") or "").upper()
                if not symbol:
                    continue
                if pause_gate_unavailable or symbol in paused_symbols:
                    statuses[symbol] = "挂单已暂停" if not pause_gate_unavailable else "协调不可用"
                    continue
                account_rule = self._symbol_rule_for_execution(symbol)
                if account_rule.get("account_enabled") is False:
                    continue
                if not self._inventory_allows(symbol):
                    continue
                try:
                    if await self._redis.get(self._capacity_redis_key(symbol)):
                        continue
                except Exception:
                    continue
                cooldown = await self._borrow_cooldown_state(symbol)
                if cooldown is not False:
                    continue
                if await self._borrow_failure_state(symbol) is not False:
                    continue
                quote = self.spread_feed.get_symbol(symbol)
                if not self._spread_sane(quote) or not self._spread_fresh(quote):
                    continue
                effective = self._sym_threshold(
                    symbol, "borrow_spread", topup_global
                )
                try:
                    effective = float(effective) + topup_buffer
                except (TypeError, ValueError):
                    continue
                if not self._has_incremental_borrow_room(
                    symbol,
                    quote,
                    additive_positions,
                    allow_cap_tail=True,
                ):
                    continue
                if not self._spread_persisted(
                    symbol, float(quote.spread_short), effective
                ):
                    continue
                if not self._rules_are_current(rules_generation):
                    return
                await self._topup_borrow(
                    idle,
                    quote,
                    account_note,
                    expected_rules_generation=rules_generation,
                )

        global_max = rules.max_positions or MAX_POSITIONS_PER_ACCOUNT
        max_positions = self._account_max_positions if self._account_max_positions is not None else global_max

        # ── HEDGE: BORROWED_IDLE → OPEN at open_spread ──
        # ``max_positions`` is a distinct-symbol slot limit. The idle row
        # already owns its slot, including when an older tranche is OPEN.
        open_slot_symbols = {p.symbol for p in open_positions}
        for pos in idle_positions:
            if not self._running:
                break
            # A genuinely new idle symbol must still respect the slot limit.
            if (
                pos.symbol not in open_slot_symbols
                and len(open_slot_symbols) >= max_positions
            ):
                continue
            spread = self.spread_feed.get_symbol(pos.symbol)
            if not self._spread_sane(spread):            # glitch → 不在坏点差上对冲开仓
                continue
            if not self._spread_fresh(spread):
                continue
            # The borrow line intentionally does not depend on this check.
            # Once a coin is borrowed, however, an inverted/equal open and
            # close line would immediately satisfy both lifecycle gates and
            # can churn the position.  Hold the borrowed asset until the
            # operator fixes that configuration, then resume the hedge.
            _open_th = self._sym_threshold(pos.symbol, "open_spread", rules.open_spread)
            _close_th = self._sym_threshold(pos.symbol, "close_spread", rules.close_spread)
            # A negative opening line is an explicit force-open/canary input.
            # Keep rejecting accidental non-negative inverted lines, but do
            # not silently strand an already borrowed canary position merely
            # because its close line is above -1. repay_ban still prevents an
            # immediate close/reopen loop after the forced hedge.
            force_open = False
            try:
                force_open = Decimal(str(_open_th)) < 0
            except (TypeError, ValueError):
                pass
            if not force_open and open_close_conflict(_open_th, _close_th):
                statuses[pos.symbol] = "配置冲突"
                continue
            if upward_reached(spread.spread_short, _open_th):
                if not self._rules_are_current(rules_generation):
                    return
                await self._hedge_position(
                    pos,
                    spread,
                    account_note,
                    expected_rules_generation=rules_generation,
                )
                open_positions = await asyncio.to_thread(self._load_open_positions)
                open_slot_symbols = {p.symbol for p in open_positions}
                continue
            # 超时放弃:状态机原本 BORROWED_IDLE 唯一出路是对冲,点差借完回落就永久卡住白付利息
            # +dashboard 挂"现-期残留"(实测 FIL 借后 open 阈值够不着卡 15min+)。正阈值(非囤券)的
            # idle 仓超时未能对冲 → 放弃还币止损。负阈值=故意囤券持币等点差,不适用超时。
            if not self._rules_are_current(rules_generation):
                return
            await self._maybe_giveup_idle(
                pos, rules, expected_rules_generation=rules_generation
            )

        # ── BORROW: pushed ∩ tradable, spread >= borrow_spread → execute_borrow (idle) ──
        # 同时为挂单中(未持仓)的每个推送币算逐账户状态写入 statuses(点差不符/无券/量不足/冷却…),
        # 让前端子账户行能显示状态(与参照系统一致)。本 worker = 一个子账户,天然 per-account。
        # Hedge/unhedge above can change a row after the cycle's initial
        # status snapshot. Refresh before deciding whether an existing symbol
        # may receive another bite; a same-cycle PENDING_REPAY must win.
        active = await asyncio.to_thread(self._load_active_statuses)
        # Position slots are counted by distinct symbol.  A symbol with an
        # existing OPEN row is already owned by its single lifecycle record;
        # it must never enter the legacy separate-tranche borrow path.
        active_slot_symbols = {p.symbol for p in open_positions + idle_positions}
        active_count = len(active_slot_symbols)
        # Manual and early-borrow candidates bypass auto-push discovery, so
        # they need the same private maxBorrowable preflight here. Keep one
        # shared budget for the whole account cycle to avoid a large pushed
        # list fanning out into unbounded private SAPI requests.
        self._execution_preflight_probes = 0
        # Coin owns its opening gate.  Do not consult the old C3 control plane:
        # a missing/disabled external key used to stop every Coin borrow and
        # relabel otherwise healthy rows as "new engine takeover".
        g_borrow_spread = getattr(rules, "borrow_spread", rules.open_spread)   # 全局挂单点差回退值
        # 开仓阈值缓冲: 实际要求点差 ≥ 挂单点差 + buffer,吸收腿间滑点/~160ms借币延迟(0=不留)
        borrow_buffer = float(getattr(rules, "open_spread_buffer", 0) or 0)
        # The loader uses the synchronous Redis client for compatibility with
        # the balance/read path; keep its network I/O off the event loop.
        no_inventory = await asyncio.to_thread(self._load_no_inventory)   # 无券冷却中的币(-3045),本周期跳过不重试
        self._shared_removed_bans = await asyncio.to_thread(self._load_shared_removed_bans)
        for symbol in pushed:
            if not self._rules_are_current(rules_generation):
                return
            removal_spread = self.spread_feed.get_symbol(symbol)
            # ``OPEN`` separate-tranche increments were removed when active
            # Position uniqueness became a database invariant.  Additional
            # debt is only added in-place while the row is BORROWED_IDLE,
            # before the hedge transition below.
            can_add_bite = False
            if symbol in active_symbols or symbol in statuses:
                continue
            if self._maintenance_blocks_new:
                statuses[symbol] = "网站维护中"
                continue
            if pause_gate_unavailable or symbol in paused_symbols:
                statuses[symbol] = (
                    "挂单已暂停" if not pause_gate_unavailable else "协调不可用"
                )
                continue
            # Maintain the pushed-list lifecycle before tradability/blacklist
            # gates. Retired symbols and symbols absent from the current
            # market universe have no quote, so placing this below those gates
            # left them pinned in the user's list forever.
            if not self._spread_fresh(removal_spread):
                if await self._maybe_remove_stale_pushed(
                    symbol, expected_rules_generation=rules_generation
                ):
                    continue
            else:
                await self._clear_stale_pushed_since(symbol)
            # 逐道护栏:被拒则记状态(供前端挂单中子账户行显示),不借
            if symbol in blacklist:
                if not await self._maybe_auto_remove(
                    symbol,
                    reason="blacklist",
                    expected_rules_generation=rules_generation,
                ):
                    statuses[symbol] = "黑名单"
                continue
            if symbol not in tradable_symbols:
                if not await self._maybe_auto_remove(
                    symbol,
                    reason="not_tradable",
                    expected_rules_generation=rules_generation,
                ):
                    statuses[symbol] = "不可交易"
                continue
            # 点差不足移除是独立于借币条件的列表生命周期规则。必须先于
            # 无券/冷却等等待态判断，否则一个曾经 -3045 的低点差币会被
            # no-inventory 冷却永久挡在自动移除逻辑之前。
            if self._spread_sane(removal_spread) and self._spread_fresh(removal_spread):
                configured_remove_threshold = self._sym_threshold(
                    symbol, "remove_spread", getattr(rules, "remove_spread", None)
                )
                remove_threshold = self._bounded_remove_spread(
                    configured_remove_threshold,
                    getattr(rules, "auto_push_spread", None),
                )
                if self._below_remove_spread(removal_spread.spread_short, remove_threshold):
                    if not await self._low_spread_can_continue(
                        symbol,
                        removal_spread.spread_short,
                        expected_rules_generation=rules_generation,
                    ):
                        statuses[symbol] = "点差不符"
                        continue
            spread = removal_spread
            if not self._spread_fresh(spread):
                statuses[symbol] = "行情陈旧"; continue
            if not self._spread_sane(spread):
                statuses[symbol] = "行情异常"; continue
            # The effective spread line is a pure local gate and therefore
            # must win over cached inventory, volume, cooldown and private
            # maxBorrowable states. In particular, changing a symbol from a
            # permissive line to 9% must immediately show "点差不符" and must
            # never leak through to any Binance call under an older status.
            sym_rule = self._symbol_rule_for_execution(symbol)
            # Per-account symbol rules can stop new borrow requests while
            # existing positions continue through hedge/close/repay cleanup.
            # Apply this before inventory preflight or any Binance I/O.
            if sym_rule.get("account_enabled") is False:
                statuses[symbol] = "借币停止"
                continue
            eff_borrow = float(
                self._sym_threshold(symbol, "borrow_spread", g_borrow_spread)
            ) + borrow_buffer
            if not self._spread_persisted(
                symbol, float(spread.spread_short), eff_borrow
            ):
                statuses[symbol] = "点差不符"
                continue
            # Inventory polling is independent from the decision loop.  A
            # positive, fresh account snapshot is necessary before the more
            # expensive per-asset maxBorrowable preflight may run.
            if not self._inventory_allows(symbol):
                statuses[symbol] = "无券"
                continue
            # 无券/量不足/行情陈旧/点差不符 均为"正常等待态"(非故障),但各自如实显示 ——
            # 曾统一显示"运行中",用户无从区分"在等什么/是否真在借"(只能去币安App查借币记录),已拆回。
            # 无库存是一次真实的 Binance 借币阻断，不是 Worker 空转或已借到。
            # 保留冷却和自动重试，但把原因发布给前端，避免“运行中”被误读为
            # 借币已经成功。冷却到期后下一轮仍会重新检查库存。
            if symbol in no_inventory:
                # Binance -3045 is a normal inventory wait state. Keep the
                # execution state running so stale worker snapshots cannot
                # resurrect the retired "无券" fault label; the UI maps any
                # legacy payload to "寻币中" for compatibility.
                statuses[symbol] = "运行中"; continue
            if not self._volume_ok(symbol):
                statuses[symbol] = "量不足"; continue
            if self._is_banned(symbol):
                statuses[symbol] = "借币冷却"; continue
            if self._is_removed_banned(symbol):
                statuses[symbol] = "移除冷却"; continue
            # 手动还币后的暂停标记(engine_api 写,勾选1800s/在途10s):防"刚还清又被负阈值秒级重借"。
            # ⚠self._redis 是 aioredis(异步),必须 await —— 漏 await 时 get() 返回 coroutine 对象
            # 恒为 truthy → 每个币每周期恒判「还币暂停」永不借币(Redis 无 key 也照样暂停)。已修。
            try:
                if await self._redis.get(f"engine:{self._user_id}:repayhold:{symbol}"):
                    statuses[symbol] = "还币暂停"; continue
            except Exception:
                pass
            # 净期望闸拒开冷却(execute_borrow enforce 分支写,EX300):显示真实拦截原因
            # (原来只显"运行中"=反馈黑洞)+ 5min 内不重试(防 FAILED 洪水+白烧利率 REST)。
            try:
                if await self._redis.get(f"engine:{self._user_id}:netgate:{symbol}"):
                    statuses[symbol] = "E闸拒开"; continue
            except Exception:
                pass
            # 通用借币失败冷却(execute_borrow 非-3045错误写,EX120):如实显示+2min不重试
            # (防 -3055 等其它错误码每周期重试刷 FAILED 行,同 E闸/无券的打地鼠终版)。
            if await self._borrow_failure_state(symbol) is True:
                statuses[symbol] = "借币异常"; continue
            if sym_rule.get("max_borrow_amount") is not None and sym_rule["max_borrow_amount"] == 0:
                statuses[symbol] = "禁借"; continue
            # ── P0-2 自杀组合校验 ── 开仓阈值 < 平仓阈值 = 必然循环:借币对冲开仓(spread>open_spread)
            # 后立刻满足平仓(spread<close_spread),整夜开→平→重开烧 4 腿手续费+每轮小时头利息
            # (FIL 开-1/平1.0 即此)。从借币源头掐掉:开<平直接不借,记"配置冲突"提示用户改配置。
            # Borrowing is an independent inventory/holding decision.  Do not
            # apply the hedge open/close relationship here: a user may
            # deliberately pre-borrow at a zero (or negative) borrow line and
            # wait for a later opening spread.  The relationship is checked
            # immediately before hedging below.
            # An account/risk/capacity gate is a waiting state, not an active
            # Binance request.  Keep it explicit so the dashboard never shows
            # a false green "运行中" row.
            # Re-evaluate after every successful symbol in this same cycle.
            # A snapshot taken before the loop lets multiple candidates pass
            # a one-position limit before the next database refresh.
            borrow_block_status = self._borrow_block_status(
                active_count,
                max_positions,
                slot_occupied=symbol in active_slot_symbols,
            )
            if borrow_block_status:
                statuses[symbol] = borrow_block_status
                continue
            # A pushed symbol is shared by all of a user's workers, but margin
            # capacity is account-specific. Require this account's own cached
            # or live maxBorrowable result before it can compete for execution.
            # This also keeps known -3045 accounts out of execute_borrow, where
            # they would otherwise create a FAILED Position before an eligible
            # sibling gets the user/symbol lock.
            borrowable = await self._filter_by_borrowable(
                {symbol}, use_cycle_budget=True
            )
            if symbol not in borrowable:
                try:
                    unavailable = bool(
                        await self._redis.get(self._noinv_redis_key(symbol))
                    )
                    capacity_limited = bool(
                        await self._redis.get(self._capacity_redis_key(symbol))
                    )
                except Exception:
                    statuses[symbol] = "协调不可用"
                    continue
                if unavailable:
                    statuses[symbol] = "无券"
                elif capacity_limited:
                    statuses[symbol] = "额度不足"
                else:
                    statuses[symbol] = "库存预检"
                continue
            # 多账户并联(borrow_mode=multi): 同一币的并联账户数受 multi_max_accounts_per_symbol 限,
            # 跨账户 Redis 配额,防 N 账户一拥而上把杠杆池库存(-3045)/资金一次打光。非 multi 模式直接放行。
            if not await self._multi_parallel_reserve(symbol):
                statuses[symbol] = "并联满"
                continue
            # Serialize requests from the user's sub-account workers. A
            # Binance -3045 response can otherwise arrive five times before
            # the cooldown is visible to the other workers.
            borrow_lock = await self._acquire_borrow_lock(symbol)
            if borrow_lock is None:
                statuses[symbol] = "协调不可用"
                continue
            try:
                # The pushed list is user-scoped and can be changed by a
                # sibling Worker after this cycle loaded its snapshot. All
                # Worker-side transitions share this lock, so re-read both
                # gates here before initiating a financial side effect.
                if await self._is_paused_symbol(symbol):
                    statuses[symbol] = "挂单已暂停"
                    continue
                transition_state = await self._locked_borrow_transition_state(symbol)
                if transition_state is None:
                    statuses[symbol] = "协调不可用"
                    continue
                still_pushed, removal_cooldown = transition_state
                if not still_pushed:
                    statuses.pop(symbol, None)
                    continue
                if removal_cooldown:
                    self._shared_removed_bans.add(symbol)
                    statuses[symbol] = "移除冷却"
                    continue
                # Re-check after acquiring the lock: another account may
                # have just observed -3045 and written its scoped cooldown.
                cooldown = await self._borrow_cooldown_state(symbol)
                if cooldown is None:
                    statuses[symbol] = "协调不可用"
                    continue
                if cooldown:
                    no_inventory.add(symbol)
                    statuses[symbol] = "无券"
                    continue
                async def publish_borrow_phase(label: str) -> None:
                    statuses[symbol] = label
                    # This loop is still building a complete account snapshot.
                    # Carry forward later symbols so a phase event cannot make
                    # their rows disappear from the dashboard.
                    visible_symbols = set(pushed) | active_symbols
                    phase_snapshot = {
                        previous_symbol: previous_status
                        for previous_symbol, previous_status in self._symbol_statuses.items()
                        if previous_symbol in visible_symbols
                    }
                    phase_snapshot.update(statuses)
                    await self._publish_symbol_statuses(phase_snapshot)

                async def on_submission_event(event: str) -> None:
                    if event == "started":
                        await publish_borrow_phase("借币中")
                    elif event == "finished":
                        await publish_borrow_phase("借币核对中")

                # Preflight, configured confirmation delay and account-lock
                # acquisition are waiting work, not a Binance request.
                await publish_borrow_phase("等待借币")
                borrowed = await self._initiate_borrow(
                    symbol,
                    spread,
                    eff_borrow,
                    account_note,
                    submission_event_callback=on_submission_event,
                    expected_rules_generation=rules_generation,
                )
            finally:
                await self._release_borrow_lock(symbol, borrow_lock)
            if borrowed:
                active_symbols.add(symbol)
                if symbol not in active_slot_symbols:
                    active_slot_symbols.add(symbol)
                    active_count += 1
                # The request has returned and execute_borrow has committed
                # BORROWED_IDLE. "借币中" is valid only while Binance I/O is
                # in flight; publish the real next lifecycle stage now.
                statuses[symbol] = self._EXEC_STATUS_MAP["BORROWED_IDLE"]
            else:
                # execute_borrow persists lifecycle state before returning.
                # Re-read it so an ambiguous submission is never overwritten
                # by the generic error label for the rest of this cycle.
                lifecycle = await asyncio.to_thread(self._load_active_statuses)
                persisted_status = lifecycle.get(symbol)
                if persisted_status:
                    active_symbols.add(symbol)
                    statuses[symbol] = persisted_status
                else:
                    cooldown = await self._borrow_cooldown_state(symbol)
                    if cooldown is None:
                        statuses[symbol] = "协调不可用"
                    elif cooldown:
                        no_inventory.add(symbol)
                        statuses[symbol] = "无券"
                    else:
                        statuses[symbol] = "借币异常"

        await self._publish_symbol_statuses(statuses)

        # P1-8 借币子路径心跳:借币评估循环每跑完一轮就打戳,证明借币子路径真活着。
        # 区别于 _update_state 每10周期的主循环心跳——主循环心跳在借币子路径卡死时照跳
        # (就像"漏 await 致借币全废但主循环空转"那类);此戳一旦停更(而主心跳仍在)= 借币停摆。
        if self._redis:
            try:
                await self._redis.setex(
                    f"engine:{self._user_id}:borrow_hb:{self.sub_account_id}", 300,
                    datetime.now(timezone.utc).isoformat())
            except Exception:
                pass

        # ── Auto-push: symbols whose spread ≥ auto_push_spread join the user's pushed list ──
        if self._cycle_count % 10 == 0 and getattr(rules, "auto_push_spread", 0) and rules.auto_push_spread > 0:
            if not self._rules_are_current(rules_generation):
                return
            await self._auto_push(
                float(rules.auto_push_spread),
                tradable_symbols,
                expected_rules_generation=rules_generation,
            )

        # Borrow, close, and auto-push paths above can all change the
        # authoritative opportunity set after the first snapshot was written.
        # Re-read state once at the end of the cycle so a long Binance request
        # cannot leave the dashboard and inventory probe using a stale
        # denominator until the next full cycle.
        if self._rules_are_current(rules_generation):
            await self._reconcile_inventory_candidates(
                tradable_symbols,
                rules=rules,
                blacklist=blacklist,
                expected_rules_generation=rules_generation,
            )

        if self._cycle_count % 10 == 0:
            await self._update_state("RUNNING", active_positions=len(open_positions))

    async def _publish_symbol_statuses(self, statuses: dict[str, str]) -> None:
        """Persist and publish one account's complete decision snapshot."""
        snapshot = dict(statuses)
        self._symbol_statuses = snapshot
        if not self._redis:
            return

        # A newly opened dashboard needs a current snapshot because pub/sub
        # events are edge-triggered.  Refresh this short TTL every cycle.
        if self._user_id is not None:
            try:
                await self._redis.setex(
                    f"engine:{int(self._user_id)}:symbol_status:{int(self.sub_account_id)}",
                    120,
                    json.dumps(snapshot, ensure_ascii=False),
                )
            except Exception:
                logger.debug("symbol status snapshot write failed", exc_info=True)
            try:
                await self._redis.setex(
                    f"engine:{int(self._user_id)}:inventory_candidates:{int(self.sub_account_id)}",
                    120,
                    json.dumps(sorted(self._inventory_candidates), separators=(",", ":")),
                )
            except Exception:
                logger.debug("inventory candidate snapshot write failed", exc_info=True)

        # Publish every transition immediately.  This is also called before a
        # Binance borrow request so short-lived in-flight states remain visible.
        if snapshot != self._last_pushed_statuses:
            try:
                await self._redis.publish("symbol_status:updates", json.dumps({
                    "sub_account_id": self.sub_account_id,
                    "user_id": self._user_id,
                    "statuses": snapshot,
                }))
                self._last_pushed_statuses = snapshot
            except Exception as exc:
                logger.debug(f"symbol_status immediate publish failed: {exc}")

    async def _publish_inventory_candidates(self) -> bool:
        """Write and broadcast the current inventory-candidate snapshot.

        The Redis key remains a plain JSON list for compatibility with the
        health endpoint.  The pub/sub payload carries a generation and
        timestamp so clients can refresh immediately while retaining the
        endpoint as the authoritative, tenant-scoped source of rates.
        """
        if self._redis is None or self._user_id is None:
            return False
        generation = self._inventory_candidates_generation
        candidates = sorted(self._inventory_candidates)
        key = f"engine:{int(self._user_id)}:inventory_candidates:{int(self.sub_account_id)}"
        payload = {
            "user_id": self._user_id,
            "sub_account_id": self.sub_account_id,
            "candidates": candidates,
            "candidate_count": len(candidates),
            "generation": generation,
            "updated_at": time.time(),
        }
        try:
            # Write first: a health refresh triggered by the event must never
            # observe the previous candidate set.
            await self._redis.setex(
                key,
                120,
                json.dumps(candidates, separators=(",", ":")),
            )
            await self._redis.publish(
                "inventory_candidates:updates",
                json.dumps(payload, separators=(",", ":")),
            )
        except Exception:
            logger.debug(
                "inventory candidate update publish failed for account %s",
                self.sub_account_id,
                exc_info=True,
            )
            return False
        # If another cycle changed the set while Redis was awaited, leave the
        # newer generation pending so it is published on the next cycle.
        if generation == self._inventory_candidates_generation:
            self._inventory_candidates_published_generation = generation
        return True

    def _borrow_block_status(
        self,
        active_count: int,
        max_positions: int,
        *,
        slot_occupied: bool = False,
    ) -> str | None:
        """Describe a local opening gate without claiming a request is active.

        ``max_positions`` limits distinct symbols, not independently tracked
        borrow tranches.  Callers pass ``slot_occupied=True`` when evaluating
        another bite for a symbol that already owns a slot.
        """
        if not self._running or not self._account_opening_enabled:
            return "借币停止"
        if not self._margin_safe:
            return "保证金保护"
        if active_count >= max_positions and not slot_occupied:
            return "仓位已满"
        if self._account_max_borrow is not None and self._account_max_borrow == 0:
            return "禁借"
        return None

    async def _multi_parallel_reserve(self, symbol: str) -> bool:
        """多账户并联(borrow_mode=multi)跨账户配额: 同一币(同 user)最多
        multi_max_accounts_per_symbol 个子账户同时并联借。非 multi 模式恒放行(零行为变动)。

        实现: Redis set engine:borrowpar:{user}:{symbol} 存并联中的 account_id,带 TTL 兜底
        (借币秒级完成,本账户已在场则幂等放行;set 满且本账户不在其中则拒)。已在场(持有该币
        借/持仓)的账户视为已占位,直接放行。失败/异常一律放行(不因协调层故障阻断借币)。"""
        mode = getattr(self.config.global_rules, "borrow_mode", None) or \
            ("otoco" if getattr(self.config.global_rules, "borrow_via_otoco", False) else "repay")
        if mode != "multi":
            return True
        try:
            cap = int(getattr(self.config.global_rules, "multi_max_accounts_per_symbol", 3) or 3)
            if cap <= 0:
                return True
            key = f"engine:borrowpar:{self._user_id}:{symbol}"
            aid = str(self.sub_account_id)
            if self._redis is None:
                return False
            # 本账户已在集合内 → 幂等放行(刷新 TTL);否则在未满时加入。
            if await self._redis.sismember(key, aid):
                await self._redis.expire(key, 30)
                return True
            if await self._redis.scard(key) >= cap:
                return False
            await self._redis.sadd(key, aid)
            await self._redis.expire(key, 30)
            return True
        except Exception as exc:
            logger.error("Borrow parallel reservation unavailable for %s: %s", symbol, exc)
            return False

    async def _initiate_borrow(
        self,
        symbol: str,
        spread: SpreadSnapshot,
        eff_borrow: float,
        account_note: str,
        submission_event_callback=None,
        expected_rules_generation: int | None = None,
        allow_open_increment: bool = False,
    ) -> bool:
        """Phase 1: borrow at 挂单点差(含开仓缓冲), hold idle。eff_borrow=借币点差+open_spread_buffer。"""
        if is_custom_monitor_candidate(symbol):
            return False
        from engine.trading.order_executor import execute_borrow
        from decimal import Decimal as _D
        if await self._is_paused_symbol(symbol):
            return False
        if not self._borrow_submission_allowed(
            symbol, expected_rules_generation
        ):
            return False
        operation_lock = await self._acquire_account_operation_lock(
            symbol, ttl_sec=self._borrow_lock_ttl()
        )
        if operation_lock is None:
            logger.info("Borrow deferred %s: account operation lock is busy", symbol)
            return False
        try:
            if not self._borrow_submission_allowed(
                symbol, expected_rules_generation
            ):
                return False
            result = await execute_borrow(
                self.sub_account_id, symbol, spread,
                self.config.global_rules, self._trading_client,
                self._notifier, account_note,
                spread_feed=self.spread_feed,
                min_spread=_D(str(eff_borrow)),   # 二次确认按含缓冲的阈值,且 execute_borrow 内借币前会再校验新鲜度+阈值
                user_id=self._user_id,
                submission_event_callback=submission_event_callback,
                pre_submit_guard=lambda: self._rules_are_current(
                    expected_rules_generation
                ),
                inventory_guard=lambda quantity: self._inventory_allows(
                    symbol, minimum=quantity
                ),
                new_action_guard=lambda: self._new_action_allowed(symbol),
                # The final Binance boundary must prove that this Worker
                # still owns the Redis account/asset lease.  Passing the token
                # through avoids treating a lease that expired or was
                # replaced by a sibling worker as authorization to borrow.
                operation_lock_token=operation_lock,
                operation_lock_redis=self._redis,
                operation_lock_ttl_sec=self._borrow_lock_ttl(),
                allow_open_increment=allow_open_increment,
            )
            if result is None:
                return False
            self._last_borrow_at[symbol] = datetime.now(timezone.utc)  # C4 ban countdown
            return True
        except Exception as e:
            logger.error(f"Initiate borrow failed {symbol}: {e}")
            return False
        finally:
            await self._release_account_operation_lock(symbol, operation_lock)

    async def _topup_borrow(
        self,
        position: Position,
        spread: SpreadSnapshot,
        account_note: str,
        expected_rules_generation: int | None = None,
    ):
        """Top up one idle position; the executor owns the lifecycle lock."""
        if is_custom_monitor_candidate(getattr(position, "symbol", "")):
            return Decimal("0")
        from engine.trading.order_executor import execute_borrow_topup

        if await self._is_paused_symbol(position.symbol):
            return Decimal("0")
        if not self._borrow_submission_allowed(
            position.symbol, expected_rules_generation
        ):
            return Decimal("0")
        try:
            return await execute_borrow_topup(
                position.id,
                self.sub_account_id,
                position.symbol,
                spread,
                self.config.global_rules,
                self._trading_client,
                self._notifier,
                account_note,
                user_id=self._user_id,
                redis_client=self._redis,
                pre_submit_guard=lambda: self._rules_are_current(
                    expected_rules_generation
                ),
                inventory_guard=lambda quantity: self._inventory_allows(
                    position.symbol, minimum=quantity
                ),
                new_action_guard=lambda: self._new_action_allowed(
                    position.symbol
                ),
            )
        except Exception as exc:
            logger.warning("Top-up borrow failed %s: %s", position.symbol, exc)
            return Decimal("0")

    async def _hedge_position(
        self,
        position: Position,
        spread: SpreadSnapshot,
        account_note: str,
        expected_rules_generation: int | None = None,
    ):
        """Phase 2: sell spot + futures long. BORROWED_IDLE → OPEN.
        hedge_via_master 开启时合约腿用共享主账户 client;主账户 client 不可用则
        不动现货(留 BORROWED_IDLE 重试),绝不回退到子账户 key 打合约。"""
        from engine.trading.order_executor import execute_hedge
        # Keep the lifecycle lease alive through the configured confirmation
        # delay and the subsequent hedge preflight.  The same TTL is passed to
        # the final Binance boundary, where Lua compare-and-renew fences every
        # opening POST against replacement workers.
        operation_ttl = self._borrow_lock_ttl()
        operation_lock = await self._acquire_account_operation_lock(
            position.symbol, ttl_sec=operation_ttl
        )
        if operation_lock is None:
            logger.info("Hedge deferred %s: account operation lock is busy", position.symbol)
            return
        try:
            if not self._rules_are_current(expected_rules_generation):
                return
            if not self._spread_fresh(spread):
                logger.warning("Hedge %s held BORROWED_IDLE: spread snapshot is stale", position.symbol)
                return
            fc = None
            if getattr(self.config.global_rules, "hedge_via_master", False):
                from engine.trading.master_client import get_master_futures_client
                fc = await get_master_futures_client(self._user_id)
                if fc is None:
                    logger.warning(f"hedge_via_master: master client unavailable; "
                                   f"{position.symbol} stays BORROWED_IDLE")
                    return
            if not self._rules_are_current(expected_rules_generation):
                return
            async with self._master_symbol_operation(
                position.symbol,
                operation_ttl,
                force_master=bool(getattr(self.config.global_rules, "hedge_via_master", False)),
            ) as coordinated:
                if not coordinated:
                    return
                await execute_hedge(
                    position, spread, self.config.global_rules,
                    self._trading_client, self._notifier, account_note,
                    futures_client=fc, user_id=self._user_id,
                    pre_submit_guard=lambda: self._rules_are_current(
                        expected_rules_generation
                    ),
                    operation_lock_token=operation_lock,
                    operation_lock_redis=self._redis,
                    operation_lock_ttl_sec=operation_ttl,
                )
        except Exception as e:
            logger.error(f"Hedge failed {position.symbol}: {e}")
        finally:
            await self._release_account_operation_lock(position.symbol, operation_lock)

    async def _unhedge_position(
        self,
        position: Position,
        spread: SpreadSnapshot,
        account_note: str,
        emergency: bool = False,
        expected_rules_generation: int | None = None,
    ):
        """Close hedge (futures close + spot buy back), leave coin pending repay.
        合约腿按持仓归属(hedge_account)选 client,与开关当前值无关。"""
        from engine.trading.order_executor import execute_unhedge
        operation_ttl = self._borrow_lock_ttl()
        operation_lock = await self._acquire_account_operation_lock(
            position.symbol, ttl_sec=operation_ttl
        )
        if operation_lock is None:
            logger.info("Unhedge deferred %s: account operation lock is busy", position.symbol)
            return False
        try:
            if not emergency and not self._rules_are_current(expected_rules_generation):
                return False
            spot_order_mode = (
                getattr(self.config.global_rules, "spot_order_mode", "market") or "market"
            )
            # A stop-loss is an emergency risk exit.  Force a market buy-back
            # even when the configured normal mode is maker; maker pricing
            # depends on a live quote and must never hold exposure open.
            if emergency:
                spot_order_mode = "market"
            elif not self._spread_fresh(spread):
                logger.warning("Unhedge %s deferred: spread snapshot is stale", position.symbol)
                return False
            fc = None
            if getattr(position, "hedge_account", None) == "master":
                from engine.trading.master_client import get_master_futures_client
                fc = await get_master_futures_client(self._user_id)
                # fc=None 时 execute_unhedge 内部留 OPEN 等重试
            if not emergency and not self._rules_are_current(expected_rules_generation):
                return
            async with self._master_symbol_operation(
                position.symbol,
                operation_ttl,
                force_master=(
                    getattr(position, "hedge_account", None) == "master"
                    or bool(getattr(self.config.global_rules, "hedge_via_master", False))
                ),
            ) as coordinated:
                if not coordinated:
                    return False
                unhedged = await execute_unhedge(
                    position, spread, self._trading_client, self._notifier, account_note,
                    futures_client=fc,
                    user_id=self._user_id,
                    spot_order_mode=spot_order_mode,
                    allow_emergency_close=emergency,
                    pre_submit_guard=(
                        None
                        if emergency
                        else lambda: self._rules_are_current(expected_rules_generation)
                    ),
                    operation_lock_token=operation_lock,
                    operation_lock_redis=self._redis,
                    operation_lock_ttl_sec=operation_ttl,
                )
            if not unhedged:
                # Do not start the repay/removed cooldown until the hedge was
                # actually closed. A stale quote, missing master client, or
                # exchange error must remain eligible for the next retry.
                return False
            now = datetime.now(timezone.utc)
            self._repay_ban[position.symbol] = now
            # A Redis outage while publishing the removed-symbol cooldown
            # must not hide a completed exchange close or suppress the
            # immediate repayment follow-up.  The cooldown is advisory; the
            # durable Position state is authoritative.
            try:
                await self._set_removed_ban(position.symbol)   # 退出 → 进入用户级再借冷却窗
            except Exception:
                logger.warning(
                    "Unable to persist removed-symbol cooldown after closing %s",
                    position.symbol,
                    exc_info=True,
                )
            return True
        except Exception as e:
            logger.error(f"Unhedge failed {position.symbol}: {e}")
            return False
        finally:
            await self._release_account_operation_lock(position.symbol, operation_lock)

    async def _repay_position(
        self,
        position: Position,
        account_note: str,
        expected_rules_generation: int | None = None,
    ):
        """Repay margin debt → CLOSED (auto path; manual path via API)."""
        from engine.trading.order_executor import execute_repay
        operation_ttl = self._borrow_lock_ttl()
        operation_lock = await self._acquire_account_operation_lock(
            position.symbol, ttl_sec=operation_ttl
        )
        if operation_lock is None:
            self._repay_retry_after[position.id] = (
                time.monotonic() + REPAY_RETRY_COOLDOWN_SEC
            )
            logger.info("Repay deferred %s: account operation lock is busy", position.symbol)
            return
        try:
            if not self._rules_are_current(expected_rules_generation):
                return
            completed = await execute_repay(
                position, self._trading_client, self._notifier, account_note,
                fee_spot=getattr(self.config.global_rules, "taker_fee_spot", None),
                fee_futures=getattr(self.config.global_rules, "taker_fee_futures", None),
                pre_submit_guard=lambda: self._rules_are_current(
                    expected_rules_generation
                ),
                operation_lock_token=operation_lock,
                operation_lock_redis=self._redis,
                operation_lock_ttl_sec=operation_ttl,
            )
            if not completed:
                self._repay_retry_after[position.id] = (
                    time.monotonic() + REPAY_RETRY_COOLDOWN_SEC
                )
                return
            self._repay_retry_after.pop(position.id, None)
            # 还币完成后检查:该币所有持仓是否已 CLOSED,若是则自动下架+清规则(回归全局默认)
            await self._check_and_remove_symbol_after_close(position.symbol)
        except Exception as e:
            logger.error(f"Repay failed {position.symbol}: {e}")
        finally:
            await self._release_account_operation_lock(position.symbol, operation_lock)

    def _repay_retry_ready(self, position_id: int) -> bool:
        retry_after = self._repay_retry_after.get(position_id, 0.0)
        if retry_after > time.monotonic():
            return False
        self._repay_retry_after.pop(position_id, None)
        return True

    def _borrow_only_repay_retry_ready(self, symbol: str) -> bool:
        retry_after = self._borrow_only_repay_retry_after.get(symbol, 0.0)
        if retry_after > time.monotonic():
            return False
        self._borrow_only_repay_retry_after.pop(symbol, None)
        return True

    async def _maybe_giveup_idle(
        self,
        position,
        rules,
        expected_rules_generation: int | None = None,
    ):
        """BORROWED_IDLE 超时放弃(状态机补洞):借币后点差回落、对冲阈值长时间够不着的仓,
        原状态机无任何出路 → 永久 idle 白付小时头利息 + dashboard 挂「现-期残留」。
        条件(全满足才放弃):
          ① 有效挂单点差阈值 ≥ 0 —— 负阈值=故意囤券(借币持券等点差),持有即策略,不放弃;
          ② idle 时长 > IDLE_GIVEUP_MINUTES;
          ③ 还币未被该币规则禁止(allow_repay)。
        放弃 = 腿字段归零 + CAS 翻 PENDING_REPAY,复用既有还币路径(repay_spread 未配即立即还)。"""
        try:
            if not self._rules_are_current(expected_rules_generation):
                return
            g_borrow = getattr(rules, "borrow_spread", rules.open_spread)
            eff = self._sym_threshold(position.symbol, "borrow_spread", g_borrow)
            if eff is not None and float(eff) < 0:
                return   # 囤券意图,不超时
            if not self._is_repay_allowed(position.symbol):
                return
            anchor = (
                getattr(position, "borrowed_at", None)
                or position.created_at
                or position.updated_at
            )
            if anchor is None:
                return
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - anchor).total_seconds() / 60
            if age_min <= IDLE_GIVEUP_MINUTES:
                return
            def _flip():
                db = SessionLocal()
                try:
                    z = Decimal("0")
                    n = db.query(Position).filter(
                        Position.id == position.id, Position.status == "BORROWED_IDLE",
                    ).update({
                        "status": "PENDING_REPAY",
                        "spot_sell_qty": z, "spot_sell_price": z,
                        "spot_buy_qty": z, "spot_buy_price": z,
                        "futures_long_qty": z, "futures_long_price": z, "futures_close_price": z,
                        "error_message": f"idle 超时 {int(age_min)}min 未达对冲阈值,放弃还币止损",
                    }, synchronize_session=False)
                    db.commit()
                    return n
                finally:
                    db.close()
            if await asyncio.to_thread(_flip):
                logger.info(f"Idle give-up {position.symbol}: {int(age_min)}min 未达对冲阈值 → 转还币")
        except Exception as e:
            logger.warning(f"idle give-up check failed {position.symbol}: {e}")

    async def _check_and_remove_symbol_after_close(self, symbol: str):
        """平仓后自动下架+清规则:检查该币所有持仓是否已 CLOSED,若是则从 pushed_symbols discard + 清 SymbolRule/AccountSymbolRule。"""
        transition_lock = await self._acquire_borrow_lock(
            symbol, ttl_sec=BORROW_LOCK_TTL_SEC
        )
        if transition_lock is None:
            return
        db = None
        try:
            db = SessionLocal()
            # Position is already imported from the engine ledger model at
            # module scope; only the account owner join is local here.
            from app.db.models import SubAccount
            # 检查该 user 该 symbol 是否还有活跃持仓。FAILED 是终态且永久留库(借币点差中止等
            # 高频产生),必须与 CLOSED 一并排除 —— 原 `!= "CLOSED"` 把 FAILED 也当"未平仓",
            # 导致交易过的币几乎永不自动下架(engine_api 手动路径早已用 notin_ 口径,此处对齐)。
            # Position.user_id is NULL on legacy rows. Scope through the owned
            # sub-account so those financially live rows still block removal.
            owner = (
                SubAccount.user_id.is_(None)
                if self._user_id is None
                else SubAccount.user_id == self._user_id
            )
            open_count = db.query(Position).join(
                SubAccount, SubAccount.id == Position.sub_account_id,
            ).filter(
                owner,
                Position.symbol == symbol,
                Position.status.notin_(["CLOSED", "FAILED"]),
            ).count()
            if open_count > 0:
                return  # 还有未平仓位,不下架
            # 所有持仓已 CLOSED → 从 pushed_symbols 下架 + 清规则
            # ⚠self._redis 是 aioredis,get/set/publish 必须 await —— 曾漏 await 致 raw 为 coroutine,
            # json.loads 崩 TypeError 被 except 吞 → 全部币的平仓后自动下架+清规则从未生效
            # (FIL 残留配置本该在全平后被清,就是被这里挡住;实测 12:19:55 "not coroutine" 日志)。
            quote = self.spread_feed.get_symbol(symbol)
            if not self._spread_sane(quote) or not self._spread_fresh(quote):
                return
            removed = await self._maybe_auto_remove(
                symbol,
                reason="position_closed",
                spread_short=quote.spread_short,
                _transition_lock_token=transition_lock,
            )
            if not removed:
                return
            # 清单一规则(复用 engine_api._purge_symbol_rules)
            from app.api.engine_api import _purge_symbol_rules
            from app.db.models import SubAccount
            sub_ids = [a.id for a in db.query(SubAccount).filter(SubAccount.user_id == self._user_id).all()]
            _purge_symbol_rules(db, self._user_id, symbol, sub_ids)
            logger.info(f"Auto-purged symbol rules for {symbol} (回归全局默认)")
        except Exception as e:
            logger.error(f"Auto-remove symbol {symbol} failed: {e}")
        finally:
            if db is not None:
                db.close()
            await self._release_borrow_lock(symbol, transition_lock)

    async def _check_futures_margin(self, account_note: str):
        """合约账户距爆仓安全垫 < margin_rate_alert% 告警(纯告警,不动仓)。
        安全垫 = (totalMarginBalance − totalMaintMargin)/totalMarginBalance ×100,越低越接近强平。
        hedge_via_master 看主账户合约(全对冲腿所在),否则看子账户自身合约。
        跨子账户用 Redis 去重(每 user 每 ~25s 仅一次,避免 5 个 worker 重复查主账户)。"""
        try:
            self._notifier._ensure_config()
            thr = self._notifier.margin_rate_alert
            if thr is None or Decimal(str(thr)) <= 0:
                return
            from app.services.notifier import throttle_ok
            if not await asyncio.to_thread(throttle_ok, f"futmargin:check:{self._user_id}", 25, 1):
                return
            if getattr(self.config.global_rules, "hedge_via_master", False):
                from engine.trading.master_client import get_master_futures_client
                fc = await get_master_futures_client(self._user_id)
            else:
                fc = self._trading_client
            if fc is None:
                return
            acct = await fc.get_futures_account()
            mb = Decimal(str(acct.get("totalMarginBalance", "0")))
            mm = Decimal(str(acct.get("totalMaintMargin", "0")))
            if mb <= 0 or mm <= 0:
                return  # 无合约持仓/无维持保证金 = 无强平风险
            buffer_pct = (mb - mm) / mb * Decimal("100")
            if buffer_pct < Decimal(str(thr)):
                await self._notifier.notify_futures_margin(account_note, buffer_pct, Decimal(str(thr)))
        except Exception as e:
            logger.debug(f"futures margin check failed: {e}")

    def _position_unrealized_pnl(self, position: Position, spread: SpreadSnapshot) -> Decimal | None:
        """OPEN 仓盯市未实现 PnL(USDT,盈正亏负),供单仓止损判定。
        按平仓侧成交价估两腿:现货空腿买回=spot_ask、合约多腿平仓=fut_bid;
        加累计资金费(USDT,收正付负),减累计借币利息(币本位×现价换 USDT)。
        现货溢价走阔→两腿合计转负=亏(方向正确)。缺字段/价格异常返回 None(不触发止损,安全)。"""
        try:
            ssq = position.spot_sell_qty
            ssp = position.spot_sell_price
            flq = position.futures_long_qty
            flp = position.futures_long_price
            if not (ssq and ssp and flq and flp and spread
                    and spread.spot_ask > 0 and spread.fut_bid > 0):
                return None
            spot_leg = (Decimal(str(ssp)) - spread.spot_ask) * Decimal(str(ssq))   # 空现货: 卖价-买回价
            fut_leg = (spread.fut_bid - Decimal(str(flp))) * Decimal(str(flq))      # 多合约: 平价-开价
            funding = Decimal(str(position.cumulative_funding_fee or 0))            # USDT
            interest_usdt = Decimal(str(position.cumulative_interest or 0)) * spread.spot_ask  # 币本位→USDT
            return spot_leg + fut_leg + funding - interest_usdt
        except Exception:
            return None

    def _load_pushed_symbols(self) -> set[str]:
        """Load executable pushed symbols; custom rows stay display-only.

        The API still exposes ``CUSTOM:<id>`` in the tenant candidate list,
        but the trading Worker must never let that namespace reach inventory,
        borrow, hedge, or Binance preflight code.
        """
        try:
            import redis as _redis_sync
            r = _redis_sync.from_url(settings.redis_url, decode_responses=True)
            raw = r.get(f"engine:{self._user_id}:pushed_symbols")
            r.close()
            values = set(json.loads(raw)) if raw else set()
            return {
                str(symbol).strip().upper()
                for symbol in values
                if str(symbol).strip() and not is_custom_monitor_candidate(symbol)
            }
        except Exception:
            return set()

    def _load_paused_symbols(self) -> set[str] | None:
        """Return this tenant's pause set, or ``None`` if Redis is unknown."""
        from engine.pause_gate import load_paused_symbols_sync

        return load_paused_symbols_sync(self._user_id)

    async def _is_paused_symbol(self, symbol: str) -> bool:
        """Recheck the pause gate immediately before a new action."""
        try:
            from engine.pause_gate import is_symbol_paused_async

            return await is_symbol_paused_async(
                self._user_id,
                symbol,
                self._redis,
            )
        except Exception:
            return True

    def _new_action_allowed(self, symbol: str) -> bool:
        """Synchronous final-HTTP pause check for Binance client callbacks."""
        if is_custom_monitor_candidate(symbol):
            return False
        from engine.pause_gate import is_symbol_paused_sync

        # ``BinanceTradingClient`` invokes this callback synchronously at the
        # last HTTP boundary.  ``self._redis`` is the Worker event-loop client
        # (redis.asyncio); passing it to a sync gate returns coroutine objects
        # and can make every request look paused.  Let the sync gate create a
        # short-timeout sync client instead.  This check is deliberately kept
        # separate from the async cycle-level gate so an admin change still
        # closes the final submission race.
        if is_symbol_paused_sync(self._user_id, symbol):
            return False
        # Re-read the shared maintenance switch at the final boundary.  The
        # cycle cache closes the normal path; this check closes a race where
        # an admin enables maintenance while an HTTP request is in flight.
        if self._maintenance_blocks_new:
            return False
        try:
            from engine.maintenance_gate import maintenance_blocks_new_sync
            return not maintenance_blocks_new_sync()
        except Exception:
            return False

    async def _locked_borrow_transition_state(
        self, symbol: str
    ) -> tuple[bool, bool] | None:
        """Re-read membership and removal cooldown while holding the symbol lock."""
        if is_custom_monitor_candidate(symbol):
            return None
        if self._redis is None:
            return None
        normalized = str(symbol or "").strip().upper()
        scope = self._redis_user_scope()
        try:
            raw = await self._redis.get(f"engine:{scope}:pushed_symbols")
            if isinstance(raw, bytes):
                raw = raw.decode()
            members = json.loads(raw) if raw else []
            if not isinstance(members, list):
                raise ValueError("pushed symbol payload is not a JSON array")
            still_pushed = normalized in {
                str(member or "").strip().upper() for member in members
            }
            cooldown_raw = await self._redis.get(
                f"engine:{scope}:removed_cooldown:{normalized}"
            )
            cooldown_enabled = int(
                getattr(self.config.global_rules, "removed_cooldown_minutes", 0) or 0
            ) > 0
            return still_pushed, cooldown_enabled and bool(cooldown_raw)
        except Exception:
            logger.warning(
                "Borrow transition state unavailable for %s", normalized, exc_info=True
            )
            return None

    def _redis_user_scope(self) -> str:
        """Stable Redis namespace for owned and legacy NULL-owner engines."""
        return "None" if self._user_id is None else str(int(self._user_id))

    @staticmethod
    def _below_remove_spread(value, threshold) -> bool:
        """Return whether a live spread is strictly below its removal line."""
        if threshold is None:
            return False
        try:
            current = Decimal(str(value))
            limit = Decimal(str(threshold))
            return current.is_finite() and limit.is_finite() and current < limit
        except Exception:
            return False

    @staticmethod
    def _bounded_remove_spread(remove_threshold, auto_push_threshold):
        return effective_remove_threshold(remove_threshold, auto_push_threshold)

    def _all_user_accounts_below_remove_line(self, symbol: str, spread_short) -> bool:
        """Authorize a shared-list removal only when every eligible account agrees.

        The pushed list is user-scoped, while account-symbol removal overrides
        are account-scoped. One Worker must therefore never remove a symbol
        that a sibling account still keeps above its own exit line.
        """
        db = SessionLocal()
        try:
            normalized = str(symbol or "").strip().upper()
            if not normalized:
                return False
            bare = normalized[:-4] if normalized.endswith("USDT") else normalized
            candidates = (normalized, bare) if bare != normalized else (normalized,)
            owner = (
                SubAccount.user_id.is_(None)
                if self._user_id is None
                else SubAccount.user_id == self._user_id
            )
            accounts = db.query(SubAccount).filter(
                owner,
                SubAccount.is_enabled.is_(True),
            ).all()
            if not accounts:
                return False

            symbol_query = db.query(SymbolRule).filter(SymbolRule.symbol.in_(candidates))
            if self._user_id is None:
                symbol_query = symbol_query.filter(SymbolRule.user_id.is_(None))
            else:
                symbol_query = symbol_query.filter(SymbolRule.user_id == self._user_id)
            symbol_rows = symbol_query.all()
            symbol_rule = next(
                (row for row in symbol_rows if row.symbol == normalized),
                symbol_rows[0] if symbol_rows else None,
            )
            if symbol_rule is not None and symbol_rule.allow_remove is False:
                return False

            account_ids = [int(account.id) for account in accounts]
            account_query = db.query(AccountSymbolRule).filter(
                AccountSymbolRule.sub_account_id.in_(account_ids),
                AccountSymbolRule.symbol.in_(candidates),
            )
            if self._user_id is None:
                account_query = account_query.filter(AccountSymbolRule.user_id.is_(None))
            else:
                account_query = account_query.filter(
                    AccountSymbolRule.user_id == self._user_id
                )
            account_rules: dict[int, AccountSymbolRule] = {}
            for row in account_query.all():
                account_id = int(row.sub_account_id)
                current = account_rules.get(account_id)
                if current is None or row.symbol == normalized:
                    account_rules[account_id] = row

            base_remove = getattr(self.config.global_rules, "remove_spread", None)
            if symbol_rule is not None and symbol_rule.remove_spread is not None:
                base_remove = symbol_rule.remove_spread
            auto_push = getattr(self.config.global_rules, "auto_push_spread", None)
            eligible = 0
            for account in accounts:
                account_rule = account_rules.get(int(account.id))
                if account_rule is not None and account_rule.is_enabled is False:
                    continue
                eligible += 1
                threshold = base_remove
                if account_rule is not None and account_rule.remove_spread is not None:
                    threshold = account_rule.remove_spread
                threshold = self._bounded_remove_spread(threshold, auto_push)
                if not self._below_remove_spread(spread_short, threshold):
                    return False
            return eligible > 0
        except Exception:
            logger.warning(
                "Unable to aggregate remove policy for %s", symbol, exc_info=True
            )
            return False
        finally:
            db.close()

    def _has_user_active_position(self, symbol: str) -> bool:
        """Protect a user-level pushed symbol while any owned account is in-flight."""
        db = SessionLocal()
        try:
            query = db.query(Position.id).join(
                SubAccount, Position.sub_account_id == SubAccount.id
            ).filter(
                SubAccount.user_id == self._user_id,
                Position.symbol == symbol,
                Position.status.notin_(("CLOSED", "FAILED")),
            )
            return query.first() is not None
        finally:
            db.close()

    async def _maybe_auto_remove(
        self,
        symbol: str,
        *,
        reason: str = "remove_spread",
        spread_short=None,
        expected_rules_generation: int | None = None,
        _transition_lock_token: str | None = None,
    ) -> bool:
        """Remove a low-spread pushed symbol when it is safe to leave the list.

        Manual pushes are protected from the normal low-spread lifecycle.
        Safety exits such as a persistently stale market feed still remove the
        symbol and clear its manual marker.
        """
        if not self._redis:
            return False
        protect_manual = reason == "remove_spread"
        require_account_consensus = reason in ("remove_spread", "position_closed")
        if protect_manual and self._symbol_rule_for_execution(symbol).get("allow_remove", True) is False:
            return False

        scope = self._redis_user_scope()
        owns_transition_lock = _transition_lock_token is None
        transition_lock = _transition_lock_token
        try:
            if owns_transition_lock:
                transition_lock = await self._acquire_borrow_lock(
                    symbol, ttl_sec=BORROW_LOCK_TTL_SEC
                )
                if transition_lock is None:
                    return False
            if not self._rules_are_current(expected_rules_generation):
                return False
            if await asyncio.to_thread(self._has_user_active_position, symbol):
                return False
            if require_account_consensus:
                if spread_short is None:
                    quote = self.spread_feed.get_symbol(symbol)
                    spread_short = getattr(quote, "spread_short", None)
                if not await asyncio.to_thread(
                    self._all_user_accounts_below_remove_line,
                    symbol,
                    spread_short,
                ):
                    return False

            # The database consensus read can yield while a committed rule
            # event replaces this cycle's snapshot. Do not let the former
            # threshold delete shared control-plane state afterward.
            if not self._rules_are_current(expected_rules_generation):
                return False

            pushed_key = f"engine:{scope}:pushed_symbols"
            cooldown_minutes = int(
                getattr(self.config.global_rules, "removed_cooldown_minutes", 0) or 0
            )
            cooldown_key = (
                f"engine:{scope}:removed_cooldown:{symbol}"
                if cooldown_minutes > 0 else ""
            )
            current, changed = await mutate_pushed_symbols_async(
                self._redis,
                pushed_key,
                remove={symbol},
                remove_cooldown_key=cooldown_key,
                remove_cooldown_ttl=cooldown_minutes * 60,
                manual_marker_key=manual_push_marker_key(self._user_id, symbol),
                protect_manual_removal=protect_manual,
                clear_manual=not protect_manual,
            )
            if not changed:
                return False

            try:
                await self._redis.hdel(auto_global_rules_key(self._user_id), symbol)
            except Exception:
                logger.warning(
                    "Unable to clear automatic rule source for %s",
                    symbol,
                    exc_info=True,
                )

            await self._set_removed_ban(symbol, persist=False)
            await self._redis.publish("pushed:updates", json.dumps({
                "user_id": self._user_id,
                "pushed_symbols": sorted(current),
                "removed_symbol": symbol,
                "reason": reason,
            }))
            logger.info("Auto-removed %s: %s", symbol, reason)
            return True
        except Exception:
            logger.warning("Auto-remove failed for %s", symbol, exc_info=True)
            return False
        finally:
            if owns_transition_lock:
                await self._release_borrow_lock(symbol, transition_lock)

    async def _low_spread_can_continue(
        self,
        symbol: str,
        spread_short,
        *,
        expected_rules_generation: int | None = None,
    ) -> bool:
        """Keep protected pushes eligible for their independent borrow line.

        ``remove_spread`` controls list lifecycle. A manual marker or an
        explicit ``allow_remove=false`` protects that lifecycle, but must not
        become an extra opening threshold. Other failed removals (lock owner,
        active position, or Redis failure) remain fail-closed for this cycle.
        """
        if await self._maybe_auto_remove(
            symbol,
            spread_short=spread_short,
            expected_rules_generation=expected_rules_generation,
        ):
            return False
        if self._symbol_rule_for_execution(symbol).get("allow_remove", True) is False:
            return True
        if not self._redis:
            return False
        try:
            return bool(
                await self._redis.get(manual_push_marker_key(self._user_id, symbol))
            )
        except Exception:
            return False

    async def _clear_stale_pushed_since(self, symbol: str) -> None:
        if not self._redis:
            return
        try:
            await self._redis.hdel(
                f"engine:{self._redis_user_scope()}:pushed_stale_since", symbol
            )
        except Exception:
            logger.debug("Unable to clear pushed stale timer for %s", symbol, exc_info=True)

    async def _maybe_remove_stale_pushed(
        self,
        symbol: str,
        *,
        expected_rules_generation: int | None = None,
    ) -> bool:
        """Remove an unpositioned pushed symbol after its market feed is absent long enough."""
        if not self._redis:
            return False
        key = f"engine:{self._redis_user_scope()}:pushed_stale_since"
        now = int(time.time())
        try:
            raw = await self._redis.hget(key, symbol)
            if raw is None:
                await self._redis.hsetnx(key, symbol, now)
                return False
            try:
                stale_since = int(raw)
            except (TypeError, ValueError):
                await self._redis.hdel(key, symbol)
                await self._redis.hsetnx(key, symbol, now)
                return False
            if now - stale_since < PUSHED_STALE_EVICT_SEC:
                return False
            removed = await self._maybe_auto_remove(
                symbol,
                reason="market_feed_stale",
                expected_rules_generation=expected_rules_generation,
            )
            if removed:
                await self._redis.hdel(key, symbol)
            return removed
        except Exception:
            logger.warning("Stale pushed-symbol cleanup failed for %s", symbol, exc_info=True)
            return False

    def _inventory_source_symbols(
        self,
        pushed,
        open_positions,
        idle_positions,
        pending_repay,
        active_statuses,
        *,
        topup_path_enabled: bool,
    ) -> set[str]:
        """Build the account-local source set before market/rule filtering.

        The inventory endpoint returns one full account snapshot.  This set
        describes which pushed/idle symbols can still reach that endpoint in
        the current lifecycle state; it is intentionally kept separate from
        the final quote/rule eligibility check.
        """
        active_symbols = (
            {getattr(position, "symbol", "") for position in open_positions}
            | {getattr(position, "symbol", "") for position in idle_positions}
            | {getattr(position, "symbol", "") for position in pending_repay}
        )
        active_symbols.discard("")
        active = set(active_statuses or {})
        # OPEN rows are already fully hedged and now own the single active
        # Position key.  They must not be treated as fresh borrow candidates;
        # only BORROWED_IDLE rows can use the existing in-place top-up path.
        additive_positions = list(idle_positions or ())
        idle_symbols = {
            str(getattr(position, "symbol", "") or "").upper()
            for position in idle_positions
            if getattr(position, "symbol", None)
        }
        additive_symbols = {
            getattr(position, "symbol", "") for position in additive_positions
        }
        additive_symbols.discard("")
        sources: set[str] = set()
        for raw_symbol in pushed or ():
            symbol = str(raw_symbol or "").upper()
            if not symbol or is_custom_monitor_candidate(symbol):
                continue
            if symbol not in active_symbols and symbol not in active:
                sources.add(symbol)
                continue
            if (
                symbol in additive_symbols
                and symbol not in active
                and (symbol not in idle_symbols or topup_path_enabled)
                and self._has_incremental_borrow_room(
                    symbol,
                    self.spread_feed.get_symbol(symbol),
                    additive_positions,
                    allow_cap_tail=symbol in idle_symbols,
                )
            ):
                sources.add(symbol)
        if topup_path_enabled:
            for position in idle_positions or ():
                symbol = str(getattr(position, "symbol", "") or "").upper()
                if symbol and self._has_incremental_borrow_room(
                    symbol,
                    self.spread_feed.get_symbol(symbol),
                    additive_positions,
                    allow_cap_tail=True,
                ):
                    sources.add(symbol)
        return sources

    async def _reconcile_inventory_candidates(
        self,
        tradable_symbols: set[str],
        *,
        rules=None,
        blacklist: set[str] | None = None,
        expected_rules_generation: int | None = None,
    ) -> bool:
        """Recompute/publish candidates from the latest lifecycle state.

        This is deliberately a single end-of-cycle read.  It catches state
        transitions made after the initial candidate calculation (successful
        borrow, hedge/repay, low-spread removal, or auto-push) without adding a
        publish call to every individual transition.
        """
        if rules is None:
            async with self._rules_state_lock:
                rules = self.config.global_rules
                blacklist = self.config.blacklist
                if expected_rules_generation is None:
                    expected_rules_generation = self._rules_generation
        elif blacklist is None:
            blacklist = self.config.blacklist
        if expected_rules_generation is None:
            expected_rules_generation = self._rules_generation
        try:
            open_positions = await asyncio.to_thread(self._load_open_positions)
            idle_positions = await asyncio.to_thread(
                self._load_positions_by_status, "BORROWED_IDLE"
            )
            pending_repay = await asyncio.to_thread(
                self._load_positions_by_status, "PENDING_REPAY"
            )
            pushed = await asyncio.to_thread(self._load_pushed_symbols)
            active_statuses = await asyncio.to_thread(self._load_active_statuses)
            topup_mode = getattr(rules, "borrow_mode", None) or (
                "otoco" if getattr(rules, "borrow_via_otoco", False) else "repay"
            )
            sources = self._inventory_source_symbols(
                pushed,
                open_positions,
                idle_positions,
                pending_repay,
                active_statuses,
                topup_path_enabled=topup_mode
                in ("single", "multi", "otoco", "repay"),
            )
            # Reads above can yield while the rules listener invalidates this
            # cycle.  Recheck immediately before mutating the authoritative
            # in-memory candidate set, under the same state lock used by the
            # listener, so stale thresholds cannot leak into the next probe.
            if not self._rules_are_current(expected_rules_generation):
                return False
            paused_symbols = await asyncio.to_thread(self._load_paused_symbols)
            eligible = set()
            if paused_symbols is not None:
                eligible = self._eligible_inventory_candidates(
                    sources,
                    tradable_symbols=set(tradable_symbols or ()),
                    blacklist=set(blacklist or ()),
                    rules=rules,
                    paused_symbols=paused_symbols,
                )
            async with self._rules_state_lock:
                if not self._rules_are_current(expected_rules_generation):
                    return False
                changed = self._set_inventory_candidates(eligible)
            if (
                changed
                or self._inventory_candidates_published_generation
                != self._inventory_candidates_generation
            ):
                if not self._rules_are_current(expected_rules_generation):
                    return False
                await self._publish_inventory_candidates()
            return changed
        except Exception:
            # Candidate publication is a health/telemetry path.  Keep the
            # previous authoritative snapshot if a transient DB read fails;
            # the next cycle will retry rather than clearing a valid gate.
            logger.warning(
                "Inventory candidate reconciliation failed for account %s",
                self.sub_account_id,
                exc_info=True,
            )
            return False

    def _set_inventory_candidates(self, symbols) -> bool:
        normalized = frozenset(
            f"{asset}USDT"
            for asset in (normalize_asset(symbol) for symbol in (symbols or ()))
            if asset
        )
        if normalized == self._inventory_candidates:
            return False
        self._inventory_candidates = normalized
        self._inventory_candidates_generation += 1
        self._inventory_candidates_event.set()
        return True

    def _eligible_inventory_candidates(
        self,
        symbols,
        *,
        tradable_symbols: set[str],
        blacklist: set[str],
        rules,
        paused_symbols: set[str] | None = None,
    ) -> set[str]:
        """Return symbols that can reach this account's inventory read gate."""
        if (
            not self._running
            or not self._account_opening_enabled
            or not self._margin_safe
            or self._trading_client is None
            or self._redis is None
            or (
                self._account_max_borrow is not None
                and self._account_max_borrow == 0
            )
        ):
            return set()

        global_borrow = getattr(rules, "borrow_spread", rules.open_spread)
        try:
            spread_buffer = float(getattr(rules, "open_spread_buffer", 0) or 0)
        except (TypeError, ValueError):
            return set()

        eligible: set[str] = set()
        paused = {
            str(value).strip().upper()
            for value in (paused_symbols or set())
            if str(value).strip()
        }
        for raw_symbol in symbols or ():
            if is_custom_monitor_candidate(raw_symbol):
                continue
            asset = normalize_asset(raw_symbol)
            symbol = f"{asset}USDT" if asset else ""
            if (
                not symbol
                or symbol not in tradable_symbols
                or symbol in blacklist
                or symbol in paused
            ):
                continue
            account_rule = self._symbol_rule_for_execution(symbol)
            if account_rule.get("account_enabled") is False:
                continue
            if account_rule.get("max_borrow_amount") == 0:
                continue
            spread = self.spread_feed.get_symbol(symbol)
            if not self._spread_sane(spread) or not self._spread_fresh(spread):
                continue
            try:
                effective_borrow = float(
                    self._sym_threshold(symbol, "borrow_spread", global_borrow)
                ) + spread_buffer
                spread_short = float(spread.spread_short)
            except (AttributeError, TypeError, ValueError):
                continue
            if not self._spread_persisted(symbol, spread_short, effective_borrow):
                continue
            eligible.add(symbol)
        return eligible

    def _inventory_redis_scope(self) -> str:
        tenant = (
            str(int(self._user_id))
            if self._user_id is not None
            else f"account-{int(self.sub_account_id)}"
        )
        return f"{tenant}:{int(self.sub_account_id)}"

    def _inventory_redis_key(self, kind: str) -> str:
        return f"engine:inventory:{kind}:{self._inventory_redis_scope()}"

    def _inventory_allows(
        self,
        symbol: object,
        minimum: Decimal = Decimal("0"),
    ) -> bool:
        """Fail closed unless fresh inventory covers ``minimum`` quantity."""
        probe = self._inventory_probe
        snapshot = self._inventory_snapshot
        asset = normalize_asset(symbol)
        pair = f"{asset}USDT" if asset else ""
        try:
            required = Decimal(str(minimum))
        except (TypeError, ValueError, ArithmeticError):
            return False
        if (
            probe is None
            or snapshot is None
            or not asset
            or pair not in self._inventory_candidates
            or not required.is_finite()
            or required < 0
        ):
            return False
        age = max(0.0, time.monotonic() - snapshot.observed_at)
        return (
            age <= probe.snapshot_max_age
            and snapshot.has_inventory(asset, required)
        )

    def _borrow_submission_allowed(
        self,
        symbol: object,
        expected_rules_generation: int | None,
    ) -> bool:
        return (
            not is_custom_monitor_candidate(symbol)
            and
            self._rules_are_current(expected_rules_generation)
            and not self._maintenance_blocks_new
            and self._inventory_allows(symbol)
        )

    async def _release_inventory_probe_lease(self, token: str) -> None:
        if self._redis is None:
            return
        key = self._inventory_redis_key("lease")
        try:
            await self._redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end",
                1,
                key,
                token,
            )
            return
        except Exception:
            pass
        try:
            if await self._redis.get(key) == token:
                await self._redis.delete(key)
        except Exception:
            logger.warning(
                "Inventory probe lease release failed for account %s",
                self.sub_account_id,
                exc_info=True,
            )

    async def _read_shared_inventory_snapshot(self) -> InventorySnapshot | None:
        if self._redis is None or self._inventory_probe is None:
            return None
        try:
            raw = await self._redis.get(self._inventory_redis_key("snapshot"))
            if not raw:
                return None
            payload = json.loads(raw)
            published_at_ms = int(payload.pop("publishedAtMs"))
            age = (int(time.time() * 1000) - published_at_ms) / 1000.0
            if age < -1.0 or age > self._inventory_probe.snapshot_max_age:
                return None
            return parse_inventory_snapshot(
                payload,
                time.monotonic() - max(0.0, age),
            )
        except Exception:
            return None

    async def _distributed_inventory_probe(
        self,
        candidates: frozenset[str],
    ) -> InventorySnapshot | None:
        """Run at most one account GET per distributed rate slot.

        A short-lived shared snapshot lets a rolling-deployment duplicate use
        the leader's result without multiplying Binance UID requests. Redis
        failures close the gate; they never fall back to an uncoordinated GET.
        """
        probe = self._inventory_probe
        if probe is None or self._redis is None:
            return None
        lease_key = self._inventory_redis_key("lease")
        gate_key = self._inventory_redis_key("gate")
        snapshot_key = self._inventory_redis_key("snapshot")
        token = f"{os.getpid()}:{time.time_ns()}"
        try:
            acquired = await self._redis.set(
                lease_key,
                token,
                nx=True,
                ex=15,
            )
        except Exception as exc:
            raise InventoryProbeError("inventory coordination unavailable") from exc
        if not acquired:
            return await self._read_shared_inventory_snapshot()

        try:
            try:
                owns_slot = await self._redis.set(
                    gate_key,
                    token,
                    nx=True,
                    px=max(1, math.ceil(probe.interval * 1000)),
                )
            except Exception as exc:
                raise InventoryProbeError("inventory rate slot unavailable") from exc
            if not owns_slot:
                return await self._read_shared_inventory_snapshot()

            try:
                snapshot = await probe.probe(candidates)
            except BaseException:
                try:
                    await self._redis.delete(snapshot_key)
                except Exception:
                    pass
                raise

            shared = json.dumps(
                {
                    "assets": {
                        asset: str(amount)
                        for asset, amount in snapshot.assets.items()
                    },
                    "updateTime": snapshot.update_time_ms,
                    "publishedAtMs": int(time.time() * 1000),
                },
                separators=(",", ":"),
            )
            try:
                await self._redis.set(
                    snapshot_key,
                    shared,
                    px=max(1, math.ceil(probe.snapshot_max_age * 1000)),
                )
            except Exception as exc:
                # A local-only positive snapshot would let this process trade
                # while duplicates fail to coordinate. Close the whole gate.
                raise InventoryProbeError("inventory snapshot publish failed") from exc
            return snapshot
        finally:
            await self._release_inventory_probe_lease(token)

    async def _clear_recovered_no_inventory(
        self,
        assets: frozenset[str],
    ) -> None:
        if self._redis is None:
            return
        for asset in assets:
            try:
                await self._redis.delete(
                    self._noinv_redis_key(f"{asset}USDT")
                )
            except Exception:
                logger.warning(
                    "Unable to clear recovered inventory marker %s/%s",
                    self.sub_account_id,
                    asset,
                    exc_info=True,
                )

    async def _wait_for_inventory_change(
        self,
        timeout: float | None,
        expected_candidates: frozenset[str] | None = None,
        expected_interval: float | None = None,
    ) -> None:
        self._inventory_candidates_event.clear()
        if (
            expected_candidates is not None
            and self._inventory_candidates != expected_candidates
        ):
            return
        probe = self._inventory_probe
        if (
            expected_interval is not None
            and probe is not None
            and probe.interval != expected_interval
        ):
            return
        if timeout is not None and timeout <= 0:
            return
        try:
            if timeout is None:
                await self._inventory_candidates_event.wait()
            else:
                await asyncio.wait_for(
                    self._inventory_candidates_event.wait(), timeout=timeout
                )
        except asyncio.TimeoutError:
            pass

    async def _inventory_probe_loop(self) -> None:
        """Continuously refresh inventory without accelerating `_cycle`."""
        failures = 0
        last_candidates: frozenset[str] | None = None
        while self._running:
            candidates = self._inventory_candidates
            if not candidates:
                if last_candidates:
                    if self._inventory_probe is not None:
                        await self._inventory_probe.probe(())
                    self._inventory_snapshot = None
                    self._inventory_positive_assets = frozenset()
                last_candidates = candidates
                self._inventory_candidates_event.clear()
                if self._inventory_candidates:
                    continue
                await self._inventory_candidates_event.wait()
                continue

            last_candidates = candidates
            started_at = time.monotonic()
            try:
                snapshot = await self._distributed_inventory_probe(candidates)
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                snapshot = None
                failures += 1
                if failures == 1 or failures & (failures - 1) == 0:
                    logger.warning(
                        "Inventory probe failed for account %s: %s",
                        self.sub_account_id,
                        exc,
                    )

            previous = self._inventory_positive_assets
            current = frozenset(
                normalize_asset(symbol)
                for symbol in candidates
                if snapshot is not None
                and snapshot.has_inventory(normalize_asset(symbol))
            )
            self._inventory_snapshot = snapshot
            self._inventory_positive_assets = current
            newly_positive = current - previous
            if newly_positive:
                await self._clear_recovered_no_inventory(newly_positive)
                self._inventory_ready_event.set()

            probe = self._inventory_probe
            base_interval = (
                probe.interval
                if probe is not None
                else 1.0 / DEFAULT_INVENTORY_PROBE_RATE
            )
            if failures:
                delay = min(5.0, max(base_interval, 0.5) * (2 ** min(failures - 1, 4)))
            else:
                delay = max(0.0, base_interval - (time.monotonic() - started_at))
            await self._wait_for_inventory_change(
                delay,
                candidates,
                expected_interval=base_interval,
            )

    def _load_account_no_inventory(self) -> set[str]:
        """Return only this sub-account's authoritative no-inventory markers."""
        r = None
        try:
            import redis as _redis_sync
            r = _redis_sync.from_url(settings.redis_url, decode_responses=True)
            prefix = f"engine:noinv:{int(self.sub_account_id)}:"
            keys = _scan_keys(r, f"{prefix}*")
            return {k.split(prefix, 1)[1] for k in keys if k.startswith(prefix)}
        except Exception:
            return set()
        finally:
            if r is not None:
                try:
                    r.close()
                except Exception:
                    logger.debug("Unable to close synchronous Redis client", exc_info=True)

    def _load_no_inventory(self) -> set[str]:
        """Return only this account's authoritative inventory misses.

        Binance capacity can differ between sibling sub-accounts because their
        collateral differs. A user-wide cooldown would let the first account
        that receives -3045 prevent another account with capacity from trying.
        The user/symbol lock still serializes actual requests.
        """
        return self._load_account_no_inventory()

    @staticmethod
    def _borrow_asset(symbol: object) -> str:
        # Keep this wrapper for callers/tests that used the Worker helper;
        # key construction itself lives in borrow_coordination.py so the
        # executor, worker, and balance reader cannot drift apart.
        return normalize_asset(symbol)

    def _noinv_redis_key(self, symbol: object) -> str:
        return no_inventory_key(self.sub_account_id, symbol)

    async def _borrow_cooldown_state(self, symbol: str) -> bool | None:
        """Return ``True`` for a cooldown, ``False`` for clear, ``None`` if unavailable."""
        if self._redis is None:
            logger.error("Borrow cooldown unavailable for %s: Redis client is not initialized", symbol)
            return None
        try:
            return bool(await self._redis.get(self._noinv_redis_key(symbol)))
        except Exception as exc:
            logger.warning("Borrow cooldown read unavailable for %s: %s", symbol, exc)
            return None

    async def _has_no_inventory(self, symbol: str) -> bool:
        """Compatibility wrapper; unavailable coordination fails closed."""
        state = await self._borrow_cooldown_state(symbol)
        return state is not False

    def _borrow_lock_ttl(self) -> int:
        """Return a lease long enough to cover the borrow confirmation delay.

        ``execute_borrow`` sleeps for ``borrow_delay_sec`` before submitting
        the request.  The lease must outlive that delay so sibling workers
        cannot enter while the first request is still in flight.  Keep a
        minimum TTL for the zero-delay path and tolerate malformed config
        values by falling back to the minimum.
        """
        try:
            delay = max(0, int(getattr(self.config.global_rules, "borrow_delay_sec", 0) or 0))
        except (TypeError, ValueError):
            delay = 0
        return max(BORROW_LOCK_TTL_SEC, delay + BORROW_LOCK_GRACE_SEC)

    async def _acquire_borrow_lock(self, symbol: str, ttl_sec: int | None = None) -> str | None:
        """Acquire the user/symbol transition lock; ``None`` means it is owned."""
        if self._redis is None:
            logger.error("Borrow lock unavailable for %s: Redis client is not initialized", symbol)
            return None
        token = f"{self._user_id or 0}:{self.sub_account_id}:{time.time_ns()}"
        key = borrow_lock_key(self._user_id, self.sub_account_id, symbol)
        try:
            requested_ttl = self._borrow_lock_ttl() if ttl_sec is None else ttl_sec
            ttl = max(BORROW_LOCK_TTL_SEC, int(requested_ttl or BORROW_LOCK_TTL_SEC))
            acquired = await self._redis.set(key, token, nx=True, ex=ttl)
            return token if acquired else None
        except Exception as exc:
            logger.error("Borrow lock unavailable for %s; refusing new borrow: %s", symbol, exc)
            return None

    async def _acquire_account_operation_lock(
        self, symbol: str, ttl_sec: int | None = None
    ) -> str | None:
        """Acquire the account/asset lifecycle lock, failing closed on Redis errors."""
        if self._redis is None:
            logger.error("Account operation lock unavailable for %s: Redis is not initialized", symbol)
            return None
        # The lease is later carried to Binance's final HTTP guard.  A Redis
        # client without atomic EVAL cannot provide that ownership fence, so
        # do not acquire a lock that would only look advisory to the caller.
        if not callable(getattr(self._redis, "eval", None)):
            logger.error(
                "Account operation lock unavailable for %s: Redis EVAL is not supported",
                symbol,
            )
            return None
        token = f"{self._user_id or 0}:{self.sub_account_id}:{time.time_ns()}"
        key = account_operation_lock_key(self.sub_account_id, symbol)
        try:
            ttl = max(
                ACCOUNT_OPERATION_LOCK_TTL_SEC,
                int(ttl_sec or ACCOUNT_OPERATION_LOCK_TTL_SEC),
            )
            acquired = await self._redis.set(key, token, nx=True, ex=ttl)
            return token if acquired else None
        except Exception as exc:
            logger.error("Account operation lock unavailable for %s: %s", symbol, exc)
            return None

    @asynccontextmanager
    async def _master_symbol_operation(
        self,
        symbol: str,
        ttl_sec: int | None = None,
        *,
        force_master: bool | None = None,
    ):
        """Serialize this tenant's independent commands on a shared master symbol."""
        use_master = (
            bool(getattr(self.config.global_rules, "hedge_via_master", False))
            if force_master is None
            else bool(force_master)
        )
        if not use_master:
            yield True
            return
        if self._redis is None:
            logger.error("Master symbol lock unavailable for %s: Redis is not initialized", symbol)
            yield False
            return
        ttl = self._borrow_lock_ttl() if ttl_sec is None else ttl_sec
        try:
            async with master_symbol_lock(
                self._redis,
                self._user_id,
                symbol,
                owner=f"worker:{self.sub_account_id}",
                ttl_sec=ttl,
            ):
                yield True
        except (AccountOperationLockBusy, AccountOperationLockUnavailable) as exc:
            logger.info("Master symbol operation deferred %s: %s", symbol, exc)
            yield False

    async def _release_borrow_lock(self, symbol: str, token: str | None) -> None:
        if not token or self._redis is None:
            return
        key = borrow_lock_key(self._user_id, self.sub_account_id, symbol)
        eval_fn = getattr(self._redis, "eval", None)
        if not callable(eval_fn):
            logger.warning(
                "Cannot release borrow lock %s without atomic EVAL; leaving it for TTL expiry",
                key,
            )
            return
        try:
            await eval_fn(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end",
                1, key, token,
            )
        except Exception:
            logger.warning(
                "Failed to atomically release borrow lock %s; leaving it for TTL expiry",
                key,
                exc_info=True,
            )

    async def _release_account_operation_lock(self, symbol: str, token: str | None) -> None:
        if not token or self._redis is None:
            return
        key = account_operation_lock_key(self.sub_account_id, symbol)
        eval_fn = getattr(self._redis, "eval", None)
        if not callable(eval_fn):
            logger.warning(
                "Cannot release account operation lock %s without atomic EVAL; leaving it for TTL expiry",
                key,
            )
            return
        try:
            await eval_fn(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end",
                1, key, token,
            )
        except Exception:
            logger.warning(
                "Failed to atomically release account operation lock %s; leaving it for TTL expiry",
                key,
                exc_info=True,
            )

    async def _filter_by_tick(self, syms: set, threshold: float) -> set:
        """P1-6 tick 粒度过滤:剔除"一个 tick 的点差步进 > 阈值一半"的币。
        粗刻度低价币(如 RPL,tick=0.54%)点差只能按 tick 大档跳、量子化,开平各付半个 tick 摩擦
        就吃掉大半空间,推了也是伪机会。tick 从现货 exchangeInfo(_get_spot_filters,缓存1h),
        price 用点差快照 spot_ask。查不到价/tick 时不过滤(保守放行)。"""
        syms = {
            str(symbol).strip().upper()
            for symbol in (syms or set())
            if str(symbol).strip() and not is_custom_monitor_candidate(symbol)
        }
        if not syms or not self._trading_client:
            return syms
        kept = set()
        for sym in syms:
            try:
                sp = self.spread_feed.get_symbol(sym)
                px = float(getattr(sp, "spot_ask", 0) or 0) if sp else 0.0
                if px <= 0:
                    kept.add(sym); continue
                f = await self._trading_client._get_spot_filters(sym)
                tick_pct = float(f["tick"]) / px * 100.0   # 一个 tick 的点差步进(%)
                if tick_pct <= threshold / 2.0:
                    kept.add(sym)
                else:
                    logger.info(f"auto_push tick-filter 剔除 {sym}: tick步进 {tick_pct:.3f}% > 阈值半 {threshold/2:.3f}%")
            except Exception:
                kept.add(sym)   # 查失败保守放行
        return kept

    async def _mark_auto_push_unavailable(
        self, symbol: str, *, account_ttl: int = NO_INVENTORY_TTL_SEC
    ) -> None:
        """Cache an account-scoped private-SAPI inventory miss.

        Do not write the user-wide execution cooldown here. A preflight miss
        on one sub-account must leave sibling workers able to establish
        whether another enabled account has executable capacity.
        """
        if not self._redis:
            return
        await self._redis.set(
            self._noinv_redis_key(symbol), "1", ex=max(1, int(account_ttl))
        )

    def _capacity_redis_key(self, symbol: object) -> str:
        return borrow_capacity_key(
            self._user_id,
            self.sub_account_id,
            symbol,
        )

    async def _borrow_failure_state(self, symbol: object) -> bool | None:
        """Read the account key plus the legacy user key during migration."""
        if self._redis is None:
            return None
        try:
            for key in borrow_failure_read_keys(
                self._user_id, self.sub_account_id, symbol
            ):
                if await self._redis.get(key):
                    return True
            return False
        except Exception:
            logger.warning(
                "Borrow failure cooldown unavailable for account %s %s",
                self.sub_account_id,
                symbol,
                exc_info=True,
            )
            return None

    async def _mark_borrow_capacity_unavailable(
        self,
        symbol: str,
        *,
        ttl: int = BORROW_CAPACITY_TTL_SEC,
    ) -> None:
        if self._redis is None:
            return
        await self._redis.set(
            self._capacity_redis_key(symbol),
            "1",
            ex=max(1, int(ttl)),
        )

    def _auto_push_preflight_key(self, symbol: str, result: str) -> str:
        user_scope = (
            str(int(self._user_id))
            if self._user_id is not None
            else f"account-{int(self.sub_account_id)}"
        )
        return (
            f"engine:borrowpreflight:{user_scope}:{int(self.sub_account_id)}:"
            f"{symbol}:{result}"
        )

    async def _filter_by_borrowable(
        self, syms: set[str], *, use_cycle_budget: bool = False
    ) -> set[str]:
        """Keep execution candidates this account can borrow at executable size.

        This is an execution gate, not a pushed-list discovery filter. Results
        are account-scoped so one unavailable sub-account cannot block another.
        ``maxBorrowable`` is private account data and has no Binance websocket
        equivalent, so positive/negative/error results are cached and probes
        are budgeted per execution cycle.
        """
        syms = {
            str(symbol).strip().upper()
            for symbol in (syms or set())
            if str(symbol).strip() and not is_custom_monitor_candidate(symbol)
        }
        if not syms or not self._trading_client or not self._redis:
            return set()

        from engine.trading.binance_trading import BinanceAPIError

        minimum = AUTO_PUSH_MIN_NOTIONAL_USDT
        configured_min = Decimal(str(
            getattr(self.config.global_rules, "min_borrow_usdt", 0) or 0
        ))
        if configured_min.is_finite() and configured_min > minimum:
            minimum = configured_min
        collateral_ratio = Decimal(str(
            getattr(self.config.global_rules, "collateral_ratio", 1) or 1
        ))
        if (
            not collateral_ratio.is_finite()
            or collateral_ratio <= 0
            or collateral_ratio > 1
        ):
            collateral_ratio = Decimal("1")

        kept: set[str] = set()
        probes = 0
        for symbol in sorted(syms):
            ok_key = self._auto_push_preflight_key(symbol, "ok")
            error_key = self._auto_push_preflight_key(symbol, "error")
            capacity_key = self._capacity_redis_key(symbol)
            try:
                cached_amount = await self._redis.get(ok_key)
                if cached_amount is not None:
                    amount = Decimal(str(cached_amount))
                    snapshot = self.spread_feed.get_symbol(symbol)
                    price = Decimal(str(getattr(snapshot, "spot_ask", 0) or 0))
                    if (
                        amount.is_finite()
                        and price.is_finite()
                        and amount > 0
                        and price > 0
                        and amount * collateral_ratio * price >= minimum
                    ):
                        kept.add(symbol)
                    continue
                if await self._redis.get(error_key):
                    continue
                if await self._redis.get(capacity_key):
                    continue
                # Only this account's authoritative inventory marker applies
                # to preflight. The shorter user execution cooldown is for
                # serializing actual borrow attempts, not account discovery.
                if await self._redis.get(self._noinv_redis_key(symbol)):
                    continue
            except Exception:
                return set()

            budget_used = (
                self._execution_preflight_probes
                if use_cycle_budget
                else probes
            )
            if budget_used >= AUTO_PUSH_PREFLIGHT_BUDGET:
                continue

            lock_token = await self._acquire_borrow_lock(symbol)
            if lock_token is None:
                continue
            try:
                # Re-check account-scoped caches after taking the user/symbol
                # lock; another worker process may have completed this exact
                # account preflight while we waited.
                cached_amount = await self._redis.get(ok_key)
                if cached_amount is not None:
                    amount = Decimal(str(cached_amount))
                    snapshot = self.spread_feed.get_symbol(symbol)
                    price = Decimal(str(getattr(snapshot, "spot_ask", 0) or 0))
                    if (
                        amount.is_finite()
                        and price.is_finite()
                        and amount > 0
                        and price > 0
                        and amount * collateral_ratio * price >= minimum
                    ):
                        kept.add(symbol)
                    continue
                if (
                    await self._redis.get(error_key)
                    or await self._redis.get(capacity_key)
                    or await self._redis.get(self._noinv_redis_key(symbol))
                ):
                    continue

                try:
                    probes += 1
                    if use_cycle_budget:
                        self._execution_preflight_probes += 1
                    result = await self._trading_client.get_max_borrowable(
                        self._borrow_asset(symbol)
                    )
                    amount = Decimal(str(
                        result.get("amount", "0") if isinstance(result, dict) else result
                    ))
                    snapshot = self.spread_feed.get_symbol(symbol)
                    price = Decimal(str(getattr(snapshot, "spot_ask", 0) or 0))
                    if (
                        not amount.is_finite()
                        or not price.is_finite()
                        or amount <= 0
                        or price <= 0
                    ):
                        await self._mark_borrow_capacity_unavailable(symbol)
                        logger.info(
                            "Auto-push inventory filter rejected %s for account %s: amount=%s price=%s",
                            symbol, self.sub_account_id, amount, price,
                        )
                        continue
                    executable_notional = amount * collateral_ratio * price
                    if executable_notional < minimum:
                        await self._mark_borrow_capacity_unavailable(symbol)
                        logger.info(
                            "Auto-push inventory filter rejected %s for account %s: %.4fU < %.4fU",
                            symbol, self.sub_account_id, executable_notional, minimum,
                        )
                        continue
                    await self._redis.set(
                        ok_key,
                        str(amount),
                        ex=AUTO_PUSH_PREFLIGHT_OK_TTL_SEC,
                    )
                    await self._redis.delete(capacity_key)
                    kept.add(symbol)
                except BinanceAPIError as exc:
                    if exc.api_code == -3045:
                        await self._mark_auto_push_unavailable(symbol)
                        logger.info(
                            "Auto-push inventory filter rejected %s for account %s: Binance -3045",
                            symbol, self.sub_account_id,
                        )
                    else:
                        await self._redis.set(
                            error_key,
                            str(exc.api_code),
                            ex=AUTO_PUSH_PREFLIGHT_ERROR_TTL_SEC,
                        )
                        logger.warning(
                            "Auto-push borrowability check failed for %s account %s: %s",
                            symbol, self.sub_account_id, exc,
                        )
                except Exception as exc:
                    await self._redis.set(
                        error_key,
                        exc.__class__.__name__,
                        ex=AUTO_PUSH_PREFLIGHT_ERROR_TTL_SEC,
                    )
                    logger.warning(
                        "Auto-push borrowability check failed for %s account %s: %s",
                        symbol, self.sub_account_id, exc,
                    )
            finally:
                await self._release_borrow_lock(symbol, lock_token)
        return kept

    async def _add_auto_pushed_symbols(
        self,
        key: str,
        symbols: set[str],
        *,
        expected_rules_generation: int | None = None,
    ) -> tuple[set[str], set[str]]:
        """Add symbols through the shared atomic membership/timestamp helper."""
        if self._redis is None:
            return set(), set()
        if not self._rules_are_current(expected_rules_generation):
            return set(), set()
        scope = self._redis_user_scope()
        expected_key = f"engine:{scope}:pushed_symbols"
        if key != expected_key:
            logger.error("Refusing cross-scope auto-push key %s", key)
            return set(), set()
        current: set[str] = set()
        added: set[str] = set()
        for symbol in sorted(symbols):
            transition_lock = await self._acquire_borrow_lock(
                symbol, ttl_sec=BORROW_LOCK_TTL_SEC
            )
            if transition_lock is None:
                continue
            try:
                if not self._rules_are_current(expected_rules_generation):
                    continue
                current, changed = await mutate_pushed_symbols_async(
                    self._redis,
                    key,
                    add={symbol},
                    add_guard_key=(
                        f"engine:{scope}:removed_cooldown:{symbol}"
                    ),
                )
                if changed:
                    # Automatic pushes start from the global rule snapshot.
                    # An explicit single-symbol/account save removes this
                    # member and re-enables the local override.
                    try:
                        marker_key = auto_global_rules_key(self._user_id)
                        await self._redis.hsetnx(
                            marker_key, symbol, "1"
                        )
                        # A symbol that left and later re-entered the list
                        # starts a fresh automatic-source epoch. Clear stale
                        # account fields for all sibling Workers; otherwise
                        # only the first Worker would reset and a sibling's
                        # old override could control the new push.
                        await clear_auto_global_rule_account_markers_async(
                            self._redis, self._user_id, symbol
                        )
                    except Exception:
                        logger.warning(
                            "Unable to persist automatic rule source for %s",
                            symbol,
                            exc_info=True,
                        )
                    added.add(symbol)
            finally:
                await self._release_borrow_lock(symbol, transition_lock)
        return current, added

    def _load_custom_monitor_infos(self):
        """Read active, tenant-owned custom mappings and apply safety gates."""
        if self._user_id is None:
            return {}
        db = SessionLocal()
        try:
            infos = load_active_custom_monitor_infos(db, int(self._user_id))
            allowed = {}
            for info in infos:
                if custom_monitor_block_reason(db, int(self._user_id), info):
                    continue
                allowed[info.monitor_id] = info
            return allowed
        except Exception:
            logger.warning(
                "Unable to load custom monitor push gates for user %s",
                self._user_id,
                exc_info=True,
            )
            return {}
        finally:
            db.close()

    async def _custom_monitor_auto_candidates(self, threshold: float) -> set[str]:
        """Return fresh custom candidates meeting the user's global threshold."""
        if self._redis is None or self._user_id is None:
            return set()
        try:
            snapshots = await load_user_snapshots(self._redis, self._user_id)
            infos = await asyncio.to_thread(self._load_custom_monitor_infos)
            candidates: set[str] = set()
            for monitor_id, snapshot in snapshots.items():
                info = infos.get(monitor_id)
                if info is None:
                    continue
                if (
                    snapshot.spot_symbol is None
                    or snapshot.futures_symbol is None
                    or str(snapshot.spot_symbol).upper() != info.spot_symbol
                    or str(snapshot.futures_symbol).upper() != info.futures_symbol
                    or str(snapshot.data_status or "").upper() != "LIVE"
                    or not custom_snapshot_is_fresh(snapshot)
                ):
                    continue
                try:
                    spread_short = float(snapshot.spread_short)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(spread_short) or not upward_reached(
                    spread_short, threshold
                ):
                    continue
                candidates.add(custom_monitor_candidate_key(monitor_id))
            return candidates
        except Exception:
            logger.warning(
                "Custom monitor auto-push evaluation failed for user %s",
                self._user_id,
                exc_info=True,
            )
            return set()

    async def _add_custom_monitor_candidates(
        self,
        candidates: set[str],
    ) -> tuple[set[str], set[str]]:
        """Atomically add display-only candidates and preserve their source."""
        if self._redis is None or self._user_id is None or not candidates:
            return set(), set()
        key = f"engine:{self._user_id}:pushed_symbols"
        current, changed = await mutate_pushed_symbols_async(
            self._redis,
            key,
            add={
                str(candidate).strip().upper()
                for candidate in candidates
                if is_custom_monitor_candidate(candidate)
            },
        )
        try:
            marker_key = custom_monitor_source_key(self._user_id)
            mapping = {
                str(candidate).strip().upper(): str(
                    custom_monitor_id_from_candidate(candidate)
                )
                for candidate in candidates
                if is_custom_monitor_candidate(candidate)
            }
            if mapping:
                await self._redis.hset(marker_key, mapping=mapping)
        except Exception:
            logger.warning(
                "Unable to persist custom monitor source metadata for user %s",
                self._user_id,
                exc_info=True,
            )
        added = {
            candidate for candidate in candidates if candidate in current
        }
        return current, added if changed else set()

    async def _auto_push(
        self,
        threshold: float,
        tradable_symbols: set[str],
        *,
        expected_rules_generation: int | None = None,
    ):
        """Add symbols whose spread_short ≥ auto_push_spread to the user's pushed set."""
        try:
            if not self._rules_are_current(expected_rules_generation):
                return
            # Custom mappings use the tenant's same auto_push_spread threshold,
            # but are inserted as namespaced display candidates with no
            # borrowability probe, command queue entry, or trade side effect.
            custom_candidates = await self._custom_monitor_auto_candidates(threshold)
            if custom_candidates:
                current_custom, added_custom = await self._add_custom_monitor_candidates(
                    custom_candidates
                )
                if added_custom:
                    await self._redis.publish("pushed:updates", json.dumps({
                        "user_id": self._user_id,
                        "pushed_symbols": sorted(current_custom),
                        "source": "custom_monitor",
                    }))
            self._shared_removed_bans = await asyncio.to_thread(self._load_shared_removed_bans)
            # pushed_symbols is the dashboard opportunity set. Borrowability
            # is account-specific and is checked only at the execution gate.
            candidates = {
                sym for sym, sp in self.spread_feed.get_all().items()
                if sym in tradable_symbols and sym not in self.config.blacklist  # 黑名单不进推送
                and self._spread_discoverable(sp)
                and upward_reached(sp.spread_short, threshold)
                and self._volume_ok(sym)   # 成交量护栏:低量薄盘不自动推送
                and not self._is_removed_banned(sym)   # 移除/平仓冷却内不重新推送
                and self._spread_fresh(sp)              # 死币(feed 停更/假基差)不自动推
            }
            if not candidates:
                return
            key = f"engine:{self._user_id}:pushed_symbols"
            raw = await self._redis.get(key)
            current = set(json.loads(raw)) if raw else set()
            new = candidates - current
            if not new:
                return
            # P1-6 tick 粒度过滤:一个 tick 的点差步进 > 阈值一半的币剔除(量子化伪点差)
            new = await self._filter_by_tick(new, threshold)
            if not new:
                return
            # 二次确认推送:点差≥confirm_skip_spread 直推;否则等 confirm_delay_sec 复核防抖(防瞬时跳点误推)
            rules = self.config.global_rules
            cd = int(getattr(rules, "confirm_delay_sec", 0) or 0)
            skip = float(getattr(rules, "confirm_skip_spread", 0) or 0)
            immediate, need_confirm = set(), set()
            for sym in new:
                sp = self.spread_feed.get_symbol(sym)
                s = float(sp.spread_short) if sp else 0.0
                if cd <= 0 or (skip > 0 and upward_reached(s, skip)):
                    immediate.add(sym)
                else:
                    need_confirm.add(sym)
            if immediate:
                current, added = await self._add_auto_pushed_symbols(
                    key,
                    immediate,
                    expected_rules_generation=expected_rules_generation,
                )
                # 通知链与手动推送对齐:记首次推送时刻 + publish pushed:updates。
                # 原先只写 Redis 不广播 → 前端(WS pushed_update→refreshPushed)与 BalancePusher
                # (推送即查 maxBorrowable)都收不到,自动推进来的币要手动刷新页面才出现。
                if added:
                    await self._redis.publish("pushed:updates", json.dumps({
                        "user_id": self._user_id, "pushed_symbols": sorted(current),
                    }))
                    logger.info(f"Auto-pushed {len(added)} (spread≥{threshold}, 直推): {sorted(added)[:10]}")
            if need_confirm and cd > 0:
                # Claim delayed confirmations in Redis so repeated cycles or
                # multiple workers cannot accumulate duplicate sleepers.
                claimed = set()
                pending_ttl = max(cd + 5, 30)
                for sym in need_confirm:
                    pending_key = f"engine:{self._user_id}:auto_push_pending:{sym}"
                    try:
                        if await self._redis.set(pending_key, "1", nx=True, ex=pending_ttl):
                            claimed.add(sym)
                    except Exception:
                        claimed.add(sym)
                if claimed:
                    asyncio.create_task(
                        self._confirm_push(
                            claimed,
                            threshold,
                            cd,
                            key,
                            set(tradable_symbols),
                            expected_rules_generation=expected_rules_generation,
                        )
                    )
        except Exception as e:
            logger.debug(f"Auto-push failed: {e}")

    async def _confirm_push(
        self,
        syms: set[str],
        threshold: float,
        cd: int,
        key: str,
        initial_tradable: set[str] | None = None,
        expected_rules_generation: int | None = None,
    ):
        """二次确认:等 cd 秒后复核点差仍≥阈值才推(防瞬时跳点误推)。后台执行,不阻塞主循环。"""
        pending_keys = [f"engine:{self._user_id}:auto_push_pending:{s}" for s in syms]
        try:
            await asyncio.sleep(cd)
            if not self._rules_are_current(expected_rules_generation):
                return
            self._shared_removed_bans = await asyncio.to_thread(self._load_shared_removed_bans)
            tradable = await asyncio.to_thread(self._load_tradable_symbols)
            if initial_tradable:
                tradable &= initial_tradable
            ok = {
                s for s in syms
                if s in tradable
                and s not in self.config.blacklist
                and (sp := self.spread_feed.get_symbol(s))
                and self._spread_discoverable(sp)
                and upward_reached(sp.spread_short, threshold)
                and self._volume_ok(s)
                and not self._is_removed_banned(s)
                and self._spread_fresh(sp)
            }
            if not ok:
                return
            raw = await self._redis.get(key)
            current = set(json.loads(raw)) if raw else set()
            add = ok - current
            if add:
                current, added = await self._add_auto_pushed_symbols(
                    key,
                    add,
                    expected_rules_generation=expected_rules_generation,
                )
                # 与直推分支同款:记推送时刻 + 广播,前端/BalancePusher 实时感知
                if added:
                    await self._redis.publish("pushed:updates", json.dumps({
                        "user_id": self._user_id, "pushed_symbols": sorted(current),
                    }))
                    logger.info(f"Auto-pushed {len(added)} after 2nd-confirm({cd}s): {sorted(added)[:10]}")
        except Exception as e:
            logger.debug(f"confirm_push failed: {e}")
        finally:
            for pending_key in pending_keys:
                try:
                    await self._redis.delete(pending_key)
                except Exception:
                    pass

    async def _borrow_only_repay(
        self,
        symbol: str,
        account_note: str,
        expected_rules_generation: int | None = None,
    ):
        if is_custom_monitor_candidate(symbol):
            return
        from engine.trading.order_executor import execute_borrow_only_repay
        operation_ttl = self._borrow_lock_ttl()
        operation_lock = await self._acquire_account_operation_lock(
            symbol, ttl_sec=operation_ttl
        )
        if operation_lock is None:
            logger.info("Borrow-only repay deferred %s: account operation lock is busy", symbol)
            return
        try:
            if not self._rules_are_current(expected_rules_generation):
                return
            completed = await execute_borrow_only_repay(
                self.sub_account_id, symbol,
                self._trading_client, self._notifier, account_note,
                user_id=self._user_id,
                pre_submit_guard=lambda: self._rules_are_current(
                    expected_rules_generation
                ),
                operation_lock_token=operation_lock,
                operation_lock_redis=self._redis,
                operation_lock_ttl_sec=operation_ttl,
            )
            if completed:
                self._borrow_only_repay_retry_after.pop(symbol, None)
                logger.info(f"Auto repaid borrow-only: {symbol}")
            else:
                self._borrow_only_repay_retry_after[symbol] = (
                    time.monotonic() + REPAY_RETRY_COOLDOWN_SEC
                )
                logger.warning(f"Auto borrow-only repay incomplete: {symbol}")
        except Exception as e:
            self._borrow_only_repay_retry_after[symbol] = (
                time.monotonic() + REPAY_RETRY_COOLDOWN_SEC
            )
            logger.error(f"Auto repay failed {symbol}: {e}")
        finally:
            await self._release_account_operation_lock(symbol, operation_lock)

    def _is_banned(self, symbol: str) -> bool:
        ban_until = self._repay_ban.get(symbol)
        if not ban_until:
            return False
        if datetime.now(timezone.utc) - ban_until < timedelta(minutes=self.config.global_rules.repay_ban_minutes):
            # borrow_spread < 0(负阈值=提前借意图明确)→ 跳过 repay_ban 冷却,允许平仓后立即重借。
            # 正常正阈值策略用冷却防反复开关,但负阈本就代表"基差很差也要借",30min 冷却反而阻碍。
            eff = self._symbol_rule_for_execution(symbol).get("borrow_spread")
            g_bs = getattr(self.config.global_rules, "borrow_spread", None)
            try:
                eff_bs = float(eff if eff is not None else (g_bs or 0))
            except (TypeError, ValueError):
                eff_bs = 0.0
            if eff_bs < 0:
                del self._repay_ban[symbol]
                return False
            return True
        del self._repay_ban[symbol]
        return False

    def _load_account(self) -> dict | None:
        db = SessionLocal()
        try:
            query = db.query(SubAccount).filter(SubAccount.id == self.sub_account_id)
            if self._user_id is None:
                query = query.filter(SubAccount.user_id.is_(None))
            else:
                query = query.filter(SubAccount.user_id == self._user_id)
            account = query.first()
            if not account:
                return None
            return {
                "note": account.note,
                "api_key": account.api_key,
                "api_secret": account.api_secret,
                "user_id": account.user_id,
                "is_enabled": account.is_enabled,
                "max_borrow_amount": account.max_borrow_amount,
                "max_positions": account.max_positions,
                "borrow_rate_per_sec": account.borrow_rate_per_sec,
                "inventory_probe_rate_per_sec": getattr(
                    account, "inventory_probe_rate_per_sec", None
                ),
            }
        finally:
            db.close()

    def _read_account_runtime(self) -> dict | None:
        """Read the account gate and cached fund controls in one DB round trip."""
        db = SessionLocal()
        try:
            query = db.query(SubAccount).filter(SubAccount.id == self.sub_account_id)
            if self._user_id is None:
                query = query.filter(SubAccount.user_id.is_(None))
            else:
                query = query.filter(SubAccount.user_id == self._user_id)
            account = query.first()
            if account is None:
                return None
            return {
                "is_enabled": bool(account.is_enabled),
                "max_borrow_amount": account.max_borrow_amount,
                "max_positions": account.max_positions,
                "borrow_rate_per_sec": account.borrow_rate_per_sec,
                "inventory_probe_rate_per_sec": getattr(
                    account, "inventory_probe_rate_per_sec", None
                ),
            }
        except Exception as exc:
            # Fail closed for opening when the account gate cannot be read.
            logger.warning("Account runtime check failed for %s: %s", self.sub_account_id, exc)
            return None
        finally:
            db.close()

    async def _refresh_account_runtime(self, now_mono: float | None = None) -> None:
        """Refresh mutable account controls at most once every three seconds."""
        checked_at = time.monotonic() if now_mono is None else now_mono
        if checked_at - self._account_enabled_checked_at < 3:
            return
        runtime = await asyncio.to_thread(self._read_account_runtime)
        self._account_enabled_checked_at = checked_at
        if runtime is None:
            self._account_opening_enabled = False
            return
        self._account_opening_enabled = runtime["is_enabled"]
        self._account_max_borrow = runtime["max_borrow_amount"]
        self._account_max_positions = runtime["max_positions"]
        self._account_borrow_rate = runtime["borrow_rate_per_sec"]
        self._account_inventory_probe_rate = runtime[
            "inventory_probe_rate_per_sec"
        ]

    def _read_account_enabled(self) -> bool:
        """Compatibility helper for diagnostics that only need the gate."""
        runtime = self._read_account_runtime()
        return bool(runtime and runtime["is_enabled"])

    async def _rules_reload_listener(self):
        """事件驱动 0 秒规则热重载:订阅 rules:reload:{user_id},收到即重载全局及单一规则。
        Redis 异常自动重连重订阅(while True 外层兜底),不影响主循环 3s 轮询兜底。"""
        while self._running:
            try:
                pubsub = self._redis.pubsub()
                ch = f"rules:reload:{self._user_id}"
                await pubsub.subscribe(ch)
                logger.info(f"Worker {self.sub_account_id} subscribed {ch} for instant rule reload")
                async for msg in pubsub.listen():
                    if not self._running:
                        break
                    if msg.get("type") != "message":
                        continue
                    try:
                        # save-all updates GlobalRules, while symbol/account
                        # endpoints update the override tables. Reload both so
                        # one event has identical semantics for every caller.
                        await self._reload_rule_snapshots(fence_current_cycle=True)
                        self._rules_reload_event.set()
                        logger.info(f"Worker {self.sub_account_id}: rules reloaded (event-driven, 0s)")
                    except Exception as e:
                        logger.warning(f"event rule reload failed: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"rules_reload_listener error (resubscribe in 2s): {e}")
                await asyncio.sleep(2)

    def _pushed_update_matches(self, message) -> bool:
        """Return whether a Redis pushed-list event belongs to this tenant."""
        if not isinstance(message, dict):
            return False
        channel = message.get("channel")
        if isinstance(channel, bytes):
            channel = channel.decode(errors="replace")
        if channel not in (None, "pushed:updates"):
            return False
        raw = message.get("data")
        if isinstance(raw, bytes):
            raw = raw.decode(errors="replace")
        try:
            payload = raw if isinstance(raw, dict) else json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict) or "user_id" not in payload:
            # An unscoped event must never wake every tenant's Worker.
            return False
        event_user = payload.get("user_id")
        expected_user = self._user_id
        if event_user is None or expected_user is None:
            return event_user is None and expected_user is None
        try:
            return int(event_user) == int(expected_user)
        except (TypeError, ValueError):
            return False

    async def _pushed_symbols_listener(self):
        """Wake the decision loop when this tenant's pushed list changes."""
        while self._running:
            pubsub = None
            try:
                if self._redis is None:
                    await asyncio.sleep(2)
                    continue
                pubsub = self._redis.pubsub()
                subscribed = pubsub.subscribe("pushed:updates")
                if hasattr(subscribed, "__await__"):
                    await subscribed
                logger.info(
                    "Worker %s subscribed pushed:updates for candidate refresh",
                    self.sub_account_id,
                )
                stream = pubsub.listen()
                if hasattr(stream, "__await__"):
                    stream = await stream
                async for message in stream:
                    if not self._running:
                        break
                    if not isinstance(message, dict):
                        continue
                    if message.get("type") not in ("message", b"message"):
                        continue
                    if self._pushed_update_matches(message):
                        self._pushed_symbols_event.set()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(
                    "pushed_symbols_listener error (resubscribe in 2s): %s", exc
                )
                await asyncio.sleep(2)
            finally:
                if pubsub is not None:
                    for name in ("aclose", "close"):
                        closer = getattr(pubsub, name, None)
                        if not callable(closer):
                            continue
                        try:
                            result = closer()
                            if hasattr(result, "__await__"):
                                await result
                        except Exception:
                            pass
                        break

    def _rules_are_current(self, expected_generation: int | None) -> bool:
        """Fence side effects produced by a decision snapshot that was replaced."""
        return (
            expected_generation is None
            or expected_generation == self._rules_generation
        )

    async def _reload_rule_snapshots(self, *, fence_current_cycle: bool) -> None:
        """Reload both rule layers without exposing a half-updated snapshot."""
        async with self._rules_state_lock:
            if fence_current_cycle:
                # Event reloads can overlap an active cycle. Invalidate its
                # token before either blocking database read can yield.
                self._rules_generation += 1
            await asyncio.to_thread(self.config._reload)
            await asyncio.to_thread(self._load_symbol_rules)
            if fence_current_cycle:
                # Fund controls live on SubAccount rather than in either rule
                # snapshot. Force the event-woken cycle to reload them instead
                # of honoring the normal three-second polling cache.
                self._account_enabled_checked_at = 0.0

    async def _wait_for_next_cycle(self, timeout: float = 1.0) -> None:
        """Wait for cadence, control-plane changes, or an inventory edge."""
        wake_events = (
            self._rules_reload_event,
            self._pushed_symbols_event,
            self._inventory_ready_event,
        )
        if any(event.is_set() for event in wake_events):
            self._rules_reload_event.clear()
            self._pushed_symbols_event.clear()
            self._inventory_ready_event.clear()
            return
        rules_wait = asyncio.create_task(self._rules_reload_event.wait())
        pushed_wait = asyncio.create_task(self._pushed_symbols_event.wait())
        inventory_wait = asyncio.create_task(self._inventory_ready_event.wait())
        try:
            done, pending = await asyncio.wait(
                {rules_wait, pushed_wait, inventory_wait},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (rules_wait, pushed_wait, inventory_wait):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                rules_wait, pushed_wait, inventory_wait, return_exceptions=True
            )
        if rules_wait in done:
            self._rules_reload_event.clear()
        if pushed_wait in done:
            self._pushed_symbols_event.clear()
        if inventory_wait in done:
            self._inventory_ready_event.clear()

    async def _naked_short_loop(self, account_note: str):
        """裸空安全网循环:每 NAKED_CHECK_INTERVAL 秒对账一次币安真实债务,孤儿债务(借币未对冲)
        即告警(跑马灯+飞书)+ 自动买回还币收口。独立兜底,异常不影响主循环;trading_client 与主循环
        共享(httpx 并发安全)。见 engine/fund/reconcile_checker.run_naked_short_guard。"""
        from engine.fund.reconcile_checker import run_naked_short_guard
        await asyncio.sleep(5)   # 启动稍延迟,避开冷启动 position 尚未载入窗口
        while self._running:
            try:
                if self._trading_client is not None:
                    await run_naked_short_guard(
                        self._trading_client, self._redis, self.sub_account_id,
                        self._user_id, self._notifier, account_note,
                        auto_remediate=AUTO_REMEDIATE,
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"naked_short_guard error: {e}")
            await asyncio.sleep(NAKED_CHECK_INTERVAL)

    def _load_symbol_rules(self):
        db = SessionLocal()
        try:
            rules_map = {}
            q = db.query(SymbolRule)
            if self._user_id is None:
                q = q.filter(SymbolRule.user_id.is_(None))
            else:
                q = q.filter(SymbolRule.user_id == self._user_id)
            # Older imports stored a bare asset (``FIL``) while the market
            # feed and API use ``FILUSDT``.  Collapse those aliases before
            # applying account overrides, preferring an explicitly canonical
            # row over its legacy alias and then the newest row deterministically.
            selected_symbol_rows: dict[str, SymbolRule] = {}
            for sr in sorted(q.all(), key=lambda row: int(getattr(row, "id", 0) or 0)):
                key = _canonical_symbol_key(getattr(sr, "symbol", None))
                if not key:
                    continue
                current = selected_symbol_rows.get(key)
                raw = str(getattr(sr, "symbol", "") or "").strip().upper()
                current_raw = (
                    str(getattr(current, "symbol", "") or "").strip().upper()
                    if current is not None
                    else ""
                )
                if current is None or raw == key or current_raw != key:
                    selected_symbol_rows[key] = sr

            for key, sr in selected_symbol_rows.items():
                entry = {
                    "allow_repay": sr.allow_repay,
                    "allow_remove": sr.allow_remove,
                    "remove_spread": sr.remove_spread,
                    "source": sr.source,
                }
                if sr.max_borrow_amount is not None:
                    entry["max_borrow_amount"] = sr.max_borrow_amount
                # 逐币阈值基线(仅非 NULL 才写 → 空=跟随全局);引擎开/平/还/借循环按币覆盖全局
                for k in ("open_spread", "borrow_spread", "close_spread", "order_amount", "open_order_amount", "close_funding_ratio",
                          "repay_spread", "repay_funding_ratio"):
                    val = getattr(sr, k, None)
                    if val is not None:
                        entry[k] = val
                rules_map[key] = entry
            # account-level overrides —— 逐账户规则【可独立存在】:即便该币没有 user 级 SymbolRule,
            # 逐账户「单一规则」(挂单点差/开/平/还…)也必须生效。
            # 此前用 `if key in rules_map` 守卫,导致"只在某子账户设了规则、却无配套 user 级 SymbolRule"
            # 的币被整条静默丢弃 —— 实测 hustle-011(sub9) 给 FILUSDT 设 borrow_spread=-1,因 FIL 无
            # user 级规则而被丢 → eff_borrow 回退全局 0.5 → spread_short=0 < 0.5 → 永不借。
            # 改为 setdefault 先建空基线再覆盖:有 SymbolRule 则在其上叠加(同旧),无则账户规则独立成行。
            account_rule_query = db.query(AccountSymbolRule).filter(
                AccountSymbolRule.sub_account_id == self.sub_account_id,
            )
            # AccountSymbolRule historically allowed nullable ownership.  Once
            # this worker has resolved its tenant, a rule from another tenant
            # must never override its local snapshot.  Unknown-tenant legacy
            # workers are restricted to explicitly unowned rows and therefore
            # fail closed instead of guessing an owner.
            if self._user_id is None:
                account_rule_query = account_rule_query.filter(
                    AccountSymbolRule.user_id.is_(None)
                )
            else:
                account_rule_query = account_rule_query.filter(
                    AccountSymbolRule.user_id == self._user_id
                )
            selected_account_rows: dict[str, AccountSymbolRule] = {}
            for ar in sorted(
                account_rule_query.all(),
                key=lambda row: int(getattr(row, "id", 0) or 0),
            ):
                key = _canonical_symbol_key(getattr(ar, "symbol", None))
                if not key:
                    continue
                current = selected_account_rows.get(key)
                raw = str(getattr(ar, "symbol", "") or "").strip().upper()
                current_raw = (
                    str(getattr(current, "symbol", "") or "").strip().upper()
                    if current is not None
                    else ""
                )
                if current is None or raw == key or current_raw != key:
                    selected_account_rows[key] = ar

            for key, ar in selected_account_rows.items():
                entry = rules_map.setdefault(key, {})
                if ar.remove_spread is not None:
                    entry["remove_spread"] = ar.remove_spread
                if ar.is_enabled is not None:
                    entry["account_enabled"] = ar.is_enabled
                if ar.max_borrow_amount is not None:
                    entry["max_borrow_amount"] = ar.max_borrow_amount
                # 逐账户阈值覆盖(优先于逐币基线;NULL 不覆盖)
                for k in ("open_spread", "borrow_spread", "close_spread", "order_amount", "open_order_amount", "close_funding_ratio",
                          "repay_spread", "repay_funding_ratio"):
                    val = getattr(ar, k, None)
                    if val is not None:
                        entry[k] = val
            self._symbol_rules = rules_map
        finally:
            db.close()

    async def _refresh_auto_global_rule_symbols(self, pushed_symbols) -> None:
        """Refresh automatic-source rule inheritance for this tenant.

        The hash is advisory metadata written alongside pushed-list changes.
        A Redis read failure retains the previous snapshot rather than
        weakening an already-known global-only gate during a transient outage.
        Symbols no longer in the pushed list are discarded locally even when
        their stale hash field has not yet been cleaned by an older Worker.
        """
        if self._redis is None:
            self._auto_global_rule_symbols.clear()
            return
        pushed = {
            _canonical_symbol_key(symbol)
            for symbol in (pushed_symbols or ())
            if not is_custom_monitor_candidate(symbol)
            and _canonical_symbol_key(symbol)
        }
        try:
            values: set[str] = set()
            marker_key = auto_global_rules_key(self._user_id)
            for symbol in pushed:
                marker = await self._redis.hget(marker_key, symbol)
                account_override = await self._redis.hget(
                    marker_key,
                    auto_global_rule_account_field(self.sub_account_id, symbol),
                )
                if marker and not account_override:
                    values.add(symbol)
            self._auto_global_rule_symbols = values
        except Exception:
            logger.warning(
                "Unable to refresh automatic rule source metadata; retaining prior snapshot",
                exc_info=True,
            )
            self._auto_global_rule_symbols.intersection_update(pushed)

    def _symbol_rule_for_execution(self, symbol: str) -> dict:
        """Return the effective local rule layer for execution decisions.

        Automatic pushes intentionally begin with global parameters.  Keep the
        account enable switch as a safety gate, but defer all threshold,
        amount, removal, and repay overrides until an explicit rule save clears
        the automatic-source marker.
        """
        normalized = _canonical_symbol_key(symbol)
        rule = self._symbol_rules.get(normalized) if normalized else None
        if rule is None:
            rule = self._symbol_rules.get(symbol, {})
        if normalized in self._auto_global_rule_symbols:
            return {
                key: value
                for key, value in (rule or {}).items()
                if key == "account_enabled"
            }
        return rule or {}

    def _spread_sane(self, spread) -> bool:
        """行情 glitch 护栏: 价格非正 / 点差幅度超过 max_spread_pct 时判定为坏数据,
        跳过该币种本轮所有下单/平仓决策(canary 实测 CRV 点差瞬时 6.6% 触发误开仓)。
        max_spread_pct=0 时关闭护栏(沿用原行为)。"""
        if spread is None:
            return False
        try:
            if (spread.spot_ask <= 0 or spread.spot_bid <= 0 or
                    spread.fut_ask <= 0 or spread.fut_bid <= 0):
                self._note_glitch(spread.symbol, "non-positive price")
                return False
            ceiling = float(getattr(self.config.global_rules, "max_spread_pct", 3.0) or 0)
            if ceiling > 0 and (abs(float(spread.spread_short)) > ceiling or
                                abs(float(spread.spread_long)) > ceiling):
                self._note_glitch(spread.symbol,
                                  f"spread {spread.spread_short}/{spread.spread_long}% > {ceiling}%")
                return False
        except Exception:
            return False
        return True

    def _spread_fresh(self, spread) -> bool:
        """Require both Rust WS legs to have been received recently.

        ``SpreadSnapshot.ts`` is Binance's exchange event time and can remain
        old for a quiet symbol even while the socket is healthy.  The Rust
        publisher records ``spot_recv_ts_ms`` and ``fut_recv_ts_ms`` locally;
        the shared helper rejects missing/legacy fields and future-skewed
        timestamps, so no execution path can silently fall back to ``ts``.
        """
        return is_spread_fresh(spread, max_age_ms=SPREAD_FRESH_MS)

    def _note_glitch(self, symbol: str, reason: str):
        """每币种每 60s 最多记一条 glitch 日志,避免刷屏。"""
        now = datetime.now(timezone.utc)
        last = self._glitch_logged.get(symbol)
        if not last or (now - last).total_seconds() > 60:
            self._glitch_logged[symbol] = now
            logger.warning(f"行情护栏: 跳过 {symbol} (坏数据: {reason})")

    def _sym_threshold(self, symbol: str, key: str, global_val):
        """逐币/逐账户阈值覆盖解析: _symbol_rules[symbol][key] 已是 account>symbol 合并值
        (见 _load_symbol_rules);缺失/None → 回退 global_val。返回 Decimal,与全局快照同型,
        保持纯 Decimal 比较。空=跟随全局,0 视为有效覆盖值。"""
        rule = self._symbol_rule_for_execution(symbol)
        v = rule.get(key)
        return v if v is not None else global_val

    def _repay_is_immediate(self, symbol: str, rules) -> bool:
        """Return whether a completed close may repay without a quote gate.

        A configured positive ``repay_spread`` is an explicit request to hold
        the debt until that trigger (or its funding trigger) is reached.  The
        close path must therefore not call ``execute_repay`` inline in that
        case; the normal ``PENDING_REPAY`` branch evaluates the configured
        trigger on the next cycle.  Missing or non-positive values retain the
        existing immediate-repay behavior.
        """
        configured = self._sym_threshold(
            symbol,
            "repay_spread",
            getattr(rules, "repay_spread", None),
        )
        if configured is None:
            return True
        try:
            return Decimal(str(configured)) <= 0
        except (TypeError, ValueError, ArithmeticError):
            # An invalid override must fail closed rather than bypassing the
            # user's repayment trigger.
            return False

    def _is_repay_allowed(self, symbol: str) -> bool:
        rule = self._symbol_rule_for_execution(symbol)
        if rule is None:
            # Keep legacy in-memory snapshots readable while DB-loaded rules
            # use canonical USDT pair keys.
            rule = {}
        if not rule:
            return True
        # Historical rows may contain NULL; NULL means "inherit/allowed", not
        # a falsey hard stop.
        return rule.get("allow_repay") is not False

    def _is_repay_banned(self, position_or_symbol) -> bool:
        """Apply the configured post-borrow auto-repay delay exactly.

        ``repay_ban_minutes`` is exposed as a duration. The former UTC-hour
        alignment silently extended it by up to 59 minutes, so an OPEN
        position could satisfy its effective close spread and still appear
        stuck. Interest-aware strategies can set the duration explicitly; the
        engine must not add another hidden threshold.

        OPEN positions use their persisted creation timestamp so a Worker
        restart cannot erase the delay and a later bite of the same symbol
        cannot restart an older Position's clock. The symbol-level in-memory
        timestamp is retained only as a compatibility fallback for legacy
        objects without ``created_at``.
        """
        if isinstance(position_or_symbol, str):
            symbol = position_or_symbol
            last_borrow = None
        else:
            symbol = str(getattr(position_or_symbol, "symbol", "") or "")
            last_borrow = (
                getattr(position_or_symbol, "opened_at", None)
                or getattr(position_or_symbol, "borrowed_at", None)
                or getattr(position_or_symbol, "created_at", None)
            )
        if last_borrow is None:
            last_borrow = self._last_borrow_at.get(symbol)
        if not last_borrow:
            return False
        if last_borrow.tzinfo is None:
            last_borrow = last_borrow.replace(tzinfo=timezone.utc)
        ban_min = self.config.global_rules.repay_ban_minutes
        if ban_min is None or ban_min <= 0:
            return False
        now = datetime.now(timezone.utc)
        return now < last_borrow + timedelta(minutes=ban_min)

    # Compatibility for diagnostics/tests that used the old misleading name.
    def _is_borrow_banned(self, position_or_symbol) -> bool:
        return self._is_repay_banned(position_or_symbol)

    def _is_removed_banned(self, symbol: str) -> bool:
        """移除/平仓冷却: 同币退出后 removed_cooldown_minutes 分钟内禁止再借(0=不启用)。"""
        mins = int(getattr(self.config.global_rules, "removed_cooldown_minutes", 0) or 0)
        if mins <= 0:
            return False
        if symbol in self._shared_removed_bans:
            return True
        ts = self._removed_ban.get(symbol)
        if not ts:
            return False
        if (datetime.now(timezone.utc) - ts).total_seconds() >= mins * 60:
            self._removed_ban.pop(symbol, None)
            return False
        return True

    @staticmethod
    def _spread_discoverable(spread) -> bool:
        """Validate an opportunity quote without authorizing a trade.

        ``max_spread_pct`` is an execution glitch guard. Reusing it for
        discovery silently hid genuine large gaps such as TUT around 6%.
        Discovery only requires finite positive books and finite spreads;
        ``_spread_sane`` is still enforced before every borrow/hedge action.
        """
        if spread is None:
            return False
        try:
            prices = (
                Decimal(str(spread.spot_ask)),
                Decimal(str(spread.spot_bid)),
                Decimal(str(spread.fut_ask)),
                Decimal(str(spread.fut_bid)),
            )
            values = (
                Decimal(str(spread.spread_short)),
                Decimal(str(spread.spread_long)),
            )
            return (
                all(value.is_finite() and value > 0 for value in prices)
                and all(value.is_finite() for value in values)
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _has_incremental_borrow_room(
        self,
        symbol: str,
        spread,
        positions: list[Position],
        *,
        allow_cap_tail: bool = False,
    ) -> bool:
        """Return whether an explicit cumulative cap permits another bite.

        This is a cheap DB-position gate only. ``execute_borrow`` repeats the
        decision with Binance's authoritative principal under the account
        operation lock, so a stale Position can never weaken the hard cap.
        """
        rule = self._symbol_rule_for_execution(symbol)
        cap_raw = rule.get("max_borrow_amount", self._account_max_borrow)
        if cap_raw is None or spread is None:
            return False
        try:
            cap = Decimal(str(cap_raw))
            price = Decimal(str(spread.spot_ask))
            if not cap.is_finite() or cap <= 0 or not price.is_finite() or price <= 0:
                return False
            principal = sum(
                (
                    Decimal(str(position.borrow_qty or 0))
                    for position in positions
                    if position.symbol == symbol
                ),
                Decimal("0"),
            )
            recorded_notional = Decimal("0")
            for position in positions:
                if position.symbol != symbol:
                    continue
                raw = getattr(position, "borrow_usdt_amount", None)
                if raw is None:
                    continue
                value = Decimal(str(raw))
                if not value.is_finite() or value < 0:
                    return False
                recorded_notional += value
            used_cap = max(recorded_notional, principal * price)
            remaining = cap - used_cap
            minimum = Decimal(str(
                getattr(self.config.global_rules, "min_borrow_usdt", 0) or 0
            ))
            if remaining <= 0:
                return False
            if allow_cap_tail:
                return True
            return remaining >= max(Decimal("5.5"), minimum)
        except (AttributeError, TypeError, ValueError):
            return False

    async def _set_removed_ban(self, symbol: str, *, persist: bool = True) -> None:
        """Arm the post-removal cooldown for every Worker owned by this user."""
        self._removed_ban[symbol] = datetime.now(timezone.utc)
        self._shared_removed_bans.add(symbol)
        mins = int(getattr(self.config.global_rules, "removed_cooldown_minutes", 0) or 0)
        if not persist or mins <= 0 or not self._redis:
            return
        try:
            await self._redis.setex(
                f"engine:{self._redis_user_scope()}:removed_cooldown:{symbol}",
                mins * 60,
                "1",
            )
        except Exception:
            logger.warning("Failed to persist removed cooldown for %s", symbol, exc_info=True)

    def _load_shared_removed_bans(self) -> set[str]:
        r = None
        try:
            import redis as _redis_sync
            r = _redis_sync.from_url(settings.redis_url, decode_responses=True)
            prefix = f"engine:{self._redis_user_scope()}:removed_cooldown:"
            keys = _scan_keys(r, f"{prefix}*")
            return {key[len(prefix):] for key in keys if key.startswith(prefix)}
        except Exception:
            return set()
        finally:
            if r is not None:
                try:
                    r.close()
                except Exception:
                    logger.debug("Unable to close synchronous Redis client", exc_info=True)

    def _load_tradable_symbols(self) -> set[str]:
        db = SessionLocal()
        try:
            q = db.query(Symbol.symbol, Symbol.volume_24h, Symbol.futures_volume_24h).filter(
                Symbol.is_active == True,
                Symbol.margin_tradable == True,
                Symbol.futures_tradable == True,
                Symbol.allow_open == True,        # /coins「允许开仓」硬门:禁止开仓的币不进可交易集
                Symbol.is_delisting == False,     # 下架中的币不开
            )
            if bool(getattr(self.config.global_rules, "block_risky_open", False)):
                q = q.filter(Symbol.is_risky == False)   # 可选硬拦:开启后风险币也不开
            rows = q.all()
            # 同时刷新现货/合约成交量 map(双腿量过滤:低量币不自动推送/借币)
            self._symbol_volumes = {r.symbol: float(r.volume_24h or 0) for r in rows}
            self._symbol_futures_volumes = {r.symbol: float(r.futures_volume_24h or 0) for r in rows}
            return {r.symbol for r in rows}
        finally:
            db.close()

    def _volume_ok(self, symbol: str) -> bool:
        """双腿 24h 成交量护栏:现货<min_volume_24h 或 合约<min_volume_24h_futures 的薄盘币
        不参与自动推送/借币(各自 0=该腿不启用)。"""
        min_spot = float(getattr(self.config.global_rules, "min_volume_24h", 0) or 0)
        if min_spot > 0 and self._symbol_volumes.get(symbol, 0) < min_spot:
            return False
        min_fut = float(getattr(self.config.global_rules, "min_volume_24h_futures", 0) or 0)
        if min_fut > 0 and self._symbol_futures_volumes.get(symbol, 0) < min_fut:
            return False
        return True

    def _spread_persisted(self, symbol: str, value: float, threshold: float) -> bool:
        """Require the borrow spread to remain at or above its threshold."""
        if not upward_reached(value, threshold):
            self._above_since.pop(symbol, None)
            return False
        dur_ms = int(getattr(self.config.global_rules, "filter_duration_ms", 0) or 0)
        if dur_ms <= 0:
            return True
        now = datetime.now(timezone.utc)
        since = self._above_since.get(symbol)
        if since is None:
            self._above_since[symbol] = now
            return False
        return (now - since).total_seconds() * 1000 >= dur_ms

    def _load_open_positions(self) -> list[Position]:
        db = SessionLocal()
        try:
            return db.query(Position).filter(
                Position.sub_account_id == self.sub_account_id,
                Position.status == "OPEN",
            ).order_by(Position.created_at.asc(), Position.id.asc()).all()
        finally:
            db.close()

    def _load_positions_by_status(self, status: str) -> list[Position]:
        db = SessionLocal()
        try:
            return db.query(Position).filter(
                Position.sub_account_id == self.sub_account_id,
                Position.status == status,
            ).all()
        finally:
            db.close()

    def _reclaim_stale_pending_borrow(self) -> int:
        """Recover stale borrow rows without guessing a submitted outcome.

        ``PENDING_BORROW`` has not crossed the exchange submission boundary and
        can become FAILED. ``BORROW_SUBMITTING`` was committed immediately
        before network I/O; after a restart it must become
        ``BORROW_OUTCOME_UNKNOWN`` and continue blocking retries.
        """
        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_PENDING_BORROW_SEC)
            candidates = db.query(Position).filter(
                Position.sub_account_id == self.sub_account_id,
                Position.status.in_(("PENDING_BORROW", "BORROW_SUBMITTING")),
            ).all()
            # Top-up reuses an older BORROWED_IDLE row, so ``created_at`` may
            # be hours/days old even though its submission boundary was just
            # committed. Age the recovery window from the latest lifecycle
            # update and fall back to creation time only for legacy rows.
            stale = []
            for position in candidates:
                anchor = getattr(position, "updated_at", None) or getattr(
                    position, "created_at", None
                )
                if anchor is None:
                    stale.append(position)
                    continue
                if getattr(anchor, "tzinfo", None) is None:
                    anchor = anchor.replace(tzinfo=timezone.utc)
                if anchor < cutoff:
                    stale.append(position)
            failed_count = 0
            unknown_count = 0
            for p in stale:
                if p.status == "BORROW_SUBMITTING":
                    p.status = "BORROW_OUTCOME_UNKNOWN"
                    p.error_message = (
                        f"{p.error_message or 'Borrow submission interrupted'}; "
                        "engine restarted before outcome reconciliation"
                    )
                    unknown_count += 1
                else:
                    p.status = "FAILED"
                    p.error_message = "stale PENDING_BORROW reclaimed (engine restart in borrow window)"
                    failed_count += 1
            if stale:
                db.commit()
                logger.warning(
                    "Sub-account %s: recovered %s stale borrow rows "
                    "(pending->failed=%s, submitting->unknown=%s; symbols=%s)",
                    self.sub_account_id,
                    len(stale),
                    failed_count,
                    unknown_count,
                    ", ".join(sorted({p.symbol for p in stale})),
                )
            return len(stale)
        except Exception as e:
            db.rollback()
            logger.error(f"reclaim_stale_pending_borrow failed (acct {self.sub_account_id}): {e}")
            return 0
        finally:
            db.close()

    async def _recover_stale_repaying(self) -> int:
        """Recover crashed repayment claims after authoritative flat checks.

        The helper is shared with the manual partial-repay endpoint so both
        paths use the same age/leg/order guards.  Reuse this worker's already
        open margin client and the user-scoped master client when applicable;
        no additional quote REST calls are introduced.  The account-operation
        lock is held for the complete exchange-read plus DB-CAS window, so a
        manual action cannot race a recovery decision.
        """
        if self._trading_client is None or self._redis is None:
            return 0
        db = SessionLocal()
        try:
            owner = (
                SubAccount.user_id.is_(None)
                if self._user_id is None
                else SubAccount.user_id == self._user_id
            )
            account = db.query(SubAccount).filter(
                SubAccount.id == self.sub_account_id,
                owner,
            ).first()
            if not account:
                return 0

            rows = db.query(Position).filter(
                Position.sub_account_id == self.sub_account_id,
                Position.status == "REPAYING",
            ).all()
            symbols = sorted({
                str(getattr(row, "symbol", "") or "").strip().upper()
                for row in rows
                if str(getattr(row, "symbol", "") or "").strip()
            })
            if not symbols:
                return 0

            from app.api.engine_api import _recover_stale_repaying_positions
            def _legacy_row_needs_master(row) -> bool:
                if getattr(row, "hedge_account", None):
                    return str(getattr(row, "hedge_account", "")).lower() == "master"
                # A missing route plus malformed/non-finite leg data is
                # treated as evidence requiring the extra safety read.  The
                # recovery helper will still fail closed if the read cannot
                # prove flatness.
                for field in ("spot_sell_qty", "futures_long_qty", "spot_buy_qty"):
                    try:
                        value = Decimal(str(getattr(row, field, 0) or 0))
                        if not value.is_finite() or abs(value) > Decimal("0.00000001"):
                            return True
                    except Exception:
                        return True
                for field in ("spot_sell_order_id", "futures_long_order_id",
                              "futures_close_order_id", "spot_buy_order_id"):
                    if str(getattr(row, field, None) or "").strip():
                        return True
                return False
            recovered = 0
            for symbol in symbols:
                # Recovery is a balance/lifecycle operation just like repay.
                # Never perform the exchange reads or CAS while another worker
                # or API request owns this account/asset lock.
                operation_lock = await self._acquire_account_operation_lock(symbol)
                if operation_lock is None:
                    continue
                try:
                    master_client = None
                    if any(
                        _legacy_row_needs_master(row)
                        and str(getattr(row, "symbol", "") or "").strip().upper() == symbol
                        for row in rows
                    ):
                        from engine.trading.master_client import get_master_futures_client
                        master_client = await get_master_futures_client(self._user_id)
                    recovered += await _recover_stale_repaying_positions(
                        db,
                        user_id=self._user_id,
                        account=account,
                        symbol=symbol,
                        margin_client=self._trading_client,
                        futures_client=master_client,
                    )
                finally:
                    await self._release_account_operation_lock(symbol, operation_lock)
            if recovered:
                logger.warning(
                    "Sub-account %s: recovered %s stale REPAYING row(s)",
                    self.sub_account_id,
                    recovered,
                )
            return recovered
        except Exception as exc:
            db.rollback()
            logger.warning(
                "recover_stale_repaying failed (acct %s): %s",
                self.sub_account_id,
                exc,
            )
            return 0
        finally:
            db.close()

    def _load_stale_transitional_positions(self) -> list[Position]:
        """Load only crash-recovery candidates for this owned account."""
        from engine.trading.order_executor import TRANSITIONAL_POSITION_STATUSES, TRANSITIONAL_RECOVERY_STALE_SEC
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=TRANSITIONAL_RECOVERY_STALE_SEC)
        db = SessionLocal()
        try:
            rows = db.query(Position).filter(
                Position.sub_account_id == self.sub_account_id,
                Position.status.in_(TRANSITIONAL_POSITION_STATUSES),
            ).all()
            out = []
            for row in rows:
                stamp = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
                if stamp is None:
                    continue
                if getattr(stamp, "tzinfo", None) is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                if stamp <= cutoff:
                    out.append(row)
            return out
        finally:
            db.close()

    async def _recover_stale_transitional_positions(self, account_note: str) -> int:
        """Reconcile interrupted hedge/close phases without guessing outcomes."""
        if self._trading_client is None or self._redis is None:
            return 0
        # Older/lightweight clients that do not expose the authoritative
        # futures readers cannot safely participate in recovery.  Return
        # before touching the database; this also keeps rolling upgrades
        # isolated from the normal borrow decision path.
        if not any(
            callable(getattr(self._trading_client, method, None))
            for method in ("get_futures_position", "futures_position_risk")
        ):
            return 0
        try:
            from engine.trading.order_executor import recover_interrupted_position
            rows = await asyncio.to_thread(self._load_stale_transitional_positions)
        except Exception:
            logger.warning(
                "Unable to load stale transitional positions for account %s",
                self.sub_account_id,
                exc_info=True,
            )
            return 0
        recovered = 0
        for row in rows:
            symbol = str(getattr(row, "symbol", "") or "").upper()
            if not symbol:
                continue
            operation_ttl = self._borrow_lock_ttl()
            token = await self._acquire_account_operation_lock(
                symbol, ttl_sec=operation_ttl
            )
            if token is None:
                continue
            try:
                route = str(getattr(row, "hedge_account", "") or "").strip().lower()
                futures_client = self._trading_client
                if route == "master":
                    from engine.trading.master_client import get_master_futures_client
                    futures_client = await get_master_futures_client(self._user_id)
                elif route != "sub":
                    logger.error(
                        "Interrupted position %s/%s has unknown hedge route %r; held",
                        self.sub_account_id,
                        symbol,
                        getattr(row, "hedge_account", None),
                    )
                    continue
                async with self._master_symbol_operation(
                    symbol,
                    operation_ttl,
                    force_master=(route == "master"),
                ) as coordinated:
                    if not coordinated:
                        continue
                    action = await recover_interrupted_position(
                        int(row.id),
                        sub_account_id=self.sub_account_id,
                        user_id=self._user_id,
                        margin_client=self._trading_client,
                        futures_client=futures_client,
                        notifier=self._notifier,
                        account_note=account_note,
                        operation_lock_token=token,
                        operation_lock_redis=self._redis,
                        operation_lock_ttl_sec=operation_ttl,
                    )
                if action:
                    recovered += 1
                    logger.warning(
                        "Recovered interrupted position %s %s: %s",
                        symbol,
                        row.id,
                        action,
                    )
            except Exception:
                # Recovery is a safety net. A failed read/action must not
                # terminate the worker or open a new position on stale data.
                logger.warning(
                    "Interrupted position recovery failed %s/%s",
                    self.sub_account_id,
                    symbol,
                    exc_info=True,
                )
            finally:
                await self._release_account_operation_lock(symbol, token)
        return recovered

    # P1: transient/holding statuses -> explicit lifecycle labels for the
    # dashboard. Keep the spot and master-futures legs distinguishable so
    # an operator can tell exactly where a cross-account hedge is waiting.
    _EXEC_STATUS_MAP = {
        "BORROW_OUTCOME_UNKNOWN": "借币待核对",
        "BORROW_SUBMITTING": "借币中",
        "PENDING_BORROW": "排队中",
        "BORROWED": "已借币待卖现货",
        "BORROWED_IDLE": "已借币待卖现货",
        "HEDGING": "卖现货中",
        "SPOT_SOLD": "合约开多中",
        "CLOSING_FUTURES": "合约平仓中",
        "FUTURES_CLOSED": "买回中",
        "CLOSING_SPOT": "买回中",
        "SPOT_BOUGHT": "还币中",
        "PENDING_REPAY": "待还币",
        "REPAYING": "还币中",
    }

    def _load_active_statuses(self) -> dict[str, str]:
        """symbol -> execution label for positions currently mid-pipeline."""
        db = SessionLocal()
        try:
            rows = db.query(Position.symbol, Position.status).filter(
                Position.sub_account_id == self.sub_account_id,
                Position.status.in_(list(self._EXEC_STATUS_MAP.keys())),
            ).order_by(Position.id.desc()).all()
            out: dict[str, str] = {}
            for sym, st in rows:
                # Multiple parallel positions can share a symbol.  The newest
                # position is the one the dashboard should describe; otherwise
                # an older closing row can overwrite a newer opening phase.
                if sym not in out:
                    out[sym] = self._EXEC_STATUS_MAP.get(st, "")
            return out
        finally:
            db.close()

    async def _update_state(self, status: str, error: str = None, active_positions: int = None):
        def _write():
            db = SessionLocal()
            try:
                scope = f"sub:{self.sub_account_id}"
                state = db.query(EngineState).filter(
                    EngineState.scope == scope,
                    EngineState.user_id == self._user_id,
                ).first()
                # Claim a legacy row that predates user_id. The scope contains
                # the owned sub-account id, so this cannot cross user boundaries.
                if not state:
                    state = db.query(EngineState).filter(
                        EngineState.scope == scope,
                        EngineState.user_id.is_(None),
                    ).first()
                if not state:
                    state = EngineState(scope=scope, user_id=self._user_id)
                    db.add(state)
                elif state.user_id is None:
                    state.user_id = self._user_id
                state.status = status
                state.last_heartbeat = datetime.now(timezone.utc)
                state.total_cycles = self._cycle_count
                if error:
                    state.error_message = error
                elif status == "RUNNING" and state.error_message:
                    # 化石错误自清:历史崩溃残言(如某次部署窗口的 import 错)在 worker 恢复
                    # RUNNING 后仍钉在行上误导排障(实测 sub:9 顶着旧 import 错跑了 6 万周期)。
                    # RUNNING 心跳即代表当前健康,清掉旧错。
                    state.error_message = None
                if active_positions is not None:
                    state.active_positions = active_positions
                db.commit()
            finally:
                db.close()
        await asyncio.to_thread(_write)

        # C4: publish ban countdown data to Redis
        if self._redis and status == "RUNNING":
            try:
                now_utc = datetime.now(timezone.utc)
                ban_info = {}
                ban_seconds = self.config.global_rules.repay_ban_minutes * 60
                for sym, ts in self._last_borrow_at.items():
                    remaining = ban_seconds - (now_utc - ts).total_seconds()
                    if remaining > 0:
                        ban_info[sym] = {"type": "borrow", "remaining": int(remaining), "total": ban_seconds}
                for sym, ts in self._repay_ban.items():
                    remaining = ban_seconds - (now_utc - ts).total_seconds()
                    if remaining > 0:
                        ban_info[sym] = {"type": "repay", "remaining": int(remaining), "total": ban_seconds}
                if ban_info:
                    await self._redis.publish("ban:updates", json.dumps({
                        "sub_account_id": self.sub_account_id,
                        "user_id": self._user_id,
                        "bans": ban_info,
                    }))
                if self._symbol_statuses:
                    await self._redis.publish("symbol_status:updates", json.dumps({
                        "sub_account_id": self.sub_account_id,
                        "user_id": self._user_id,
                        "statuses": self._symbol_statuses,
                    }))
                # P0: publish IP weight (read budget) + UID weight (borrow budget) for
                # the top-bar gauge and per-account throttle display.
                try:
                    from engine.metrics import global_weight_snapshot, max_uid_weight_snapshot, per_account_uid_weight_snapshot
                    ws = global_weight_snapshot()
                    if ws["weight_time"] > 0:
                        await self._redis.set("engine:weight:latest", json.dumps(ws), ex=90)
                    us = max_uid_weight_snapshot()
                    if us["uid_weight_time"] > 0:
                        await self._redis.set("engine:uid_weight:latest", json.dumps(us), ex=90)
                    # 逐子账户 UID 权重(各账户速率不同)→ 前端子账户行显示 per-account 速率
                    pa = per_account_uid_weight_snapshot()
                    if pa:
                        await self._redis.set("engine:uid_weight:by_account", json.dumps(pa), ex=90)
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"Ban/status publish failed: {e}")

        # 逐账户"被币安API限制"状态(供前端规则列红字提示)。不限 RUNNING —— 账户降级时也要能提示;
        # 仅在"有限制"或"刚解除"时发布,常态无限制不刷 Redis。
        if self._redis:
            try:
                from engine.metrics import get_metrics
                rsnap = get_metrics(self.sub_account_id).restriction_snapshot()
                if rsnap is not None or getattr(self, "_restriction_pub_active", False):
                    await self._redis.publish("account_restriction:updates", json.dumps({
                        "sub_account_id": self.sub_account_id,
                        "user_id": self._user_id,
                        "restriction": rsnap,   # None=未限制(前端据此清除)
                    }))
                    self._restriction_pub_active = rsnap is not None
            except Exception as e:
                logger.debug(f"restriction publish failed: {e}")
