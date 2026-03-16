"""Timing Configuration Model"""
from sqlalchemy import Column, Integer, String, Float, TIMESTAMP, Boolean, Text, text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class TimingConfig(Base):
    """Strategy timing configuration model with three-tier inheritance"""
    __tablename__ = "strategy_timing_configs"

    id = Column(Integer, primary_key=True, index=True)
    config_level = Column(String(20), nullable=False)  # 'global', 'strategy_type', 'instance'
    strategy_type = Column(String(50), nullable=True)  # 'reverse_opening', 'reverse_closing', etc.
    strategy_instance_id = Column(Integer, nullable=True)

    # Trigger control group
    trigger_check_interval = Column(Float, nullable=False, default=0.5)
    opening_trigger_count = Column(Integer, nullable=False, default=3)
    closing_trigger_count = Column(Integer, nullable=False, default=3)

    # Order execution group
    binance_timeout = Column(Float, nullable=False, default=5.0)
    bybit_timeout = Column(Float, nullable=False, default=0.1)
    order_check_interval = Column(Float, nullable=False, default=0.2)
    spread_check_interval = Column(Float, nullable=False, default=2.0)
    mt5_deal_sync_wait = Column(Float, nullable=False, default=3.0)

    # Flow control group
    api_spam_prevention_delay = Column(Float, nullable=False, default=3.0)
    delayed_single_leg_check_delay = Column(Float, nullable=False, default=10.0)
    delayed_single_leg_second_check_delay = Column(Float, nullable=False, default=1.0)

    # Retry configuration group
    api_retry_times = Column(Integer, nullable=False, default=3)
    api_retry_delay = Column(Float, nullable=False, default=0.5)
    max_binance_limit_retries = Column(Integer, nullable=False, default=25)

    # Wait delay group
    open_wait_after_cancel_no_trade = Column(Float, nullable=False, default=3.0)
    open_wait_after_cancel_part = Column(Float, nullable=False, default=2.0)
    close_wait_after_cancel_no_trade = Column(Float, nullable=False, default=3.0)
    close_wait_after_cancel_part = Column(Float, nullable=False, default=2.0)

    # Frontend interaction group
    status_polling_interval = Column(Float, nullable=False, default=5.0)
    debounce_delay = Column(Float, nullable=False, default=0.5)

    # Template and locking
    template = Column(String(50), nullable=True)
    is_locked = Column(Boolean, nullable=False, default=False)
    locked_by = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True)
    locked_at = Column(TIMESTAMP, nullable=True)

    # Metadata
    created_at = Column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    created_by = Column(Integer, nullable=True)

    # Relationships
    history = relationship("TimingConfigHistory", back_populates="config", cascade="all, delete-orphan")


class TimingConfigHistory(Base):
    """Timing configuration change history"""
    __tablename__ = "timing_config_history"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey('strategy_timing_configs.id', ondelete='CASCADE'), nullable=False, index=True)
    config_level = Column(String(20), nullable=False)
    strategy_type = Column(String(50), nullable=True, index=True)
    strategy_instance_id = Column(Integer, nullable=True)

    # Configuration data (all parameters stored as JSON)
    config_data = Column(JSONB, nullable=False)
    template = Column(String(50), nullable=True)

    # Metadata
    created_at = Column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'), index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True)
    change_reason = Column(Text, nullable=True)

    # Relationships
    config = relationship("TimingConfig", back_populates="history")


class TimingConfigTemplate(Base):
    """Custom timing configuration templates"""
    __tablename__ = "timing_config_templates"

    id = Column(Integer, primary_key=True, index=True)
    strategy_type = Column(String(50), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    config_data = Column(JSONB, nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'), index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True)
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
