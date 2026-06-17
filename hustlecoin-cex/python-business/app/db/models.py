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
    is_risky = Column(Boolean, server_default='false')
    volume_24h = Column(Numeric(20, 2), nullable=True)            # 现货 24h 成交额(quoteVolume,USDT)
    futures_volume_24h = Column(Numeric(20, 2), nullable=True)    # 合约 24h 成交额(USDT),双腿量过滤用
    volume_updated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RulePreset(Base):
    __tablename__ = "rule_presets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    name = Column(String(50), nullable=False)
    open_spread = Column(Numeric(10, 4), nullable=True)
    close_spread = Column(Numeric(10, 4), nullable=True)
    order_amount = Column(Numeric(15, 2), nullable=True)
    remove_spread = Column(Numeric(10, 4), nullable=True)
    close_funding_ratio = Column(Numeric(10, 4), nullable=True)
    repay_funding_ratio = Column(Numeric(10, 4), nullable=True)
    repay_spread = Column(Numeric(10, 4), nullable=True)
    max_daily_interest_rate = Column(Numeric(10, 6), nullable=True)
    max_borrow_amount = Column(Numeric(15, 2), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


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
    borrow_rate_per_sec = Column(Numeric(6, 2), nullable=True)  # per-account override; null=follow global
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MasterAccount(Base):
    __tablename__ = "master_account"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    account_name = Column(String(100), nullable=True)
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
    borrow_spread = Column(Numeric(10, 4), default=0.5)   # 挂单点差: borrow-and-hold threshold (≤ open_spread)
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
    # Order-quality params (desktop parity). Defaults preserve current behavior.
    slippage_pct = Column(Numeric(10, 4), default=0.1)       # limit-price tolerance vs ask
    follow_type = Column(String(10), default="market")        # "market" | "limit"
    stabilize_sec = Column(Numeric(6, 2), default=0)          # wait after spot sell before futures hedge
    tier_ratios = Column(String(120), default="")             # "0.5:30,0.8:30,1.2:40" (persisted)
    borrow_rate_per_sec = Column(Numeric(6, 2), default=2)    # per-account target borrow pacing (req/s)
    borrow_via_otoco = Column(Boolean, default=False)         # True=借币走 coinmini 同款 IOC OTO/OTOCO;False=borrow-repay
    otoco_legs = Column(Integer, default=2)                   # OTOCO 借币腿数: 2=OTO(2单撤)/3=OTOCO(3单撤)
    hedge_via_master = Column(Boolean, default=False)         # True=合约对冲腿用主账户 key;False=三腿同子账户(原行为)
    max_spread_pct = Column(Numeric(10, 4), default=3.0)      # 点差合理性上限(%): 超过视为行情glitch,跳过该币种下单/平仓(0=不启用)
    min_volume_24h = Column(Numeric(20, 2), default=0)        # 现货24h成交量(USDT)门槛: 低于此的币不自动推送/借币(交易护栏;0=不启用)
    min_volume_24h_futures = Column(Numeric(20, 2), default=0)  # 合约24h成交量(USDT)门槛: 双腿量过滤的合约腿(0=不启用)
    block_risky_open = Column(Boolean, default=False)        # 风险币硬拦开关: 开启后 is_risky 的币也禁止开仓(默认仅展示告警)
    filter_duration_ms = Column(Integer, default=0)          # 信号级防抖: 点差需持续超阈 N ms 才触发借币(coinmini filter_duration_ms;0=不启用)
    min_borrow_usdt = Column(Numeric(15, 2), default=0)      # 单笔借币下限(USDT): 名义低于此跳过,不做尘埃单(0=不启用)
    collateral_ratio = Column(Numeric(6, 4), default=1)      # 抵押率安全垫: OTOCO 借币按 maxBorrowable×此比例封顶(1=借满,不缩)
    open_spread_buffer = Column(Numeric(10, 4), default=0)   # 开仓阈值缓冲(%): 实际要求 spread_short ≥ 借币点差+此值,吸收腿间滑点/~160ms借币延迟(0=不留)
    taker_fee_spot = Column(Numeric(10, 6), default=0.00075)  # 现货吃单费率(仅用于 PnL 口径,可配;开 BNB 抵扣时实际更低)
    taker_fee_futures = Column(Numeric(10, 6), default=0.00075)  # 合约吃单费率(仅用于 PnL 口径,双腿分开)
    bnb_burn_enabled = Column(Boolean, default=False)        # BNB 抵扣手续费开关(每用户):引擎对本用户各子账户统一下发 spot/marginBNBBurn
    removed_cooldown_minutes = Column(Integer, default=0)    # 移除/平仓冷却(分钟): 同币退出后此时长内禁止再借,抑制反复进出(0=不启用)
    spread_stale_sec = Column(Integer, default=300)          # 利差监控新鲜阈值(秒,系统全局): ts 落后全表最新值超此秒数的币在 /spreads 不显示(死币剔除;前端读)
    version = Column(Integer, default=0)                      # 乐观锁版本号(保存事务化用)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Blacklist(Base):
    __tablename__ = "blacklist"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)   # 用户隔离(列+ (user_id,symbol) 唯一约束由迁移 g1a2b3c4d5e6 加;补声明同步模型)
    symbol = Column(String(20), nullable=False)   # 唯一性现为 (user_id, symbol) 复合,故去掉单列 unique
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
    enable_borrow_success_alert = Column(Boolean, default=True)   # 借币成功(开仓/对冲完成)提醒
    enable_repay_success_alert = Column(Boolean, default=True)    # 还币成功(平仓/还币完成)提醒
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FundRules(Base):
    __tablename__ = "fund_rules"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)   # 用户隔离:每用户一行资金规则;legacy=NULL
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
    version = Column(Integer, default=0)                      # 乐观锁版本号(保存事务化用)
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
    max_borrow_amount = Column(Numeric(15, 2), nullable=True)   # 金额限制(借币金额上限,USDT);null=跟随账户/全局
    slippage_pct = Column(Numeric(10, 4), nullable=True)        # 每币种滑点覆盖;null=跟随全局
    follow_type = Column(String(10), nullable=True)            # 每币种跟单方式 market/limit;null=跟随全局
    note = Column(String(120), nullable=True)                 # 备注(展示用,不参与决策)
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
    slippage_pct = Column(Numeric(10, 4), nullable=True)        # 每账户·每币种滑点覆盖;null=跟随单币种/全局
    follow_type = Column(String(10), nullable=True)            # 每账户·每币种跟单方式;null=跟随单币种/全局
    note = Column(String(120), nullable=True)                 # 备注(展示用)
    is_enabled = Column(Boolean, server_default='true')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PendingBlacklist(Base):
    __tablename__ = "pending_blacklist"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(30), nullable=False, unique=True)
    reason = Column(String(500), nullable=True)
    source = Column(String(50), default="binance_announcement")   # 来源(币安公告等)
    announcement_title = Column(Text, nullable=True)              # 触发公告标题
    announcement_url = Column(String(500), nullable=True)         # 公告链接
    is_confirmed = Column(Boolean, default=False)                 # 管理员是否已确认下发
    confirmed_by = Column(Integer, nullable=True)                 # 确认人 user_id
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AiCoinConfig(Base):
    __tablename__ = "aicoin_config"

    id = Column(Integer, primary_key=True)
    api_key = Column(String(200), nullable=True)
    api_secret = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BalanceSnapshot(Base):
    """账户资金净值时间序列(balance_pusher 每 ~10min 落一行/用户),支撑资金曲线/日终对账/回撤监控。
    口径见 app/services/fund_aggregate.aggregate_balances(与实时资金总览同源)。"""
    __tablename__ = "balance_snapshot"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True, index=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    equity = Column(Numeric(18, 4))
    available = Column(Numeric(18, 4))
    borrowed = Column(Numeric(18, 4))
    unrealized_pnl = Column(Numeric(18, 4))
    margin_level_min = Column(Numeric(12, 4), nullable=True)
    bnb = Column(Numeric(18, 8))
    account_count = Column(Integer)


# Import engine models into same Base so create_all() covers them
from engine.models import Position, TradeLog, EngineState  # noqa: E402, F401
