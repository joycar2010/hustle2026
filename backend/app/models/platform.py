import uuid
from datetime import datetime
from sqlalchemy import Column, String, SmallInteger, Boolean, Float, Integer, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Platform(Base):
    """Platform configuration — CEX exchanges and MT5 brokers"""

    __tablename__ = "platforms"

    platform_id = Column(SmallInteger, primary_key=True)
    platform_name = Column(String(20), nullable=False)
    display_name = Column(String(50), nullable=False, default="")
    platform_type = Column(String(10), nullable=False, default="cex", comment="cex / mt5")
    api_base_url = Column(String(100), nullable=False)
    ws_base_url = Column(String(100), nullable=False)
    account_api_type = Column(String(30), nullable=False)
    market_api_type = Column(String(30), nullable=False)
    auth_type = Column(String(40), nullable=False, default="hmac_sha256", comment="hmac_sha256 / hmac_sha256_passphrase / hmac_sha512 / bridge_http")
    position_mode = Column(String(20), nullable=False, default="hedging", comment="hedging / one_way / net")
    maker_mechanism = Column(String(40), nullable=False, default="none", comment="price_match_queue / post_only_flag / order_type_post_only / none")
    default_tif = Column(String(10), nullable=False, default="GTC")
    base_currency = Column(String(10), nullable=False, default="USDT")
    mt5_template_path = Column(String(500), nullable=True, comment="MT5模板路径，用于克隆生成客户端运行目录")
    requires_proxy = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    accounts = relationship("Account", back_populates="platform")
    symbols = relationship("PlatformSymbol", back_populates="platform", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Platform(platform_id={self.platform_id}, name={self.platform_name})>"


class PlatformSymbol(Base):
    """Per-platform symbol configuration — contract specs, precision, fees"""

    __tablename__ = "platform_symbols"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform_id = Column(SmallInteger, ForeignKey("platforms.platform_id"), nullable=False, index=True)
    symbol = Column(String(30), nullable=False, comment="Platform-specific symbol name")
    base_asset = Column(String(10), nullable=False, comment="Standardized asset: XAU, XAG, CL, BZ, NG")
    quote_asset = Column(String(10), nullable=False, default="USDT")

    # Contract specification
    contract_unit = Column(Float, nullable=False, default=1.0, comment="Contract multiplier: Binance XAU=1, MT5 XAU=100, MT5 XAG=5000")
    qty_unit = Column(String(20), nullable=False, default="XAU", comment="Display unit: XAU, XAG, BBL, mmBtu, lot, contract")
    qty_precision = Column(Integer, nullable=False, default=0, comment="Decimal places for quantity")
    qty_step = Column(Float, nullable=False, default=1.0, comment="Minimum qty increment")
    min_qty = Column(Float, nullable=False, default=1.0, comment="Minimum order quantity")
    price_precision = Column(Integer, nullable=False, default=2, comment="Decimal places for price")
    price_step = Column(Float, nullable=False, default=0.01, comment="Tick size")

    # Fees
    maker_fee_rate = Column(Float, nullable=False, default=0.0002)
    taker_fee_rate = Column(Float, nullable=False, default=0.0005)
    fee_type = Column(String(20), nullable=False, default="percentage", comment="percentage / per_lot")
    fee_per_lot = Column(Float, nullable=False, default=0.0, comment="Fixed fee per lot (MT5 broker commission)")

    # Margin
    margin_rate_initial = Column(Float, nullable=False, default=0.01)
    margin_rate_maintenance = Column(Float, nullable=False, default=0.005)

    # Funding / swap
    funding_interval = Column(String(10), nullable=True, comment="8h / 4h / 1h / null for MT5")
    swap_type = Column(String(20), nullable=True, comment="points / percentage / null for CEX")

    # Trading hours (JSON: {"summer_open":"Mon 06:00","summer_close":"Sat 05:00",...})
    trading_hours = Column(JSONB, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    # Relationships
    platform = relationship("Platform", back_populates="symbols")

    def __repr__(self):
        return f"<PlatformSymbol({self.platform_id}:{self.symbol} unit={self.contract_unit})>"


class HedgingPair(Base):
    """Hedging product pair — links two accounts+symbols for arbitrage"""

    __tablename__ = "hedging_pairs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pair_name = Column(String(60), nullable=False, comment="Display name: 黄金套利, 白银套利")
    pair_code = Column(String(30), nullable=False, unique=True, comment="Code: XAU, XAG, CL, BZ, NG")

    # Side A (主账号)
    account_a_id = Column(UUID(as_uuid=True), ForeignKey("accounts.account_id"), nullable=True)
    symbol_a_id = Column(UUID(as_uuid=True), ForeignKey("platform_symbols.id"), nullable=False)

    # Side B (对冲账号)
    account_b_id = Column(UUID(as_uuid=True), ForeignKey("accounts.account_id"), nullable=True)
    symbol_b_id = Column(UUID(as_uuid=True), ForeignKey("platform_symbols.id"), nullable=False)

    # Conversion
    conversion_factor = Column(Float, nullable=False, default=100.0, comment="1 unit_b = N unit_a (e.g. 1 lot = 100 XAU)")
    usd_usdt_rate = Column(Float, nullable=False, default=1.0)
    usd_usdt_auto_sync = Column(Boolean, default=False)

    # Spread config
    spread_mode = Column(String(20), nullable=False, default="absolute", comment="absolute / percentage / ticks")
    spread_precision = Column(Integer, nullable=False, default=2)
    default_spread_target = Column(Float, nullable=True, comment="Reference spread for new strategies")

    # Risk limits
    max_position_value_usd = Column(Float, nullable=True, comment="Max position value in USD")
    min_hedgeable_qty_a = Column(Float, nullable=True, comment="Min hedgeable qty on side A")
    min_hedgeable_qty_b = Column(Float, nullable=True, comment="Min hedgeable qty on side B")

    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    account_a = relationship("Account", foreign_keys=[account_a_id])
    account_b = relationship("Account", foreign_keys=[account_b_id])
    symbol_a = relationship("PlatformSymbol", foreign_keys=[symbol_a_id])
    symbol_b = relationship("PlatformSymbol", foreign_keys=[symbol_b_id])

    def __repr__(self):
        return f"<HedgingPair({self.pair_code}: {self.pair_name})>"
