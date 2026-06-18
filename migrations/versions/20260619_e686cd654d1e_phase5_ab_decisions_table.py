"""phase5 ab_decisions table

Revision ID: e686cd654d1e
Revises: e5b2bfeacd39
Create Date: 2026-06-19 07:33:32.120649

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e686cd654d1e'
down_revision: Union[str, Sequence[str], None] = 'e5b2bfeacd39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ab_decisions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('experiment_id', sa.String(length=36), nullable=False),
    sa.Column('prompt_version_id', sa.String(length=36), nullable=True),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('decision_at', sa.DateTime(), nullable=False),
    sa.Column('p_value', sa.Float(), nullable=True),
    sa.Column('scores', sa.JSON(), nullable=False),
    sa.Column('effect_size', sa.Float(), nullable=True),
    sa.Column('meta', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ab_decisions_action', 'ab_decisions', ['action'], unique=False)
    op.create_index('ix_ab_decisions_decision_at', 'ab_decisions', ['decision_at'], unique=False)
    op.create_index('ix_ab_decisions_experiment', 'ab_decisions', ['experiment_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ab_decisions_experiment', table_name='ab_decisions')
    op.drop_index('ix_ab_decisions_decision_at', table_name='ab_decisions')
    op.drop_index('ix_ab_decisions_action', table_name='ab_decisions')
    op.drop_table('ab_decisions')
