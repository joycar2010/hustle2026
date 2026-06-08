import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import redis.asyncio as aioredis

from app.config import settings
from app.db.models import SubAccount, Symbol, SymbolRule, AccountSymbolRule
from app.db.session import SessionLocal
from engine.models import Position, EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed, SpreadSnapshot

logger = logging.getLogger(__name__)

MAX_POSITIONS_PER_ACCOUNT = 10
MAX_PER_SYMBOL = 3


class Worker:
    def __init__(self, sub_account_id: int, config: ConfigLoader, spread_feed: SpreadFeed):
        self.sub_account_id = sub_account_id
        self.config = config
        self.spread_feed = spread_feed
        self._running = False
        self._repay_ban: dict[str, datetime] = {}
        self._last_borrow_at: dict[str, datetime] = {}
        self._cycle_count = 0
        self._trading_client = None
        self._notifier = None
        self._margin_safe = True
        self._symbol_rules: dict[str, dict] = {}
        self._symbol_statuses: dict[str, str] = {}
        self._user_id: int | None = None
        self._account_max_borrow: Decimal | None = None
        self._account_max_positions: int | None = None
        self._account_borrow_rate: Decimal | None = None
        self._redis: aioredis.Redis | None = None

    async def run(self):
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
        logger.info(f"Worker started for sub-account {self.sub_account_id} ({account_note})")

        await asyncio.to_thread(self._load_symbol_rules)

        from engine.trading.binance_trading import BinanceTradingClient
        self._trading_client = BinanceTradingClient(
            account_info["api_key"], account_info["api_secret"],
            sub_account_id=self.sub_account_id,
        )

        from engine.notify.feishu_sender import FeishuSender
        self._notifier = FeishuSender()

        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)

        await self._update_state("RUNNING")

        tradable_symbols = await asyncio.to_thread(self._load_tradable_symbols)
        last_bnb_check = 0
        last_debt_check = 0
        last_risk_check = 0
        last_health_check = 0
        last_funding_check = 0
        last_borrow_scan = 0

        try:
            async with self._trading_client:
                while self._running:
                    await self._cycle(tradable_symbols, account_note)
                    self._cycle_count += 1
                    if self._cycle_count % 300 == 0:
                        tradable_symbols = await asyncio.to_thread(self._load_tradable_symbols)
                        await asyncio.to_thread(self._load_symbol_rules)

                    # periodic fund tasks
                    now = asyncio.get_event_loop().time()
                    fund_rules = self.config.fund_rules

                    if now - last_risk_check > 30:
                        from engine.fund.risk_monitor import check_margin_risk
                        self._margin_safe = await check_margin_risk(
                            self._trading_client, fund_rules, self._notifier, account_note,
                        )
                        last_risk_check = now

                    if now - last_bnb_check > fund_rules.bnb_convert_interval_sec:
                        from engine.fund.bnb_manager import run_bnb_check
                        await run_bnb_check(self._trading_client, fund_rules, self._notifier, account_note)
                        last_bnb_check = now

                    if now - last_debt_check > fund_rules.usdt_debt_interval_sec:
                        from engine.fund.debt_repayer import run_usdt_debt_check
                        await run_usdt_debt_check(self._trading_client, fund_rules, self._notifier, account_note)
                        last_debt_check = now

                    if now - last_health_check > 300:
                        from engine.fund.health_monitor import run_health_check
                        await run_health_check(self._notifier)
                        last_health_check = now

                    if now - last_funding_check > 1800:
                        from engine.fund.funding_collector import collect_funding_fees
                        await collect_funding_fees(self._trading_client, self.sub_account_id)
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
                            await asyncio.to_thread(self._load_symbol_rules)
                            logger.info(f"Borrow scan found {len(new_borrows)} new symbols: {new_borrows}")
                        last_borrow_scan = now

                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Worker {self.sub_account_id} error: {e}", exc_info=True)
            await self._update_state("ERROR", str(e))
            raise
        finally:
            await self._update_state("STOPPED")
            logger.info(f"Worker stopped for sub-account {self.sub_account_id}")

    async def stop(self):
        self._running = False

    async def _cycle(self, tradable_symbols: set[str], account_note: str):
        rules = self.config.global_rules
        blacklist = self.config.blacklist
        # Apply per-account borrow pacing: account override else global (live-updates)
        from engine.trading.binance_trading import set_borrow_rate
        eff_rate = self._account_borrow_rate if self._account_borrow_rate else getattr(rules, "borrow_rate_per_sec", 2)
        set_borrow_rate(self.sub_account_id, eff_rate)

        open_positions = await asyncio.to_thread(self._load_open_positions)
        idle_positions = await asyncio.to_thread(self._load_positions_by_status, "BORROWED_IDLE")
        pending_repay = await asyncio.to_thread(self._load_positions_by_status, "PENDING_REPAY")

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

        statuses: dict[str, str] = {}
        for pos in open_positions:
            sym = pos.symbol
            if sym in statuses:
                continue
            if not self._is_repay_allowed(sym):
                statuses[sym] = "借币停止"
            elif self._is_borrow_banned(sym):
                statuses[sym] = "借币红"
            else:
                sp = self.spread_feed.get_symbol(sym)
                if sp and sp.spread_short < rules.close_spread:
                    statuses[sym] = "还币中"
                else:
                    statuses[sym] = "点差不符"
        # P1: overlay in-flight execution states (排队中/待对冲/开仓中/待还币...)
        active = await asyncio.to_thread(self._load_active_statuses)
        for sym, label in active.items():
            if label:
                statuses[sym] = label
        self._symbol_statuses = statuses

        # ── UNHEDGE: OPEN → PENDING_REPAY at close_spread (or funding ratio) ──
        for pos in open_positions:
            spread = self.spread_feed.get_symbol(pos.symbol)
            if not spread:
                continue
            if not self._is_repay_allowed(pos.symbol):   # C3
                continue
            if self._is_borrow_banned(pos.symbol):        # C4
                continue
            if spread.spread_short < rules.close_spread:
                await self._unhedge_position(pos, spread, account_note)
                continue
            if getattr(pos, 'funding_rate_ratio', None) is not None and \
               rules.close_funding_ratio > 0 and pos.funding_rate_ratio >= rules.close_funding_ratio:
                logger.info(f"Unhedge {pos.symbol}: funding ratio {pos.funding_rate_ratio} >= {rules.close_funding_ratio}")
                await self._unhedge_position(pos, spread, account_note)

        # ── REPAY: PENDING_REPAY → CLOSED only if an auto-repay threshold is configured & met ──
        repay_spread = getattr(rules, "repay_spread", None)
        repay_fr = getattr(rules, "repay_funding_ratio", None)
        for pos in pending_repay:
            if not self._is_repay_allowed(pos.symbol):
                continue
            spread = self.spread_feed.get_symbol(pos.symbol)
            do_repay = False
            if repay_spread is not None and repay_spread > 0 and spread and spread.spread_short < repay_spread:
                do_repay = True
            elif repay_fr is not None and repay_fr > 0 and getattr(pos, 'funding_rate_ratio', None) is not None \
                    and pos.funding_rate_ratio >= repay_fr:
                do_repay = True
            if do_repay:
                await self._repay_position(pos, account_note)

        # C6: auto-repay for borrow-only (scan) assets with no open position
        for sym, rule in self._symbol_rules.items():
            if rule.get("source") != "scan":
                continue
            if not rule.get("allow_repay", True):
                continue
            if sym in open_symbol_counts:
                continue
            spread = self.spread_feed.get_symbol(sym)
            if not spread:
                continue
            if spread.spread_short < rules.close_spread:
                await self._borrow_only_repay(sym, account_note)

        global_max = rules.max_positions or MAX_POSITIONS_PER_ACCOUNT
        max_positions = self._account_max_positions if self._account_max_positions is not None else global_max

        # ── HEDGE: BORROWED_IDLE → OPEN at open_spread ──
        for pos in idle_positions:
            if not self._running:
                break
            if len(open_positions) >= max_positions:
                break
            spread = self.spread_feed.get_symbol(pos.symbol)
            if not spread:
                continue
            if spread.spread_short > rules.open_spread:
                await self._hedge_position(pos, spread, account_note)
                open_positions = await asyncio.to_thread(self._load_open_positions)

        # ── BORROW: pushed ∩ tradable, spread > borrow_spread → execute_borrow (idle) ──
        active_count = len(open_positions) + len(idle_positions)
        can_borrow = (self._margin_safe and active_count < max_positions and
                      not (self._account_max_borrow is not None and self._account_max_borrow == 0))
        if can_borrow:
            pushed = await asyncio.to_thread(self._load_pushed_symbols)
            borrow_spread = getattr(rules, "borrow_spread", rules.open_spread)
            for symbol in pushed:
                if not self._running or active_count >= max_positions:
                    break
                if symbol in blacklist or symbol not in tradable_symbols:
                    continue
                if symbol in active_symbols:          # already borrowed / open / pending
                    continue
                if self._is_banned(symbol):
                    continue
                sym_rule = self._symbol_rules.get(symbol, {})
                if sym_rule.get("max_borrow_amount") is not None and sym_rule["max_borrow_amount"] == 0:
                    continue
                spread = self.spread_feed.get_symbol(symbol)
                if not spread or spread.spread_short <= borrow_spread:
                    continue
                await self._initiate_borrow(symbol, spread, account_note)
                active_symbols.add(symbol)
                active_count += 1

        # ── Auto-push: symbols whose spread ≥ auto_push_spread join the user's pushed list ──
        if self._cycle_count % 10 == 0 and getattr(rules, "auto_push_spread", 0) and rules.auto_push_spread > 0:
            await self._auto_push(float(rules.auto_push_spread), tradable_symbols)

        if self._cycle_count % 10 == 0:
            await self._update_state("RUNNING", active_positions=len(open_positions))

    async def _initiate_borrow(self, symbol: str, spread: SpreadSnapshot, account_note: str):
        """Phase 1: borrow at 挂单点差, hold idle."""
        from engine.trading.order_executor import execute_borrow
        try:
            await execute_borrow(
                self.sub_account_id, symbol, spread,
                self.config.global_rules, self._trading_client,
                self._notifier, account_note,
                spread_feed=self.spread_feed,
                min_spread=getattr(self.config.global_rules, "borrow_spread", self.config.global_rules.open_spread),
            )
            self._last_borrow_at[symbol] = datetime.now(timezone.utc)  # C4 ban countdown
        except Exception as e:
            logger.error(f"Initiate borrow failed {symbol}: {e}")

    async def _hedge_position(self, position: Position, spread: SpreadSnapshot, account_note: str):
        """Phase 2: sell spot + futures long. BORROWED_IDLE → OPEN."""
        from engine.trading.order_executor import execute_hedge
        try:
            await execute_hedge(
                position, spread, self.config.global_rules,
                self._trading_client, self._notifier, account_note,
            )
        except Exception as e:
            logger.error(f"Hedge failed {position.symbol}: {e}")

    async def _unhedge_position(self, position: Position, spread: SpreadSnapshot, account_note: str):
        """Close hedge (futures close + spot buy back), leave coin pending repay."""
        from engine.trading.order_executor import execute_unhedge
        try:
            await execute_unhedge(
                position, spread, self._trading_client, self._notifier, account_note,
            )
            self._repay_ban[position.symbol] = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Unhedge failed {position.symbol}: {e}")

    async def _repay_position(self, position: Position, account_note: str):
        """Repay margin debt → CLOSED (auto path; manual path via API)."""
        from engine.trading.order_executor import execute_repay
        try:
            await execute_repay(position, self._trading_client, self._notifier, account_note)
        except Exception as e:
            logger.error(f"Repay failed {position.symbol}: {e}")

    def _load_pushed_symbols(self) -> set[str]:
        """The user's actively-pushed symbols (trade gate). Synchronous Redis read."""
        try:
            import redis as _redis_sync
            r = _redis_sync.from_url(settings.redis_url, decode_responses=True)
            raw = r.get(f"engine:{self._user_id}:pushed_symbols")
            r.close()
            return set(json.loads(raw)) if raw else set()
        except Exception:
            return set()

    async def _auto_push(self, threshold: float, tradable_symbols: set[str]):
        """Add symbols whose spread_short ≥ auto_push_spread to the user's pushed set."""
        try:
            candidates = {
                sym for sym, sp in self.spread_feed.get_all().items()
                if sym in tradable_symbols and float(sp.spread_short) >= threshold
            }
            if not candidates:
                return
            key = f"engine:{self._user_id}:pushed_symbols"
            raw = await self._redis.get(key)
            current = set(json.loads(raw)) if raw else set()
            new = candidates - current
            if new:
                current |= candidates
                await self._redis.set(key, json.dumps(sorted(current)))
                logger.info(f"Auto-pushed {len(new)} symbols (spread≥{threshold}): {sorted(new)[:10]}")
        except Exception as e:
            logger.debug(f"Auto-push failed: {e}")

    async def _borrow_only_repay(self, symbol: str, account_note: str):
        from engine.trading.order_executor import execute_borrow_only_repay
        try:
            await execute_borrow_only_repay(
                self.sub_account_id, symbol,
                self._trading_client, self._notifier, account_note,
            )
            logger.info(f"Auto repaid borrow-only: {symbol}")
        except Exception as e:
            logger.error(f"Auto repay failed {symbol}: {e}")

    def _is_banned(self, symbol: str) -> bool:
        ban_until = self._repay_ban.get(symbol)
        if not ban_until:
            return False
        if datetime.now(timezone.utc) - ban_until < timedelta(minutes=self.config.global_rules.repay_ban_minutes):
            return True
        del self._repay_ban[symbol]
        return False

    def _load_account(self) -> dict | None:
        db = SessionLocal()
        try:
            account = db.query(SubAccount).get(self.sub_account_id)
            if not account:
                return None
            return {
                "note": account.note,
                "api_key": account.api_key,
                "api_secret": account.api_secret,
                "user_id": account.user_id,
                "max_borrow_amount": account.max_borrow_amount,
                "max_positions": account.max_positions,
                "borrow_rate_per_sec": account.borrow_rate_per_sec,
            }
        finally:
            db.close()

    def _load_symbol_rules(self):
        db = SessionLocal()
        try:
            rules_map = {}
            q = db.query(SymbolRule)
            if self._user_id:
                q = q.filter(SymbolRule.user_id == self._user_id)
            for sr in q.all():
                rules_map[sr.symbol] = {
                    "allow_repay": sr.allow_repay,
                    "allow_remove": sr.allow_remove,
                    "remove_spread": sr.remove_spread,
                    "source": sr.source,
                }
            # account-level overrides
            for ar in db.query(AccountSymbolRule).filter(
                AccountSymbolRule.sub_account_id == self.sub_account_id,
            ).all():
                key = ar.symbol
                if key in rules_map:
                    if ar.remove_spread is not None:
                        rules_map[key]["remove_spread"] = ar.remove_spread
                    if ar.is_enabled is not None:
                        rules_map[key]["account_enabled"] = ar.is_enabled
                    if ar.max_borrow_amount is not None:
                        rules_map[key]["max_borrow_amount"] = ar.max_borrow_amount
            self._symbol_rules = rules_map
        finally:
            db.close()

    def _is_repay_allowed(self, symbol: str) -> bool:
        rule = self._symbol_rules.get(symbol)
        if not rule:
            return True
        return rule.get("allow_repay", True)

    def _is_borrow_banned(self, symbol: str) -> bool:
        """C4: Check if symbol is within the post-borrow repay ban window."""
        last_borrow = self._last_borrow_at.get(symbol)
        if not last_borrow:
            return False
        elapsed = (datetime.now(timezone.utc) - last_borrow).total_seconds()
        ban_seconds = self.config.global_rules.repay_ban_minutes * 60
        return elapsed < ban_seconds

    def _load_tradable_symbols(self) -> set[str]:
        db = SessionLocal()
        try:
            symbols = db.query(Symbol.symbol).filter(
                Symbol.is_active == True,
                Symbol.margin_tradable == True,
                Symbol.futures_tradable == True,
            ).all()
            return {s.symbol for s in symbols}
        finally:
            db.close()

    def _load_open_positions(self) -> list[Position]:
        db = SessionLocal()
        try:
            return db.query(Position).filter(
                Position.sub_account_id == self.sub_account_id,
                Position.status == "OPEN",
            ).all()
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

    # P1: transient/holding statuses -> 执行/队列 labels for the 状态 column
    _EXEC_STATUS_MAP = {
        "PENDING_BORROW": "排队中",
        "BORROWED": "借币中",
        "BORROWED_IDLE": "待对冲",
        "SPOT_SOLD": "开仓中",
        "CLOSING_FUTURES": "平仓中",
        "FUTURES_CLOSED": "平仓中",
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
            ).all()
            out: dict[str, str] = {}
            for sym, st in rows:
                out[sym] = self._EXEC_STATUS_MAP.get(st, "")
            return out
        finally:
            db.close()

    async def _update_state(self, status: str, error: str = None, active_positions: int = None):
        def _write():
            db = SessionLocal()
            try:
                scope = f"sub:{self.sub_account_id}"
                state = db.query(EngineState).filter(EngineState.scope == scope).first()
                if not state:
                    state = EngineState(scope=scope)
                    db.add(state)
                state.status = status
                state.last_heartbeat = datetime.now(timezone.utc)
                state.total_cycles = self._cycle_count
                if error:
                    state.error_message = error
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
                    from engine.metrics import global_weight_snapshot, max_uid_weight_snapshot
                    ws = global_weight_snapshot()
                    if ws["weight_time"] > 0:
                        await self._redis.set("engine:weight:latest", json.dumps(ws), ex=90)
                    us = max_uid_weight_snapshot()
                    if us["uid_weight_time"] > 0:
                        await self._redis.set("engine:uid_weight:latest", json.dumps(us), ex=90)
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"Ban/status publish failed: {e}")
