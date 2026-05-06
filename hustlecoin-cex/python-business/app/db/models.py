from sqlalchemy import (
    Column, Integer, String, Boolean, Numeric, DateTime, Text, JSON,
    func,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Symbol(Base):
    __tablename__ = "symbols"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(30), unique=True, nullable=False)
    base_asset = Column(String(20), nullable=False)
    quote_asset = Column(String(10), nullable=False)
    margin_tradable = Column(Boolean, default=False)
    futures_tradable = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_new_coin = Column(Boolean, server_default='false')
    is_delisting = Column(Boolean, server_default='false')
    allow_open = Column(Boolean, server_default='true')
    volume_24h = Column(Numeric(20, 2), nullable=True)
    volume_updated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SubAccount(Base):
    __tablename__ = "sub_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    note = Column(String(20), nullable=False)
    email = Column(String(100), nullable=False)
    api_key = Column(String(100), nullable=False)
    api_secret = Column(String(200), nullable=False)
    is_enabled = Column(Boolean, default=True)
    margin_enabled = Column(Boolean, default=False)
    futures_enabled = Column(Boolean, default=False)
    spot_enabled = Column(Boolean, default=False)
    bnb_burn_enabled = Column(Boolean, default=False)
    bnb_interest_enabled = Column(Boolean, default=False)
    last_validated_at = Column(DateTime(timezone=True), nullable=True)
    order_amount = Column(Numeric(15, 2), nullable=True)
    base_margin_amount = Column(Numeric(15, 2), nullable=True)
    single_transfer_amount = Column(Numeric(15, 2), nullable=True)
    risk_threshold = Column(Numeric(5, 2), nullable=True)
    min_balance = Column(Numeric(10, 2), nullable=True)
    single_order_amount = Column(Numeric(10, 2), nullable=True)
    max_positions = Column(Integer, nullable=True)
    max_borrow_amount = Column(Numeric(15, 2), nullable=True)
    max_order_count = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MasterAccount(Base):
    __tablename__ = "master_account"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    api_key = Column(String(100), nullable=False)
    api_secret = Column(String(200), nullable=False)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GlobalRules(Base):
    __tablename__ = "global_rules"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    auto_push_spread = Column(Numeric(10, 4), default=0.8)
    remove_spread = Column(Numeric(10, 4), default=0.5)
    open_spread = Column(Numeric(10, 4), default=0.8)
    close_spread = Column(Numeric(10, 4), default=0.2)
    order_amount = Column(Numeric(15, 2), default=500)
    close_funding_ratio = Column(Numeric(10, 4), default=1.2)
    repay_funding_ratio = Column(Numeric(10, 4), default=1.2)
    borrow_delay_sec = Column(Integer, default=3)
    confirm_delay_sec = Column(Integer, default=2)
    confirm_skip_spread = Column(Numeric(10, 4), default=2.0)
    repay_ban_minutes = Column(Integer, default=30)
    interest_filter = Column(Numeric(10, 4), default=1.0)
    max_positions = Column(Integer, default=10)
    auto_start_on_boot = Column(Boolean, default=False)
    futures_liquidation_threshold = Column(Numeric(5, 2), nullable=True)
    max_loss_per_position = Column(Numeric(15, 2), nullable=True)
    circuit_breaker_spread_pct = Column(Numeric(10, 4), nullable=True)
    circuit_breaker_pause_sec = Column(Integer, default=300)
    max_daily_interest_rate = Column(Numeric(10, 6), nullable=True)
    repay_spread = Column(Numeric(10, 4), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Blacklist(Base):
    __tablename__ = "blacklist"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), unique=True, nullable=False)
    reason = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FeishuConfig(Base):
    __tablename__ = "feishu_config"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    webhook_url = Column(String(300))
    secret_key = Column(String(100))
    app_id = Column(String(100), nullable=True)
    app_secret = Column(String(200), nullable=True)
    alert_interval_sec = Column(Integer, default=5)
    alert_count = Column(Integer, default=1)
    margin_rate_alert = Column(Numeric(10, 2), default=30)
    leverage_risk_alert = Column(Numeric(10, 4), default=1.3)
    enable_transfer_fail_alert = Column(Boolean, default=True)
    enable_new_borrow_alert = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FundRules(Base):
    __tablename__ = "fund_rules"

    id = Column(Integer, primary_key=True)
    bnb_min_quantity = Column(Numeric(10, 4), default=0.15)
    bnb_buy_trigger_pct = Column(Numeric(10, 4), default=50)
    bnb_buy_amount = Column(Numeric(10, 4), default=0.1)
    bnb_debt_auto_repay = Column(Boolean, default=True)
    bnb_debt_threshold = Column(Numeric(10, 4), default=0.1)
    usdt_debt_auto_repay = Column(Boolean, default=True)
    usdt_debt_threshold = Column(Numeric(15, 2), default=20)
    usdt_debt_interval_sec = Column(Integer, default=3600)
    bnb_convert_interval_sec = Column(Integer, default=3600)
    debt_convert_interval_sec = Column(Integer, default=21600)
    risk_value_threshold = Column(Numeric(10, 4), default=1.5)
    single_transfer_amount = Column(Numeric(15, 2), default=500)
    base_margin_amount = Column(Numeric(15, 2), default=500)
    transfer_order = Column(String(50), default="futures,spot,margin")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SymbolRule(Base):
    __tablename__ = "symbol_rules"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    symbol = Column(String(30), nullable=False)
    open_spread = Column(Numeric(10, 4), nullable=True)
    close_spread = Column(Numeric(10, 4), nullable=True)
    order_amount = Column(Numeric(15, 2), nullable=True)
    remove_spread = Column(Numeric(10, 4), nullable=True)
    close_funding_ratio = Column(Numeric(10, 4), nullable=True)
    repay_funding_ratio = Column(Numeric(10, 4), nullable=True)
    allow_remove = Column(Boolean, server_default='true')
    allow_repay = Column(Boolean, server_default='true')
    max_daily_interest_rate = Column(Numeric(10, 6), nullable=True)
    repay_spread = Column(Numeric(10, 4), nullable=True)
    source = Column(String(10), server_default='custom')
    is_temporary = Column(Boolean, server_default='false')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AccountSymbolRule(Base):
    __tablename__ = "account_symbol_rules"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    sub_account_id = Column(Integer, nullable=False)
    symbol = Column(String(30), nullable=False)
    open_spread = Column(Numeric(10, 4), nullable=True)
    close_spread = Column(Numeric(10, 4), nullable=True)
    order_amount = Column(Numeric(15, 2), nullable=True)
    remove_spread = Column(Numeric(10, 4), nullable=True)
    close_funding_ratio = Column(Numeric(10, 4), nullable=True)
    repay_funding_ratio = Column(Numeric(10, 4), nullable=True)
    max_daily_interest_rate = Column(Numeric(10, 6), nullable=True)
    repay_spread = Column(Numeric(10, 4), nullable=True)
    max_borrow_amount = Column(Numeric(15, 2), nullable=True)
    is_enabled = Column(Boolean, server_default='true')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PendingBlacklist(Base):
    __tablename__ = "pending_blacklist"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(30), nullable=False, unique=True)
    reason = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AiCoinConfig(Base):
    __tablename__ = "aicoin_config"

    id = Column(Integer, primary_key=True)
    api_key = Column(String(200), nullable=True)
    api_secret = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# Import engine models into same Base so create_all() covers them
from engine.models import Position, TradeLog, EngineState  # noqa: E402, F401
