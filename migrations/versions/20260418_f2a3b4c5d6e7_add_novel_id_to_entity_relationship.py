"""add novel_id to entity_relationships

Revision ID: f2a3b4c5d6e7
Revises: 05af082fea75
Create Date: 2026-04-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = '05af082fea75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('entity_relationships', sa.Column('novel_id', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('entity_relationships', 'novel_id')
