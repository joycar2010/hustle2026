from pydantic import BaseModel, field_validator
from datetime import datetime
from decimal import Decimal
from typing import Optional

from app.db.schemas import validators as V


class GlobalRulesUpdate(BaseModel):
    auto_push_spread: Optional[Decimal] = None
    remove_spread: Optional[Decimal] = None
    borrow_spread: Optional[Decimal] = None
    open_spread: Optional[Decimal] = None
    close_spread: Optional[Decimal] = None
    order_amount: Optional[Decimal] = None
    close_funding_ratio: Optional[Decimal] = None
    repay_funding_ratio: Optional[Decimal] = None
    borrow_delay_sec: Optional[int] = None
    confirm_delay_sec: Optional[int] = None
    confirm_skip_spread: Optional[Decimal] = None
    repay_ban_minutes: Optional[int] = None
    interest_filter: Optional[Decimal] = None
    slippage_pct: Optional[Decimal] = None
    follow_type: Optional[str] = None
    stabilize_sec: Optional[Decimal] = None
    tier_ratios: Optional[str] = None
    borrow_rate_per_sec: Optional[Decimal] = None
    borrow_via_otoco: Optional[bool] = None
    borrow_mode: Optional[str] = None
    otoco_legs: Optional[int] = None
    multi_max_accounts_per_symbol: Optional[int] = None
    hedge_via_master: Optional[bool] = None
    hedge_auto_converge: Optional[bool] = None   # 净敞口自动收敛:裸多(实仓>在管)自动 reduceOnly 对齐;关=只告警
    max_spread_pct: Optional[Decimal] = None
    min_volume_24h: Optional[Decimal] = None
    min_volume_24h_futures: Optional[Decimal] = None
    block_risky_open: Optional[bool] = None
    filter_duration_ms: Optional[int] = None
    min_borrow_usdt: Optional[Decimal] = None
    collateral_ratio: Optional[Decimal] = None
    taker_fee_spot: Optional[Decimal] = None
    taker_fee_futures: Optional[Decimal] = None
    bnb_burn_enabled: Optional[bool] = None
    removed_cooldown_minutes: Optional[int] = None
    open_spread_buffer: Optional[Decimal] = None
    max_loss_per_position: Optional[Decimal] = None   # 单仓最大亏损止损(USDT,0/空=禁用)
    spread_stale_sec: Optional[int] = None            # 利差监控新鲜阈值(秒,系统全局)
    net_gate_mode: Optional[str] = None               # 净期望闸: off/shadow/enforce
    hedge_auto_converge: Optional[bool] = None        # 净敞口自动收敛(裸多reduceOnly对齐)
    spot_order_mode: Optional[str] = None             # 现货腿下单: market/maker

    @field_validator("spread_stale_sec")
    @classmethod
    def _v_stale(cls, v, info):
        return V.rng(v, 5, 86400, info.field_name)

    @field_validator("auto_push_spread", "confirm_skip_spread", "max_spread_pct", "slippage_pct",
                     "interest_filter", "open_spread_buffer")
    @classmethod
    def _v_pct(cls, v, info):
        return V.rng(v, 0, 100, info.field_name)

    # 点差阈值允许负值(与单币/逐账户规则口径一致:负基差行情下开/平/还/挂单需要负阈值);范围 [-100, 100]
    @field_validator("remove_spread", "borrow_spread", "open_spread", "close_spread")
    @classmethod
    def _v_spread(cls, v, info):
        return V.rng(v, -100, 100, info.field_name)

    @field_validator("close_funding_ratio", "repay_funding_ratio")
    @classmethod
    def _v_ratio(cls, v, info):
        return V.rng(v, 0, 1000, info.field_name)

    @field_validator("order_amount", "min_borrow_usdt", "min_volume_24h", "min_volume_24h_futures",
                     "max_loss_per_position")
    @classmethod
    def _v_amount(cls, v, info):
        return V.rng(v, 0, 1_000_000_000_000, info.field_name)

    @field_validator("collateral_ratio")
    @classmethod
    def _v_collateral(cls, v, info):
        return V.rng(v, 0, 1, info.field_name)

    @field_validator("borrow_rate_per_sec")
    @classmethod
    def _v_rate(cls, v, info):
        return V.rng(v, 0, 2, info.field_name)

    @field_validator("filter_duration_ms")
    @classmethod
    def _v_filter(cls, v, info):
        return V.rng(v, 0, 600000, info.field_name)

    @field_validator("taker_fee_spot", "taker_fee_futures")
    @classmethod
    def _v_fee(cls, v, info):
        return V.rng(v, 0, 0.05, info.field_name)

    @field_validator("removed_cooldown_minutes", "repay_ban_minutes")
    @classmethod
    def _v_minutes(cls, v, info):
        return V.rng(v, 0, 100000, info.field_name)

    @field_validator("borrow_delay_sec", "confirm_delay_sec")
    @classmethod
    def _v_delay(cls, v, info):
        return V.rng(v, 0, 3600, info.field_name)

    @field_validator("stabilize_sec")
    @classmethod
    def _v_stabilize(cls, v, info):
        return V.rng(v, 0, 60, info.field_name)

    @field_validator("otoco_legs")
    @classmethod
    def _v_legs(cls, v):
        if v is None:
            return v
        if int(v) not in (1, 2, 3):
            raise ValueError("撤单腿数只能是 1、2 或 3")
        return v

    @field_validator("borrow_mode")
    @classmethod
    def _v_borrow_mode(cls, v):
        if v is None:
            return v
        if str(v) not in ("repay", "otoco", "single", "multi"):
            raise ValueError("借币方式只能是 repay/otoco/single/multi")
        return v

    @field_validator("net_gate_mode")
    @classmethod
    def _v_net_gate(cls, v):
        if v is None:
            return v
        if str(v) not in ("off", "shadow", "enforce"):
            raise ValueError("净期望闸模式只能是 off/shadow/enforce")
        return v

    @field_validator("spot_order_mode")
    @classmethod
    def _v_spot_mode(cls, v):
        if v is None:
            return v
        if str(v) not in ("market", "maker"):
            raise ValueError("现货下单模式只能是 market/maker")
        return v

    @field_validator("multi_max_accounts_per_symbol")
    @classmethod
    def _v_multi_max(cls, v, info):
        return V.rng(v, 1, 50, info.field_name)

    @field_validator("follow_type")
    @classmethod
    def _v_follow(cls, v):
        return V.follow_type(v)

    @field_validator("tier_ratios")
    @classmethod
    def _v_tier(cls, v):
        return V.tier_ratios(v)


