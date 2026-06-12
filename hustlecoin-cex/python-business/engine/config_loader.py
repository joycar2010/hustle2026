import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import GlobalRules, FundRules, Blacklist
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GlobalRulesSnapshot:
    auto_push_spread: Decimal = Decimal("0.8")
    remove_spread: Decimal = Decimal("0.5")
    borrow_spread: Decimal = Decimal("0.5")
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
    max_positions: int = 10
    auto_start_on_boot: bool = False
    futures_liquidation_threshold: Decimal | None = None
    repay_spread: Decimal | None = None
    max_daily_interest_rate: Decimal | None = None
    slippage_pct: Decimal = Decimal("0.1")
    follow_type: str = "market"
    stabilize_sec: Decimal = Decimal("0")
    tier_ratios: str = ""
    borrow_rate_per_sec: Decimal = Decimal("2")
    borrow_via_otoco: bool = False
    otoco_legs: int = 2
    hedge_via_master: bool = False
    max_spread_pct: Decimal = Decimal("3.0")


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


DEFAULT_GLOBAL = GlobalRulesSnapshot()
DEFAULT_FUND = FundRulesSnapshot()


class ConfigLoader:
    def __init__(self, user_id: int = None):
        self.user_id = user_id
        self.global_rules: GlobalRulesSnapshot = DEFAULT_GLOBAL
        self.fund_rules: FundRulesSnapshot = DEFAULT_FUND
        self.blacklist: set[str] = set()
        self._running = False

    async def start(self):
        self._running = True
        await asyncio.to_thread(self._reload)
        asyncio.create_task(self._poll_loop())
        logger.info("ConfigLoader started")

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
            # 按 user_id 取本用户规则行;legacy(user_id=None)引擎回退 first()
            rq = db.query(GlobalRules)
            rules = (rq.filter(GlobalRules.user_id == self.user_id).first()
                     if self.user_id is not None else rq.first())
            if rules:
                self.global_rules = GlobalRulesSnapshot(
                    auto_push_spread=rules.auto_push_spread,
                    remove_spread=rules.remove_spread,
                    borrow_spread=rules.borrow_spread if getattr(rules, "borrow_spread", None) is not None else Decimal("0.5"),
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
                    max_positions=rules.max_positions or 10,
                    auto_start_on_boot=bool(rules.auto_start_on_boot),
                    futures_liquidation_threshold=rules.futures_liquidation_threshold,
                    repay_spread=rules.repay_spread,
                    max_daily_interest_rate=rules.max_daily_interest_rate,
                    slippage_pct=rules.slippage_pct if rules.slippage_pct is not None else Decimal("0.1"),
                    follow_type=rules.follow_type or "market",
                    stabilize_sec=rules.stabilize_sec if rules.stabilize_sec is not None else Decimal("0"),
                    tier_ratios=rules.tier_ratios or "",
                    borrow_rate_per_sec=rules.borrow_rate_per_sec if getattr(rules, "borrow_rate_per_sec", None) is not None else Decimal("2"),
                    borrow_via_otoco=bool(getattr(rules, "borrow_via_otoco", False)),
                    otoco_legs=int(getattr(rules, "otoco_legs", 2) or 2),
                    hedge_via_master=bool(getattr(rules, "hedge_via_master", False)),
                    max_spread_pct=rules.max_spread_pct if getattr(rules, "max_spread_pct", None) is not None else Decimal("3.0"),
                )

            fund = db.query(FundRules).first()
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

            bl = db.query(Blacklist).all()
            self.blacklist = {b.symbol for b in bl}
            logger.debug(f"Config reloaded: {len(self.blacklist)} blacklisted symbols")
        finally:
            db.close()
