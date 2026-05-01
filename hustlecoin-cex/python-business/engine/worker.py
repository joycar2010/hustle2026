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

MAX_POSITIONS_PER_ACCOUNT = 10


class Worker:
    def __init__(self, sub_account_id: int, config: ConfigLoader, spread_feed: SpreadFeed):
        self.sub_account_id = sub_account_id
        self.config = config
        self.spread_feed = spread_feed
        self._running = False
        self._repay_ban: dict[str, datetime] = {}
        self._cycle_count = 0
        self._trading_client = None
        self._notifier = None

    async def run(self):
        self._running = True
        account_info = await asyncio.to_thread(self._load_account)
        if not account_info:
            logger.error(f"Sub-account {self.sub_account_id} not found")
            return

        account_note = account_info["note"]
        logger.info(f"Worker started for sub-account {self.sub_account_id} ({account_note})")

        from engine.trading.binance_trading import BinanceTradingClient
        from app.config import settings
        effective_proxy = account_info.get("proxy_url") or settings.proxy_url
        self._trading_client = BinanceTradingClient(
            account_info["api_key"], account_info["api_secret"],
            proxy_url=effective_proxy,
        )

        from engine.notify.feishu_sender import FeishuSender
        self._notifier = FeishuSender()

        await self._update_state("RUNNING")

        tradable_symbols = await asyncio.to_thread(self._load_tradable_symbols)
        last_bnb_check = 0
        last_debt_check = 0
        last_risk_check = 0

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
                        last_risk_check = now

                    if now - last_bnb_check > fund_rules.bnb_convert_interval_sec:
                        from engine.fund.bnb_manager import run_bnb_check
                        await run_bnb_check(self._trading_client, fund_rules, self._notifier, account_note)
                        last_bnb_check = now

                    if now - last_debt_check > fund_rules.usdt_debt_interval_sec:
                        from engine.fund.debt_repayer import run_usdt_debt_check
                        await run_usdt_debt_check(self._trading_client, fund_rules, self._notifier, account_note)
                        last_debt_check = now

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
            if spread.spread_short < rules.close_spread:
                await self._close_position(pos, spread, account_note)

        if len(open_positions) >= MAX_POSITIONS_PER_ACCOUNT:
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
            if len(open_positions) + 1 > MAX_POSITIONS_PER_ACCOUNT:
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
                "proxy_url": account.proxy_url,
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
