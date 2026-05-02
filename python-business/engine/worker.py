import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.db.models import SubAccount, Symbol
from app.db.session import SessionLocal
from engine.models import Position, EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed, SpreadSnapshot

logger = logging.getLogger(__name__)

class Worker:
    def __init__(self, sub_account_id: int, config: ConfigLoader, spread_feed: SpreadFeed, user_id: int | None = None):
        self.sub_account_id = sub_account_id
        self.user_id = user_id
        self.config = config
        self.spread_feed = spread_feed
        self._running = False
        self._reopen_ban: dict[str, datetime] = {}
        self._cycle_count = 0
        self._trading_client = None
        self._notifier = None
        self._circuit_breaker_until: datetime | None = None
        self._prev_spreads: dict[str, Decimal] = {}
        self._pushed_symbols: set[str] = set()
        self._borrow_fail_cooldown: dict[str, datetime] = {}
        self._account_max_positions: int | None = None
        self._account_max_borrow_amount: Decimal | None = None

    async def run(self):
        self._running = True
        account_info = await asyncio.to_thread(self._load_account)
        if not account_info:
            logger.error(f"Sub-account {self.sub_account_id} not found")
            return

        account_note = account_info["note"]
        logger.info(f"Worker started for sub-account {self.sub_account_id} ({account_note})")

        from engine.trading.binance_trading import BinanceTradingClient
        self._trading_client = BinanceTradingClient(
            account_info["api_key"], account_info["api_secret"],
        )

        from engine.notify.feishu_sender import FeishuSender
        self._notifier = FeishuSender()

        await self._update_state("RUNNING")

        tradable_symbols = await asyncio.to_thread(self._load_tradable_symbols)
        last_bnb_check = 0
        last_debt_check = 0
        last_risk_check = 0
        last_funding_check = 0

        try:
            async with self._trading_client:
                while self._running:
                    await self._cycle(tradable_symbols, account_note)
                    self._cycle_count += 1
                    if self._cycle_count % 300 == 0:
                        tradable_symbols = await asyncio.to_thread(self._load_tradable_symbols)

                    # periodic fund tasks
                    now = asyncio.get_event_loop().time()
                    fund_rules = self.config.fund_rules

                    if now - last_risk_check > 30:
                        from engine.fund.risk_monitor import check_margin_risk
                        await check_margin_risk(self._trading_client, fund_rules, self._notifier, account_note)
                        from engine.fund.balance_checker import auto_balance_check
                        await auto_balance_check(self._trading_client, fund_rules, self._notifier, account_note)
                        last_risk_check = now

                    if now - last_bnb_check > fund_rules.bnb_convert_interval_sec:
                        from engine.fund.bnb_manager import run_bnb_check
                        await run_bnb_check(self._trading_client, fund_rules, self._notifier, account_note)
                        last_bnb_check = now

                    if now - last_debt_check > fund_rules.usdt_debt_interval_sec:
                        from engine.fund.debt_repayer import run_usdt_debt_check
                        await run_usdt_debt_check(self._trading_client, fund_rules, self._notifier, account_note)
                        last_debt_check = now

                    if now - last_funding_check > 300:
                        from engine.fund.funding_collector import collect_funding_fees
                        await collect_funding_fees(self._trading_client, self.sub_account_id)
                        last_funding_check = now

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
        blacklist = self.config.blacklist
        global_rules = self.config.global_rules
        now_utc = datetime.now(timezone.utc)
        repay_ban_minutes = global_rules.repay_ban_minutes

        open_positions = await asyncio.to_thread(self._load_open_positions)
        open_symbols = {p.symbol for p in open_positions}

        for pos in open_positions:
            spread = self.spread_feed.get_symbol(pos.symbol)
            if not spread:
                continue
            rules = self.config.get_effective_rules(pos.symbol, self.sub_account_id)

            # stop-loss always fires regardless of protection period
            if global_rules.max_loss_per_position is not None:
                unrealized = self._estimate_pnl(pos, spread)
                if unrealized is not None and unrealized < -abs(global_rules.max_loss_per_position):
                    logger.warning(f"Stop-loss triggered for {pos.symbol} id={pos.id}, pnl={unrealized}")
                    await self._close_position(pos, spread, account_note)
                    await self._notifier.notify_error(
                        account_note,
                        f"止损平仓 {pos.symbol}",
                        f"未实现亏损 {unrealized} USDT 超过阈值 {global_rules.max_loss_per_position}",
                    )
                    continue

            # borrow protection: skip auto-close if position opened < repay_ban_minutes ago
            if pos.opened_at and repay_ban_minutes > 0:
                elapsed = (now_utc - pos.opened_at).total_seconds() / 60
                if elapsed < repay_ban_minutes:
                    continue

            # normal close spread check
            if spread.spread_short < rules.close_spread:
                await self._close_position(pos, spread, account_note)
                continue

            # independent repay spread + funding ratio check
            repay_thresh = rules.repay_spread
            if repay_thresh is not None and spread.spread_short < repay_thresh:
                if rules.repay_funding_ratio:
                    ratio = self._get_cached_funding_ratio(pos)
                    if ratio is not None and ratio >= rules.repay_funding_ratio:
                        await self._close_position(pos, spread, account_note)
                        continue

        max_pos = self._account_max_positions or self.config.global_rules.max_positions or 10
        if len(open_positions) >= max_pos:
            return

        # circuit breaker: skip opening if paused
        if self._circuit_breaker_until and now_utc < self._circuit_breaker_until:
            if self._cycle_count % 10 == 0:
                await self._update_state("RUNNING", active_positions=len(open_positions))
            return

        all_spreads = self.spread_feed.get_all()

        # circuit breaker detection
        if global_rules.circuit_breaker_spread_pct is not None:
            for sym, sp in all_spreads.items():
                prev = self._prev_spreads.get(sym)
                if prev is not None:
                    delta = abs(sp.spread_short - prev)
                    if delta > global_rules.circuit_breaker_spread_pct:
                        pause_sec = global_rules.circuit_breaker_pause_sec
                        self._circuit_breaker_until = now_utc + timedelta(seconds=pause_sec)
                        logger.warning(f"Circuit breaker: {sym} spread delta {delta}% > {global_rules.circuit_breaker_spread_pct}%, pausing {pause_sec}s")
                        await self._notifier.notify_error(
                            account_note,
                            f"熔断触发 {sym}",
                            f"点差变动 {delta}% 超过阈值 {global_rules.circuit_breaker_spread_pct}%，暂停开仓 {pause_sec}s",
                        )
                        break
                self._prev_spreads[sym] = sp.spread_short

            if self._circuit_breaker_until and now_utc < self._circuit_breaker_until:
                if self._cycle_count % 10 == 0:
                    await self._update_state("RUNNING", active_positions=len(open_positions))
                return

        # push/remove spread slot management
        removed_from_slot: list[str] = []
        for symbol, spread in all_spreads.items():
            rules = self.config.get_effective_rules(symbol, self.sub_account_id)
            push_thresh = rules.auto_push_spread
            remove_thresh = rules.remove_spread
            if spread.spread_short >= push_thresh:
                self._pushed_symbols.add(symbol)
            elif spread.spread_short < remove_thresh:
                if symbol in self._pushed_symbols:
                    removed_from_slot.append(symbol)
                self._pushed_symbols.discard(symbol)

        if removed_from_slot:
            await asyncio.to_thread(self._clear_temporary_rules, removed_from_slot)

        for symbol, spread in all_spreads.items():
            if not self._running:
                break
            rules = self.config.get_effective_rules(symbol, self.sub_account_id)
            if symbol not in self._pushed_symbols:
                continue
            if spread.spread_short <= rules.open_spread:
                continue
            if symbol in blacklist:
                continue
            if symbol in open_symbols:
                continue
            if symbol not in tradable_symbols:
                continue
            if self._is_reopen_banned(symbol):
                continue
            if self._is_borrow_cooled_down(symbol):
                continue
            # account+symbol borrow amount limit (0 = don't borrow this coin)
            asr = self.config.get_account_symbol_rule(self.sub_account_id, symbol)
            if asr and asr.max_borrow_amount is not None and asr.max_borrow_amount <= 0:
                continue
            # account-level borrow amount limit
            if self._account_max_borrow_amount is not None and self._account_max_borrow_amount <= 0:
                continue
            # daily interest rate pre-check
            if rules.max_daily_interest_rate is not None:
                pass  # actual rate check happens in execute_open
            if len(open_positions) + 1 > max_pos:
                break

            await self._open_position(symbol, spread, account_note)
            open_positions = await asyncio.to_thread(self._load_open_positions)
            open_symbols = {p.symbol for p in open_positions}

        if self._cycle_count % 10 == 0:
            await self._update_state("RUNNING", active_positions=len(open_positions))

    async def _open_position(self, symbol: str, spread: SpreadSnapshot, account_note: str):
        from engine.trading.order_executor import execute_open
        try:
            rules = self.config.get_effective_rules(symbol, self.sub_account_id)
            await execute_open(
                self.sub_account_id, symbol, spread,
                rules, self._trading_client,
                self._notifier, account_note,
                on_borrow_fail=lambda sym: self.set_borrow_cooldown(sym, 5),
                user_id=self.user_id,
            )
        except Exception as e:
            logger.error(f"Open position failed {symbol}: {e}")

    async def _close_position(self, position: Position, spread: SpreadSnapshot, account_note: str):
        from engine.trading.order_executor import execute_close
        try:
            await execute_close(
                position, spread,
                self._trading_client, self._notifier, account_note,
            )
            self._reopen_ban[position.symbol] = datetime.now(timezone.utc)
            self._pushed_symbols.discard(position.symbol)
        except Exception as e:
            logger.error(f"Close position failed {position.symbol}: {e}")

    def _estimate_pnl(self, pos: Position, spread: SpreadSnapshot) -> Decimal | None:
        if not pos.spot_sell_qty or not pos.spot_sell_price or not pos.futures_long_price or not pos.futures_long_qty:
            return None
        spot_cost = pos.spot_sell_qty * pos.spot_sell_price
        spot_rebuy = pos.spot_sell_qty * spread.spot_ask
        futures_pnl = (spread.fut_bid - pos.futures_long_price) * pos.futures_long_qty
        return (spot_cost - spot_rebuy) + futures_pnl

    def _get_cached_funding_ratio(self, pos: Position) -> Decimal | None:
        return pos.funding_rate_ratio

    def _is_reopen_banned(self, symbol: str) -> bool:
        ban_time = self._reopen_ban.get(symbol)
        if not ban_time:
            return False
        if datetime.now(timezone.utc) - ban_time < timedelta(minutes=self.config.global_rules.repay_ban_minutes):
            return True
        del self._reopen_ban[symbol]
        return False

    def _is_borrow_cooled_down(self, symbol: str) -> bool:
        cd_time = self._borrow_fail_cooldown.get(symbol)
        if not cd_time:
            return False
        if datetime.now(timezone.utc) < cd_time:
            return True
        del self._borrow_fail_cooldown[symbol]
        return False

    def set_borrow_cooldown(self, symbol: str, minutes: int = 5):
        self._borrow_fail_cooldown[symbol] = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    def _clear_temporary_rules(self, symbols: list[str]):
        from app.db.models import SymbolRule
        db = SessionLocal()
        try:
            for sym in symbols:
                rule = db.query(SymbolRule).filter(
                    SymbolRule.symbol == sym,
                    SymbolRule.is_temporary == True,
                ).first()
                if rule:
                    db.delete(rule)
                    logger.info(f"Cleared temporary rule for {sym} (removed from slot)")
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to clear temporary rules: {e}")
            db.rollback()
        finally:
            db.close()

    def _load_account(self) -> dict | None:
        db = SessionLocal()
        try:
            account = db.query(SubAccount).get(self.sub_account_id)
            if not account:
                return None
            self._account_max_positions = account.max_positions
            self._account_max_borrow_amount = account.max_borrow_amount
            return {
                "note": account.note,
                "api_key": account.api_key,
                "api_secret": account.api_secret,
            }
        finally:
            db.close()

    def _load_tradable_symbols(self) -> set[str]:
        db = SessionLocal()
        try:
            symbols = db.query(Symbol.symbol).filter(
                Symbol.is_active == True,
                Symbol.margin_tradable == True,
                Symbol.futures_tradable == True,
                Symbol.allow_open == True,
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
                q = db.query(EngineState).filter(EngineState.scope == scope)
                if self.user_id is not None:
                    q = q.filter(EngineState.user_id == self.user_id)
                state = q.first()
                if not state:
                    state = EngineState(scope=scope, user_id=self.user_id)
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
        try:
            from app.services.event_publisher import publish_worker_status
            await publish_worker_status({
                "scope": f"sub:{self.sub_account_id}",
                "status": status,
                "total_cycles": self._cycle_count,
                "active_positions": active_positions,
                "error_message": error,
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass
