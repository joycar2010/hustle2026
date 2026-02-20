import uuid
from datetime import datetime
from sqlalchemy import Column, Float, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class AccountSnapshot(Base):
    """Account snapshot model for tracking account balance history"""

    __tablename__ = "account_snapshots"

    snapshot_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.account_id"), nullable=False, index=True)
    total_balance = Column(Float, nullable=False)
    available_balance = Column(Float, nullable=False)
    margin_used = Column(Float, default=0.0, nullable=False)
    unrealized_pnl = Column(Float, default=0.0, nullable=False)
    timestamp = Column(TIMESTAMP, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    account = relationship("Account", backref="snapshots")

    __table_args__ = (
        Index('idx_account_snapshots_time', 'account_id', 'timestamp'),
    )

    def __repr__(self):
        return f"<AccountSnapshot(account_id={self.account_id}, balance={self.total_balance}, time={self.timestamp})>"
