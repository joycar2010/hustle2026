"""Read-only early-borrow analytics models.

These tables intentionally have no relationship with the trading engine's
``pushed_symbols`` or position tables.  They store market observations and
human-review suggestions only; a suggestion can never place an order.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    func,
)

from app.db.models import Base


class EarlyBorrowConfig(Base):
    __tablename__ = "early_borrow_config"

    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    sample_interval_sec = Column(Integer, nullable=False, default=2, server_default="2")
    metrics_interval_sec = Column(Integer, nullable=False, default=300, server_default="300")
    lookback_hours = Column(Integer, nullable=False, default=6, server_default="6")
    warning_spread_pct = Column(Float, nullable=False, default=0.8, server_default="0.8")
    candidate_spread_pct = Column(Float, nullable=False, default=0.45, server_default="0.45")
    trigger_spread_pct = Column(Float, nullable=False, default=1.0, server_default="1.0")
    open_spread_pct = Column(Float, nullable=False, default=0.5, server_default="0.5")
    # MIX's anti-latency buffer, applied to the read-only candidate line.
    open_spread_buffer_pct = Column(Float, nullable=False, default=0.05, server_default="0.05")
    # Suggestions are deliberately conservative.  A trajectory must be very
    # close to a prior jump case before it is shown to an operator.
    similarity_threshold = Column(Float, nullable=False, default=0.85, server_default="0.85")
    notification_cooldown_sec = Column(Integer, nullable=False, default=1800, server_default="1800")
    retention_days = Column(Integer, nullable=False, default=7, server_default="7")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EarlyBorrowTick(Base):
    __tablename__ = "early_borrow_ticks"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(30), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)
    spot_bid = Column(Numeric(30, 12), nullable=True)
    spot_ask = Column(Numeric(30, 12), nullable=True)
    futures_bid = Column(Numeric(30, 12), nullable=True)
    futures_ask = Column(Numeric(30, 12), nullable=True)
    spread_long = Column(Float, nullable=True)
    spread_short = Column(Float, nullable=True)
    source = Column(String(20), nullable=False, default="binance_ws")

    __table_args__ = (
        Index("ix_early_borrow_ticks_symbol_time", "symbol", "captured_at"),
    )


class EarlyBorrowFeature(Base):
    __tablename__ = "early_borrow_features"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(30), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)
    position_ratio = Column(Float, nullable=True)
    account_ratio = Column(Float, nullable=True)
    leverage_ratio = Column(Float, nullable=True)
    open_interest = Column(Float, nullable=True)
    # The five-minute collection pass stores a set of fixed look-back deltas,
    # rather than only the delta since the previous process iteration.  This
    # keeps the six-hour case vector usable after a service restart.
    oi_change_pct = Column(Float, nullable=True)  # backwards-compatible alias for 5m
    oi_change_5m_pct = Column(Float, nullable=True)
    oi_change_15m_pct = Column(Float, nullable=True)
    oi_change_30m_pct = Column(Float, nullable=True)
    oi_change_1h_pct = Column(Float, nullable=True)
    oi_change_3h_pct = Column(Float, nullable=True)
    oi_change_6h_pct = Column(Float, nullable=True)
    source = Column(String(20), nullable=False, default="binance_public")

    __table_args__ = (
        Index("ix_early_borrow_features_symbol_time", "symbol", "captured_at"),
    )


class EarlyBorrowCase(Base):
    __tablename__ = "early_borrow_cases"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(30), nullable=False)
    trigger_at = Column(DateTime(timezone=True), nullable=False, index=True)
    trigger_spread = Column(Float, nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    sample_count = Column(Integer, nullable=False, default=0)
    feature_summary = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="ready")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_early_borrow_cases_symbol_trigger", "symbol", "trigger_at"),
        Index("ix_early_borrow_cases_status", "status"),
    )


class EarlyBorrowCandidate(Base):
    __tablename__ = "early_borrow_candidates"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(30), nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False, index=True)
    current_spread = Column(Float, nullable=False)
    similarity_score = Column(Float, nullable=False)
    estimated_hit_rate = Column(Float, nullable=True)
    matched_case_count = Column(Integer, nullable=False, default=0, server_default="0")
    evidence_case_ids = Column(JSON, nullable=False, default=list)
    case_id = Column(Integer, ForeignKey("early_borrow_cases.id", ondelete="SET NULL"), nullable=True)
    feature_snapshot = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="suggested")
    notified_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_early_borrow_candidates_symbol_time", "symbol", "detected_at"),
        Index("ix_early_borrow_candidates_status", "status"),
        # The monitor's hot read path filters by status/expiry and orders by
        # detection time.  Keep that path index-backed as the seven-day read
        # model grows.
        Index(
            "ix_early_borrow_candidates_status_expiry_time",
            "status",
            "expires_at",
            "detected_at",
        ),
    )
