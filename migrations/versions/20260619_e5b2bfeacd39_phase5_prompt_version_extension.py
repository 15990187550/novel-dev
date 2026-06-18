"""phase5 prompt_version extension

Revision ID: e5b2bfeacd39
Revises: 3d94ada996f0
Create Date: 2026-06-19 07:23:59.624194

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5b2bfeacd39'
down_revision: Union[str, Sequence[str], None] = '3d94ada996f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('prompt_versions', sa.Column('experiment_state', sa.String(length=32), nullable=False))
    op.add_column('prompt_versions', sa.Column('last_decision_at', sa.DateTime(), nullable=True))
    op.add_column('prompt_versions', sa.Column('last_score', sa.Float(), nullable=True))
    op.add_column('prompt_versions', sa.Column('experiment_history', sa.JSON(), nullable=False))
    op.create_index(op.f('ix_prompt_versions_experiment_state'), 'prompt_versions', ['experiment_state'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_prompt_versions_experiment_state'), table_name='prompt_versions')
    op.drop_column('prompt_versions', 'experiment_history')
    op.drop_column('prompt_versions', 'last_score')
    op.drop_column('prompt_versions', 'last_decision_at')
    op.drop_column('prompt_versions', 'experiment_state')
