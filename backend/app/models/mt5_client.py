"""
MT5客户端数据模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Float, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class MT5Client(Base):
    """MT5客户端表 - 支持一个MT5账户多个客户端连接"""
    __tablename__ = "mt5_clients"

    client_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey('accounts.account_id', ondelete='CASCADE'), nullable=False, comment='关联的MT5账户')
    client_name = Column(String(100), nullable=False, comment='客户端名称')

    # 登录凭证
    mt5_login = Column(String(100), nullable=False, comment='MT5账号')
    mt5_password = Column(String(256), nullable=False, comment='MT5密码（加密）')
    mt5_server = Column(String(100), nullable=False, comment='MT5服务器地址')
    password_type = Column(String(20), nullable=False, default='primary', comment='密码类型: primary/readonly')

    # Windows Agent配置
    agent_instance_name = Column(String(100), nullable=True, comment='Windows Agent实例名称')

    # 代理配置
    proxy_id = Column(Integer, ForeignKey('proxy_pool.id', ondelete='SET NULL'), nullable=True, comment='绑定的代理')

    # 连接状态
    connection_status = Column(String(20), nullable=False, default='disconnected', comment='连接状态')
    is_active = Column(Boolean, nullable=False, default=True, comment='是否启用')
    is_system_service = Column(Boolean, nullable=False, default=False, comment='是否为系统服务账户')
    priority = Column(Integer, nullable=False, default=0, comment='优先级')

    # 连接统计
    last_connected_at = Column(TIMESTAMP, nullable=True, comment='最后连接时间')
    last_disconnected_at = Column(TIMESTAMP, nullable=True, comment='最后断开时间')
    total_connections = Column(Integer, nullable=False, default=0, comment='总连接次数')
    failed_connections = Column(Integer, nullable=False, default=0, comment='失败连接次数')
    avg_latency_ms = Column(Float, nullable=True, comment='平均延迟（毫秒）')

    # 元数据
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=True, comment='创建人')

    # 关系
    account = relationship("Account", backref="mt5_clients")
    proxy = relationship("ProxyPool", backref="mt5_clients")

    def __repr__(self):
        return f"<MT5Client(client_id={self.client_id}, name={self.client_name}, status={self.connection_status})>"

    @property
    def is_connected(self):
        """是否已连接"""
        return self.connection_status == 'connected'

    @property
    def success_rate(self):
        """连接成功率"""
        if self.total_connections == 0:
            return 100.0
        return ((self.total_connections - self.failed_connections) / self.total_connections) * 100
