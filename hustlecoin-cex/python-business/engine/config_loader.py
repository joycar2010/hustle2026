import asyncio
import logging
from dataclasses import dataclass, field, replace
from decimal import Decimal

from sqlalchemy import or_
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
    borrow_mode: str = "repay"
    otoco_legs: int = 2
    multi_max_accounts_per_symbol: int = 3
    hedge_via_master: bool = False
    max_spread_pct: Decimal = Decimal("3.0")
    min_volume_24h: Decimal = Decimal("0")
    min_volume_24h_futures: Decimal = Decimal("0")
    block_risky_open: bool = False
    filter_duration_ms: int = 0
    min_borrow_usdt: Decimal = Decimal("0")
    collateral_ratio: Decimal = Decimal("1")
    taker_fee_spot: Decimal = Decimal("0.00075")
    taker_fee_futures: Decimal = Decimal("0.00075")
    bnb_burn_enabled: bool = False
    removed_cooldown_minutes: int = 0
    open_spread_buffer: Decimal = Decimal("0")
    max_loss_per_position: Decimal | None = None   # 单仓最大亏损止损(USDT,None/0=禁用)
    net_gate_mode: str = "shadow"   # 净期望闸: off(不评估)/shadow(评估记录不拦)/enforce(E≤0拒开)


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

# 「系统后端规则」(/rules 黄框)= 全局系统设置,由 user_id IS NULL 行主管,对所有用户一致;
# admin /admin/global-rules「系统后端规则」TAB 编辑。per-user worker 的这些字段从 NULL 行覆盖。
_SYSTEM_FIELDS = (
    "follow_type", "slippage_pct", "stabilize_sec", "tier_ratios", "borrow_rate_per_sec",
    "borrow_via_otoco", "borrow_mode", "otoco_legs", "multi_max_accounts_per_symbol",
    "hedge_via_master", "max_spread_pct", "min_volume_24h",
    "min_volume_24h_futures", "block_risky_open", "filter_duration_ms", "min_borrow_usdt",
    "collateral_ratio", "removed_cooldown_minutes", "open_spread_buffer",
    "taker_fee_spot", "taker_fee_futures", "net_gate_mode",
)
_SYS_BOOL = {"borrow_via_otoco", "hedge_via_master", "block_risky_open"}
_SYS_INT = {"otoco_legs", "multi_max_accounts_per_symbol", "filter_duration_ms", "removed_cooldown_minutes"}
_SYS_STR = {"follow_type", "tier_ratios", "borrow_mode"}


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
            # 按 user_id 取本用户规则行;legacy(user_id=None)引擎确定性取 user_id IS NULL 行
            # (多行表 .first() 无序,UPDATE 后会漂行 —— 与 /rules 读写口径对齐)
            rq = db.query(GlobalRules)
            rules = (rq.filter(GlobalRules.user_id == self.user_id).first()
                     if self.user_id is not None
                     else rq.filter(GlobalRules.user_id.is_(None)).order_by(GlobalRules.id).first())
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
                    borrow_mode=(getattr(rules, "borrow_mode", None) or ""),
                    otoco_legs=int(getattr(rules, "otoco_legs", 2) or 2),
                    multi_max_accounts_per_symbol=int(getattr(rules, "multi_max_accounts_per_symbol", 3) or 3),
                    hedge_via_master=bool(getattr(rules, "hedge_via_master", False)),
                    max_spread_pct=rules.max_spread_pct if getattr(rules, "max_spread_pct", None) is not None else Decimal("3.0"),
                    min_volume_24h=rules.min_volume_24h if getattr(rules, "min_volume_24h", None) is not None else Decimal("0"),
                    min_volume_24h_futures=rules.min_volume_24h_futures if getattr(rules, "min_volume_24h_futures", None) is not None else Decimal("0"),
                    block_risky_open=bool(getattr(rules, "block_risky_open", False)),
                    filter_duration_ms=int(getattr(rules, "filter_duration_ms", 0) or 0),
                    min_borrow_usdt=rules.min_borrow_usdt if getattr(rules, "min_borrow_usdt", None) is not None else Decimal("0"),
                    collateral_ratio=rules.collateral_ratio if getattr(rules, "collateral_ratio", None) is not None else Decimal("1"),
                    taker_fee_spot=rules.taker_fee_spot if getattr(rules, "taker_fee_spot", None) is not None else Decimal("0.00075"),
                    taker_fee_futures=rules.taker_fee_futures if getattr(rules, "taker_fee_futures", None) is not None else Decimal("0.00075"),
                    bnb_burn_enabled=bool(getattr(rules, "bnb_burn_enabled", False)),
                    removed_cooldown_minutes=int(getattr(rules, "removed_cooldown_minutes", 0) or 0),
                    open_spread_buffer=rules.open_spread_buffer if getattr(rules, "open_spread_buffer", None) is not None else Decimal("0"),
                    max_loss_per_position=getattr(rules, "max_loss_per_position", None),
                    net_gate_mode=(getattr(rules, "net_gate_mode", None) or "shadow"),
                )

            # 系统后端规则(黄框)由全局 NULL 行主管:per-user worker 把这些字段从 NULL 行覆盖
            # (admin「系统后端规则」TAB 编辑;per-user 行的同名字段忽略,对所有用户一致)
            if rules is not None and self.user_id is not None:
                sysrow = rq.filter(GlobalRules.user_id.is_(None)).order_by(GlobalRules.id).first()
                if sysrow is not None:
                    ov = {}
                    for f in _SYSTEM_FIELDS:
                        v = getattr(sysrow, f, None)
                        if v is None:
                            continue
                        ov[f] = bool(v) if f in _SYS_BOOL else int(v) if f in _SYS_INT else str(v) if f in _SYS_STR else v
                    if ov:
                        self.global_rules = replace(self.global_rules, **ov)

            # borrow_mode 归一化:新枚举字段为空时由旧 borrow_via_otoco 推导(灰度兼容,零行为变动)。
            # 在系统行覆盖之后做,保证用的是权威值(borrow_mode/borrow_via_otoco 均系统级)。
            if not getattr(self.global_rules, "borrow_mode", ""):
                derived = "otoco" if self.global_rules.borrow_via_otoco else "repay"
                self.global_rules = replace(self.global_rules, borrow_mode=derived)

            # 资金规则按 user 隔离;legacy(user_id=None)引擎确定性取 NULL 行
            fq = db.query(FundRules)
            fund = (fq.filter(FundRules.user_id == self.user_id).first()
                    if self.user_id is not None
                    else fq.filter(FundRules.user_id.is_(None)).order_by(FundRules.id).first())
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

            # 黑名单 = 本用户黑名单 ∪ 全局系统黑名单(user_id IS NULL:死币/借币池无券等,对所有用户生效)
            blq = db.query(Blacklist)
            bl = (blq.filter(or_(Blacklist.user_id == self.user_id, Blacklist.user_id.is_(None))).all()
                  if self.user_id is not None
                  else blq.filter(Blacklist.user_id.is_(None)).all())
            self.blacklist = {b.symbol for b in bl}
            logger.debug(f"Config reloaded: {len(self.blacklist)} blacklisted symbols")
        finally:
            db.close()
