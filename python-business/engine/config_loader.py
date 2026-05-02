import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import GlobalRules, FundRules, Blacklist, SymbolRule, AccountSymbolRule
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GlobalRulesSnapshot:
    auto_push_spread: Decimal = Decimal("0.8")
    remove_spread: Decimal = Decimal("0.5")
    open_spread: Decimal = Decimal("0.8")
    close_spread: Decimal = Decimal("0.2")
    order_amount: Decimal = Decimal("500")
    close_funding_ratio: Decimal = Decimal("1.2")
    repay_funding_ratio: Decimal = Decimal("1.2")
    borrow_delay_sec: int = 3
    confirm_delay_sec: int = 2
    confirm_skip_spread: Decimal = Decimal("2.0")
    repay_ban_minutes: int = 30
    interest_filter: Decimal = Decimal("1.0")
    max_loss_per_position: Decimal | None = None
    circuit_breaker_spread_pct: Decimal | None = None
    circuit_breaker_pause_sec: int = 300
    max_daily_interest_rate: Decimal | None = None
    repay_spread: Decimal | None = None
    max_positions: int = 10
    auto_start_on_boot: bool = False
    futures_liquidation_threshold: Decimal | None = None


@dataclass(frozen=True)
class FundRulesSnapshot:
    bnb_min_quantity: Decimal = Decimal("0.15")
    bnb_buy_trigger_pct: Decimal = Decimal("50")
    bnb_buy_amount: Decimal = Decimal("0.1")
    bnb_debt_auto_repay: bool = True
    bnb_debt_threshold: Decimal = Decimal("0.1")
    usdt_debt_auto_repay: bool = True
    usdt_debt_threshold: Decimal = Decimal("20")
    usdt_debt_interval_sec: int = 3600
    bnb_convert_interval_sec: int = 3600
    debt_convert_interval_sec: int = 21600
    risk_value_threshold: Decimal = Decimal("1.5")
    single_transfer_amount: Decimal = Decimal("500")
    base_margin_amount: Decimal = Decimal("500")
    transfer_order: str = "futures,spot,margin"


@dataclass(frozen=True)
class SymbolRuleSnapshot:
    symbol: str = ""
    open_spread: Decimal | None = None
    close_spread: Decimal | None = None
    order_amount: Decimal | None = None
    remove_spread: Decimal | None = None
    close_funding_ratio: Decimal | None = None
    repay_funding_ratio: Decimal | None = None
    allow_remove: bool = True
    allow_repay: bool = True
    max_daily_interest_rate: Decimal | None = None
    repay_spread: Decimal | None = None


@dataclass(frozen=True)
class AccountSymbolRuleSnapshot:
    sub_account_id: int = 0
    symbol: str = ""
    open_spread: Decimal | None = None
    close_spread: Decimal | None = None
    order_amount: Decimal | None = None
    remove_spread: Decimal | None = None
    close_funding_ratio: Decimal | None = None
    repay_funding_ratio: Decimal | None = None
    max_daily_interest_rate: Decimal | None = None
    repay_spread: Decimal | None = None
    max_borrow_amount: Decimal | None = None
    is_enabled: bool = True


DEFAULT_GLOBAL = GlobalRulesSnapshot()
DEFAULT_FUND = FundRulesSnapshot()


