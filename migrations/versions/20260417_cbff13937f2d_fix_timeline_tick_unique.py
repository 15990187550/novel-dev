"""fix timeline tick unique to novel-scoped composite

Revision ID: cbff13937f2d
Revises: a198e260c3bf
Create Date: 2026-04-17 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cbff13937f2d'
down_revision: Union[str, Sequence[str], None] = 'a198e260c3bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop the old unique constraint on tick
    op.drop_constraint('timeline_tick_key', 'timeline', type_='unique')
    # Add composite unique constraint on (novel_id, tick)
    op.create_unique_constraint('uix_timeline_novel_tick', 'timeline', ['novel_id', 'tick'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uix_timeline_novel_tick', 'timeline', type_='unique')
    op.create_unique_constraint('timeline_tick_key', 'timeline', ['tick'])
