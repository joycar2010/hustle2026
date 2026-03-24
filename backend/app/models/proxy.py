"""
代理管理数据模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Float, TIMESTAMP, Date, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class ProxyPool(Base):
    """代理池表"""
    __tablename__ = "proxy_pool"

    id = Column(Integer, primary_key=True, autoincrement=True)
    proxy_type = Column(String(20), nullable=False, comment='代理类型: http, https, socks5')
    host = Column(String(255), nullable=False, comment='代理主机地址')
    port = Column(Integer, nullable=False, comment='代理端口')
    username = Column(String(255), nullable=True, comment='代理用户名')
    password = Column(String(255), nullable=True, comment='代理密码')
    provider = Column(String(50), nullable=False, default='custom', comment='代理提供商')
    region = Column(String(50), nullable=True, comment='代理地区')
    ip_address = Column(String(50), nullable=True, comment='代理IP地址')
    expire_time = Column(TIMESTAMP, nullable=True, comment='过期时间')
    status = Column(String(20), nullable=False, default='active', comment='状态')
    health_score = Column(Integer, nullable=False, default=100, comment='健康分数 0-100')
    last_check_time = Column(TIMESTAMP, nullable=True, comment='最后检查时间')
    total_requests = Column(Integer, nullable=False, default=0, comment='总请求次数')
    failed_requests = Column(Integer, nullable=False, default=0, comment='失败请求次数')
    avg_latency_ms = Column(Float, nullable=True, comment='平均延迟(毫秒)')
    extra_metadata = Column(JSONB, nullable=True, comment='额外元数据')
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=True, comment='创建人')

    # 关系
    bindings = relationship("AccountProxyBinding", back_populates="proxy", cascade="all, delete-orphan")
    health_logs = relationship("ProxyHealthLog", back_populates="proxy", cascade="all, delete-orphan")
    usage_stats = relationship("ProxyUsageStats", back_populates="proxy", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ProxyPool(id={self.id}, host={self.host}:{self.port}, status={self.status})>"

    @property
    def proxy_url(self):
        """生成代理URL"""
        if self.username and self.password:
            return f"{self.proxy_type}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.proxy_type}://{self.host}:{self.port}"

    @property
    def success_rate(self):
        """计算成功率"""
        if self.total_requests == 0:
            return 100.0
        return ((self.total_requests - self.failed_requests) / self.total_requests) * 100


class AccountProxyBinding(Base):
    """账户代理绑定表"""
    __tablename__ = "account_proxy_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey('accounts.account_id', ondelete='CASCADE'), nullable=False)
    proxy_id = Column(Integer, ForeignKey('proxy_pool.id', ondelete='CASCADE'), nullable=False)
    platform_id = Column(Integer, nullable=False, comment='平台ID: 1=Binance, 2=Bybit')
    is_active = Column(Boolean, nullable=False, default=True, comment='是否启用')
    priority = Column(Integer, nullable=False, default=0, comment='优先级')
    bind_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    unbind_time = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关系
    proxy = relationship("ProxyPool", back_populates="bindings")

    def __repr__(self):
        return f"<AccountProxyBinding(account_id={self.account_id}, proxy_id={self.proxy_id}, active={self.is_active})>"


class ProxyHealthLog(Base):
    """代理健康检查日志表"""
    __tablename__ = "proxy_health_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    proxy_id = Column(Integer, ForeignKey('proxy_pool.id', ondelete='CASCADE'), nullable=False)
    check_time = Column(TIMESTAMP, nullable=False)
    is_success = Column(Boolean, nullable=False)
    latency_ms = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    check_type = Column(String(50), nullable=False, default='auto')
    target_url = Column(String(255), nullable=True)
    response_code = Column(Integer, nullable=True)

    # 关系
    proxy = relationship("ProxyPool", back_populates="health_logs")

    def __repr__(self):
        return f"<ProxyHealthLog(proxy_id={self.proxy_id}, success={self.is_success}, latency={self.latency_ms}ms)>"


class ProxyUsageStats(Base):
    """代理使用统计表"""
    __tablename__ = "proxy_usage_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    proxy_id = Column(Integer, ForeignKey('proxy_pool.id', ondelete='CASCADE'), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey('accounts.account_id', ondelete='CASCADE'), nullable=False)
    platform_id = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    total_requests = Column(Integer, nullable=False, default=0)
    success_requests = Column(Integer, nullable=False, default=0)
    failed_requests = Column(Integer, nullable=False, default=0)
    avg_latency_ms = Column(Float, nullable=True)
    total_data_mb = Column(Float, nullable=False, default=0)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关系
    proxy = relationship("ProxyPool", back_populates="usage_stats")

    def __repr__(self):
        return f"<ProxyUsageStats(proxy_id={self.proxy_id}, date={self.date}, requests={self.total_requests})>"

    @property
    def success_rate(self):
        """计算成功率"""
        if self.total_requests == 0:
            return 100.0
        return (self.success_requests / self.total_requests) * 100