class ConfigLoader:
    def __init__(self, user_id: int | None = None):
        self.user_id = user_id
        self.global_rules: GlobalRulesSnapshot = DEFAULT_GLOBAL
        self.fund_rules: FundRulesSnapshot = DEFAULT_FUND
        self.blacklist: set[str] = set()
        self.symbol_rules: dict[str, SymbolRuleSnapshot] = {}
        self.account_symbol_rules: dict[tuple[int, str], AccountSymbolRuleSnapshot] = {}
        self._running = False

    async def start(self):
        self._running = True
        await asyncio.to_thread(self._reload)
        asyncio.create_task(self._poll_loop())
        logger.info(f"ConfigLoader started (user_id={self.user_id})")

    def get_effective_rules(self, symbol: str, sub_account_id: int | None = None) -> GlobalRulesSnapshot:
        sr = self.symbol_rules.get(symbol)
        g = self.global_rules

        # Layer 2: SymbolRule overrides GlobalRules (NULL = inherit)
        l2_remove_spread = sr.remove_spread if sr and sr.remove_spread is not None else g.remove_spread
        l2_open_spread = sr.open_spread if sr and sr.open_spread is not None else g.open_spread
        l2_close_spread = sr.close_spread if sr and sr.close_spread is not None else g.close_spread
        l2_order_amount = sr.order_amount if sr and sr.order_amount is not None else g.order_amount
        l2_close_funding_ratio = sr.close_funding_ratio if sr and sr.close_funding_ratio is not None else g.close_funding_ratio
        l2_repay_funding_ratio = sr.repay_funding_ratio if sr and sr.repay_funding_ratio is not None else g.repay_funding_ratio
        l2_max_daily_interest_rate = sr.max_daily_interest_rate if sr and sr.max_daily_interest_rate is not None else g.max_daily_interest_rate
        l2_repay_spread = sr.repay_spread if sr and sr.repay_spread is not None else g.repay_spread

        # Layer 3: AccountSymbolRule overrides Layer 2 (if sub_account_id given)
        asr = self.account_symbol_rules.get((sub_account_id, symbol)) if sub_account_id else None

        return GlobalRulesSnapshot(
            auto_push_spread=g.auto_push_spread,
            remove_spread=asr.remove_spread if asr and asr.remove_spread is not None else l2_remove_spread,
            open_spread=asr.open_spread if asr and asr.open_spread is not None else l2_open_spread,
            close_spread=asr.close_spread if asr and asr.close_spread is not None else l2_close_spread,
            order_amount=asr.order_amount if asr and asr.order_amount is not None else l2_order_amount,
            close_funding_ratio=asr.close_funding_ratio if asr and asr.close_funding_ratio is not None else l2_close_funding_ratio,
            repay_funding_ratio=asr.repay_funding_ratio if asr and asr.repay_funding_ratio is not None else l2_repay_funding_ratio,
            borrow_delay_sec=g.borrow_delay_sec,
            confirm_delay_sec=g.confirm_delay_sec,
            confirm_skip_spread=g.confirm_skip_spread,
            repay_ban_minutes=g.repay_ban_minutes,
            interest_filter=g.interest_filter,
            max_loss_per_position=g.max_loss_per_position,
            circuit_breaker_spread_pct=g.circuit_breaker_spread_pct,
            circuit_breaker_pause_sec=g.circuit_breaker_pause_sec,
            max_daily_interest_rate=asr.max_daily_interest_rate if asr and asr.max_daily_interest_rate is not None else l2_max_daily_interest_rate,
            repay_spread=asr.repay_spread if asr and asr.repay_spread is not None else l2_repay_spread,
            max_positions=g.max_positions,
            auto_start_on_boot=g.auto_start_on_boot,
            futures_liquidation_threshold=g.futures_liquidation_threshold,
        )

    def get_account_symbol_rule(self, sub_account_id: int, symbol: str) -> AccountSymbolRuleSnapshot | None:
        return self.account_symbol_rules.get((sub_account_id, symbol))

    async def stop(self):
        self._running = False

    async def _poll_loop(self):
        while self._running:
            await asyncio.sleep(30)
            try:
                await asyncio.to_thread(self._reload)
            except Exception as e:
                logger.warning(f"Config reload failed: {e}")

    def _reload(self):
        db: Session = SessionLocal()
        try:
            q = db.query(GlobalRules)
            if self.user_id is not None:
                q = q.filter(GlobalRules.user_id == self.user_id)
            rules = q.first()
            if rules:
                self.global_rules = GlobalRulesSnapshot(
                    auto_push_spread=rules.auto_push_spread,
                    remove_spread=rules.remove_spread,
                    open_spread=rules.open_spread,
                    close_spread=rules.close_spread,
                    order_amount=rules.order_amount,
                    close_funding_ratio=rules.close_funding_ratio,
                    repay_funding_ratio=rules.repay_funding_ratio,
                    borrow_delay_sec=rules.borrow_delay_sec,
                    confirm_delay_sec=rules.confirm_delay_sec,
                    confirm_skip_spread=rules.confirm_skip_spread,
                    repay_ban_minutes=rules.repay_ban_minutes,
                    interest_filter=rules.interest_filter,
                    max_loss_per_position=rules.max_loss_per_position,
                    circuit_breaker_spread_pct=rules.circuit_breaker_spread_pct,
                    circuit_breaker_pause_sec=rules.circuit_breaker_pause_sec or 300,
                    max_daily_interest_rate=rules.max_daily_interest_rate,
                    repay_spread=rules.repay_spread,
                    max_positions=rules.max_positions or 10,
                    auto_start_on_boot=rules.auto_start_on_boot or False,
                    futures_liquidation_threshold=rules.futures_liquidation_threshold,
                )

            fq = db.query(FundRules)
            if self.user_id is not None:
                fq = fq.filter(FundRules.user_id == self.user_id)
            fund = fq.first()
            if fund:
                self.fund_rules = FundRulesSnapshot(
                    bnb_min_quantity=fund.bnb_min_quantity,
                    bnb_buy_trigger_pct=fund.bnb_buy_trigger_pct,
                    bnb_buy_amount=fund.bnb_buy_amount,
                    bnb_debt_auto_repay=fund.bnb_debt_auto_repay,
                    bnb_debt_threshold=fund.bnb_debt_threshold,
                    usdt_debt_auto_repay=fund.usdt_debt_auto_repay,
                    usdt_debt_threshold=fund.usdt_debt_threshold,
                    usdt_debt_interval_sec=fund.usdt_debt_interval_sec,
                    bnb_convert_interval_sec=fund.bnb_convert_interval_sec,
                    debt_convert_interval_sec=fund.debt_convert_interval_sec,
                    risk_value_threshold=fund.risk_value_threshold,
                    single_transfer_amount=fund.single_transfer_amount,
                    base_margin_amount=fund.base_margin_amount,
                    transfer_order=fund.transfer_order,
                )

            bq = db.query(Blacklist)
            if self.user_id is not None:
                bq = bq.filter(Blacklist.user_id == self.user_id)
            bl = bq.all()
            self.blacklist = {b.symbol for b in bl}

            sq = db.query(SymbolRule)
            if self.user_id is not None:
                sq = sq.filter(SymbolRule.user_id == self.user_id)
            sr_list = sq.all()
            self.symbol_rules = {
                sr.symbol: SymbolRuleSnapshot(
                    symbol=sr.symbol,
                    open_spread=sr.open_spread,
                    close_spread=sr.close_spread,
                    order_amount=sr.order_amount,
                    remove_spread=sr.remove_spread,
                    close_funding_ratio=sr.close_funding_ratio,
                    repay_funding_ratio=sr.repay_funding_ratio,
                    allow_remove=sr.allow_remove if sr.allow_remove is not None else True,
                    allow_repay=sr.allow_repay if sr.allow_repay is not None else True,
                    max_daily_interest_rate=sr.max_daily_interest_rate,
                    repay_spread=sr.repay_spread,
                )
                for sr in sr_list
            }
            aq = db.query(AccountSymbolRule)
            if self.user_id is not None:
                aq = aq.filter(AccountSymbolRule.user_id == self.user_id)
            asr_list = aq.all()
            self.account_symbol_rules = {
                (asr.sub_account_id, asr.symbol): AccountSymbolRuleSnapshot(
                    sub_account_id=asr.sub_account_id,
                    symbol=asr.symbol,
                    open_spread=asr.open_spread,
                    close_spread=asr.close_spread,
                    order_amount=asr.order_amount,
                    remove_spread=asr.remove_spread,
                    close_funding_ratio=asr.close_funding_ratio,
                    repay_funding_ratio=asr.repay_funding_ratio,
                    max_daily_interest_rate=asr.max_daily_interest_rate,
                    repay_spread=asr.repay_spread,
                    max_borrow_amount=asr.max_borrow_amount,
                    is_enabled=asr.is_enabled if asr.is_enabled is not None else True,
                )
                for asr in asr_list
            }
            logger.debug(f"Config reloaded: {len(self.blacklist)} blacklisted, {len(self.symbol_rules)} symbol rules, {len(self.account_symbol_rules)} account-symbol rules")
        finally:
            db.close()
