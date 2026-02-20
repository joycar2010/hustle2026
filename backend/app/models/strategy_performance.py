import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class StrategyPerformance(Base):
    """Strategy performance model for tracking strategy metrics"""

    __tablename__ = "strategy_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey("strategy_configs.config_id"), nullable=False, index=True)
    date = Column(TIMESTAMP, nullable=False, index=True)
    total_trades = Column(Integer, default=0, nullable=False)
    winning_trades = Column(Integer, default=0, nullable=False)
    losing_trades = Column(Integer, default=0, nullable=False)
    total_profit = Column(Float, default=0.0, nullable=False)
    total_loss = Column(Float, default=0.0, nullable=False)
    win_rate = Column(Float, default=0.0, nullable=False)
    avg_profit = Column(Float, default=0.0, nullable=False)
    max_drawdown = Column(Float, default=0.0, nullable=False)
    sharpe_ratio = Column(Float)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)

    # Relationships
    strategy = relationship("StrategyConfig", backref="performance_records")

    __table_args__ = (
        Index('idx_strategy_performance_date', 'strategy_id', 'date'),
    )

    def __repr__(self):
        return f"<StrategyPerformance(strategy_id={self.strategy_id}, date={self.date}, win_rate={self.win_rate})>"
