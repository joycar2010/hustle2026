from sqlalchemy import (
    Column, Integer, String, Boolean, Numeric, DateTime, Text, JSON,
    ForeignKey, UniqueConstraint, func,
)

from app.db.models import Base


class ProxyPool(Base):
    __tablename__ = "proxy_pool"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=True)
    host = Column(String(100), nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String(100), nullable=True)
    password = Column(String(200), nullable=True)
    protocol = Column(String(20), nullable=False, default="http")
    provider = Column(String(30), nullable=False, default="custom")
    status = Column(String(20), nullable=False, default="active")
    health_score = Column(Integer, default=100)
    last_check_at = Column(DateTime(timezone=True), nullable=True)
    region = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AccountProxyBinding(Base):
    __tablename__ = "account_proxy_bindings"

    id = Column(Integer, primary_key=True)
    sub_account_id = Column(Integer, ForeignKey("sub_accounts.id"), nullable=False)
    proxy_id = Column(Integer, ForeignKey("proxy_pool.id"), nullable=False)
    platform = Column(String(30), nullable=False, default="binance")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("sub_account_id", "platform", name="uq_account_proxy_platform"),
    )


class ProxyHealthLog(Base):
    __tablename__ = "proxy_health_logs"

    id = Column(Integer, primary_key=True)
    proxy_id = Column(Integer, ForeignKey("proxy_pool.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    latency_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    checked_at = Column(DateTime(timezone=True), server_default=func.now())


class IpipgoOrder(Base):
    __tablename__ = "ipipgo_orders"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(100), unique=True, nullable=False)
    product_name = Column(String(100), nullable=True)
    ip_address = Column(String(50), nullable=True)
    port = Column(Integer, nullable=True)
    protocol = Column(String(20), nullable=True)
    region = Column(String(100), nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    days_left = Column(Integer, nullable=True)
    raw_data = Column(JSON, nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now())
