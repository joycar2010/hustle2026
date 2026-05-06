import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.db.models import SubAccount, Symbol, SymbolRule, AccountSymbolRule
from app.db.session import SessionLocal
from engine.models import Position, EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed, SpreadSnapshot

logger = logging.getLogger(__name__)

MAX_POSITIONS_PER_ACCOUNT = 10


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
        self._user_id: int | None = None

    async def run(self):
        self._running = True
        account_info = await asyncio.to_thread(self._load_account)
        if not account_info:
            logger.error(f"Sub-account {self.sub_account_id} not found")
            return

        account_note = account_info["note"]
        self._user_id = account_info.get("user_id")
        logger.info(f"Worker started for sub-account {self.sub_account_id} ({account_note})")

        await asyncio.to_thread(self._load_symbol_rules)

        from engine.trading.binance_trading import BinanceTradingClient
        self._trading_client = BinanceTradingClient(
            account_info["api_key"], account_info["api_secret"],
            sub_account_id=self.sub_account_id,
        )

        from engine.notify.feishu_sender import FeishuSender
        self._notifier = FeishuSender()

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

        open_positions = await asyncio.to_thread(self._load_open_positions)
        open_symbols = {p.symbol for p in open_positions}

        for pos in open_positions:
            spread = self.spread_feed.get_symbol(pos.symbol)
            if not spread:
                continue

            # C3: skip close+repay if allow_repay is false for this symbol
            if not self._is_repay_allowed(pos.symbol):
                continue

            # C4: skip close if within borrow ban window
            if self._is_borrow_banned(pos.symbol):
                continue

            if spread.spread_short < rules.close_spread:
                await self._close_position(pos, spread, account_note)
                continue
            if hasattr(pos, 'funding_rate_ratio') and pos.funding_rate_ratio is not None:
                if rules.close_funding_ratio > 0 and pos.funding_rate_ratio >= rules.close_funding_ratio:
                    logger.info(f"Closing {pos.symbol}: funding ratio {pos.funding_rate_ratio} >= {rules.close_funding_ratio}")
                    await self._close_position(pos, spread, account_note)

        max_positions = rules.max_positions or MAX_POSITIONS_PER_ACCOUNT
        if len(open_positions) >= max_positions:
            return

        if not self._margin_safe:
            return

        all_spreads = self.spread_feed.get_all()
        for symbol, spread in all_spreads.items():
            if not self._running:
                break
            if spread.spread_short <= rules.open_spread:
                continue
            if symbol in blacklist:
                continue
            if symbol in open_symbols:
                continue
            if symbol not in tradable_symbols:
                continue
            if self._is_banned(symbol):
                continue
            if len(open_positions) + 1 > max_positions:
                break

            await self._open_position(symbol, spread, account_note)
            open_positions = await asyncio.to_thread(self._load_open_positions)
            open_symbols = {p.symbol for p in open_positions}

        if self._cycle_count % 10 == 0:
            await self._update_state("RUNNING", active_positions=len(open_positions))

    async def _open_position(self, symbol: str, spread: SpreadSnapshot, account_note: str):
        from engine.trading.order_executor import execute_open
        try:
            await execute_open(
                self.sub_account_id, symbol, spread,
                self.config.global_rules, self._trading_client,
                self._notifier, account_note,
                spread_feed=self.spread_feed,
            )
            # C4: track borrow time — reset repay ban countdown
            self._last_borrow_at[symbol] = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Open position failed {symbol}: {e}")

    async def _close_position(self, position: Position, spread: SpreadSnapshot, account_note: str):
        from engine.trading.order_executor import execute_close
        try:
            await execute_close(
                position, spread,
                self._trading_client, self._notifier, account_note,
            )
            self._repay_ban[position.symbol] = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Close position failed {position.symbol}: {e}")

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
