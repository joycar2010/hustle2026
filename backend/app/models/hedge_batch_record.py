import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class HedgeBatchRecord(Base):
    __tablename__ = 'hedge_batch_records'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id'), nullable=False, index=True)
    pair_code = Column(String(30), nullable=False, index=True)
    strategy_type = Column(String(20), nullable=False)  # 'forward' / 'reverse'
    batch_no = Column(Integer, nullable=False)
    order_time = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    hedge_price = Column(Float, nullable=False)
    hedge_qty = Column(Float, nullable=False)  # lots / quantity
    direction = Column(String(10), nullable=False)  # 'buy' / 'sell'
    status = Column(String(10), nullable=False, default='open')  # 'open' / 'closed'
    closed_at = Column(TIMESTAMP, nullable=True)
    create_time = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
