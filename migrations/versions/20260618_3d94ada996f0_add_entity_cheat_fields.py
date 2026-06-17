"""add entity cheat fields

Revision ID: 3d94ada996f0
Revises: 4a1c635516ef
Create Date: 2026-06-18 01:06:07.665950

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3d94ada996f0'
down_revision: Union[str, Sequence[str], None] = '4a1c635516ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cheat_ability / cheat_activation_rules / cheat_first_activation_chapter
    to the entities table. JSON is used for cheat_activation_rules so the
    structure round-trips identically on both PostgreSQL and SQLite."""
    op.add_column(
        'entities',
        sa.Column('cheat_ability', sa.Text(), server_default='', nullable=False),
    )
    op.add_column(
        'entities',
        sa.Column(
            'cheat_activation_rules',
            postgresql.JSON(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
    )
    op.add_column(
        'entities',
        sa.Column('cheat_first_activation_chapter', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('entities', 'cheat_first_activation_chapter')
    op.drop_column('entities', 'cheat_activation_rules')
    op.drop_column('entities', 'cheat_ability')
