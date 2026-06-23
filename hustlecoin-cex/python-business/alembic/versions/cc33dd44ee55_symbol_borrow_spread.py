"""symbol_rules + account_symbol_rules 加 borrow_spread(挂单点差,可负=提前借)

单一规则按币/按账户覆盖挂单点差;null=跟随全局。允许负值(如 -1 = 任何点差都先借)。
幂等 ADD COLUMN IF NOT EXISTS,非锁表。

Revision ID: cc33dd44ee55
Revises: bb22cc33dd44
Create Date: 2026-06-17
"""
from alembic import op

revision = "cc33dd44ee55"
down_revision = "bb22cc33dd44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE symbol_rules ADD COLUMN IF NOT EXISTS borrow_spread NUMERIC(10,4)")
    op.execute("ALTER TABLE account_symbol_rules ADD COLUMN IF NOT EXISTS borrow_spread NUMERIC(10,4)")


def downgrade() -> None:
    op.execute("ALTER TABLE account_symbol_rules DROP COLUMN IF EXISTS borrow_spread")
    op.execute("ALTER TABLE symbol_rules DROP COLUMN IF EXISTS borrow_spread")
