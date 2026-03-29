"""
创建套利机会表模型
Arbitrage Opportunities Table - 存储可套利的点差数据点
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, TIMESTAMP, Index
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class ArbitrageOpportunity(Base):
    """套利机会记录表 - 存储满足套利条件的点差数据"""

    __tablename__ = "arbitrage_opportunities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False, index=True)

    # 价格数据
    binance_bid = Column(Float, nullable=False)
    binance_ask = Column(Float, nullable=False)
    bybit_bid = Column(Float, nullable=False)
    bybit_ask = Column(Float, nullable=False)

    # 点差数据
    forward_spread = Column(Float, nullable=False)
    reverse_spread = Column(Float, nullable=False)

    # 套利类型标记
    opportunity_type = Column(String(50), nullable=False, index=True)
    # 可能的值: 'forward_open', 'forward_close', 'reverse_open', 'reverse_close'

    # 目标点差（策略配置的阈值）
    target_spread = Column(Float, nullable=False)

    # 时间戳
    timestamp = Column(TIMESTAMP, nullable=False, index=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_arb_opp_symbol_time', 'symbol', 'timestamp'),
        Index('idx_arb_opp_type_time', 'opportunity_type', 'timestamp'),
    )

    def __repr__(self):
        return f"<ArbitrageOpportunity(symbol={self.symbol}, type={self.opportunity_type}, spread={self.forward_spread}/{self.reverse_spread})>"