class GlobalRulesResponse(BaseModel):
    id: int
    auto_push_spread: Decimal
    remove_spread: Decimal
    borrow_spread: Optional[Decimal] = None
    open_spread: Decimal
    close_spread: Decimal
    order_amount: Decimal
    close_funding_ratio: Decimal
    repay_funding_ratio: Decimal
    borrow_delay_sec: int
    confirm_delay_sec: int
    confirm_skip_spread: Decimal
    repay_ban_minutes: int
    interest_filter: Decimal
    slippage_pct: Optional[Decimal] = None
    follow_type: Optional[str] = "market"
    stabilize_sec: Optional[Decimal] = None
    tier_ratios: Optional[str] = ""
    borrow_rate_per_sec: Optional[Decimal] = 2
    borrow_via_otoco: Optional[bool] = False
    borrow_mode: Optional[str] = None
    otoco_legs: Optional[int] = 2
    multi_max_accounts_per_symbol: Optional[int] = 3
    hedge_via_master: Optional[bool] = False
    hedge_auto_converge: Optional[bool] = False
    max_spread_pct: Optional[Decimal] = 3.0
    min_volume_24h: Optional[Decimal] = 0
    min_volume_24h_futures: Optional[Decimal] = 0
    block_risky_open: Optional[bool] = False
    filter_duration_ms: Optional[int] = 0
    min_borrow_usdt: Optional[Decimal] = 0
    collateral_ratio: Optional[Decimal] = 1
    taker_fee_spot: Optional[Decimal] = 0.00075
    taker_fee_futures: Optional[Decimal] = 0.00075
    bnb_burn_enabled: Optional[bool] = False
    removed_cooldown_minutes: Optional[int] = 0
    open_spread_buffer: Optional[Decimal] = 0
    max_loss_per_position: Optional[Decimal] = None
    spread_stale_sec: Optional[int] = 300
    version: Optional[int] = 0
    updated_at: datetime

    model_config = {"from_attributes": True}
