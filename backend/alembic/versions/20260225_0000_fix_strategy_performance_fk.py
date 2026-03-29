"""Fix strategy_performance foreign key to reference strategies.id

Revision ID: 20260225_0000
Revises: 20260223_0000
Create Date: 2026-02-25 00:00:00.000000

This migration documents the fix for strategy_performance.strategy_id
to correctly reference strategies.id (INTEGER) instead of
strategy_configs.config_id (UUID).

Note: The database schema was already correct. This migration only
updates the SQLAlchemy model definition to match the database.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260225_0000'
down_revision = '20260223_0000'
branch_labels = None
depends_on = None


def upgrade():
    """
    This migration is a no-op for the database since the schema
    was already correct. It only documents the model fix.

    If you need to actually fix the database schema, uncomment
    the following code:
    """
    # Drop existing foreign key constraint
    # op.drop_constraint('strategy_performance_strategy_id_fkey',
    #                    'strategy_performance', type_='foreignkey')

    # Alter column type from UUID to INTEGER
    # op.alter_column('strategy_performance', 'strategy_id',
    #                existing_type=postgresql.UUID(),
    #                type_=sa.Integer(),
    #                existing_nullable=False)

    # Add new foreign key constraint
    # op.create_foreign_key('strategy_performance_strategy_id_fkey',
    #                      'strategy_performance', 'strategies',
    #                      ['strategy_id'], ['id'],
    #                      ondelete='CASCADE')
    pass


def downgrade():
    """
    Revert to the incorrect model definition (not recommended)
    """
    # op.drop_constraint('strategy_performance_strategy_id_fkey',
    #                    'strategy_performance', type_='foreignkey')

    # op.alter_column('strategy_performance', 'strategy_id',
    #                existing_type=sa.Integer(),
    #                type_=postgresql.UUID(),
    #                existing_nullable=False)

    # op.create_foreign_key('strategy_performance_strategy_id_fkey',
    #                      'strategy_performance', 'strategy_configs',
    #                      ['strategy_id'], ['config_id'])
    pass
