"""balance_snapshot 表 + 历史查询索引(资金曲线/对账 + 跨用户历史加速)

新增 balance_snapshot(资金净值时间序列)+ 补 positions(user_id,closed_at)、trade_logs(created_at)
复合/单列索引,加速 admin 跨用户历史分页与资金曲线查询。全部 IF NOT EXISTS,幂等安全、非锁表。

Revision ID: aa11bb22cc33
Revises: d4e5f6a7b8c9
Create Date: 2026-06-16
"""
from alembic import op

revision = "aa11bb22cc33"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS balance_snapshot (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            ts TIMESTAMPTZ DEFAULT now(),
            equity NUMERIC(18, 4),
            available NUMERIC(18, 4),
            borrowed NUMERIC(18, 4),
            unrealized_pnl NUMERIC(18, 4),
            margin_level_min NUMERIC(12, 4),
            bnb NUMERIC(18, 8),
            account_count INTEGER
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_balance_snapshot_user_ts ON balance_snapshot (user_id, ts)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_positions_user_closed ON positions (user_id, closed_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_trade_logs_created ON trade_logs (created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_trade_logs_created")
    op.execute("DROP INDEX IF EXISTS ix_positions_user_closed")
    op.execute("DROP INDEX IF EXISTS ix_balance_snapshot_user_ts")
    op.execute("DROP TABLE IF EXISTS balance_snapshot")
