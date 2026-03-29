"""
MT5实例数据模型 - 管理Windows服务器上的MT5微服务实例
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class MT5Instance(Base):
    """MT5实例表 - 管理Windows服务器上的MT5微服务部署"""
    __tablename__ = "mt5_instances"

    instance_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_name = Column(String(100), nullable=False, unique=True, comment='实例名称')

    # 关联 MT5 客户端（新增）
    client_id = Column(Integer, ForeignKey('mt5_clients.client_id', ondelete='CASCADE'), nullable=True, comment='关联的MT5客户端')
    instance_type = Column(String(20), nullable=False, default='primary', comment='实例类型: primary/backup')

    # 服务器信息
    server_ip = Column(String(50), nullable=False, comment='Windows服务器IP')
    service_port = Column(Integer, nullable=False, unique=True, comment='服务端口')

    # MT5客户端配置
    mt5_path = Column(String(500), nullable=False, comment='MT5可执行文件路径')
    mt5_data_path = Column(String(500), nullable=True, comment='MT5数据目录')
    is_portable = Column(Boolean, default=False, comment='是否为便携版')

    # 部署配置
    deploy_path = Column(String(500), nullable=False, comment='服务部署路径')
    auto_start = Column(Boolean, default=True, comment='开机自启')

    # 状态信息
    status = Column(String(20), default='stopped', comment='运行状态')
    is_active = Column(Boolean, default=False, comment='是否启用（同一客户端只能有一个启用）')

    # 元数据
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(UUID(as_uuid=True), nullable=True, comment='创建人')

    # 关系
    client = relationship("MT5Client", backref="instances")

    def __repr__(self):
        return f"<MT5Instance(name={self.instance_name}, port={self.service_port}, type={self.instance_type}, status={self.status})>"
