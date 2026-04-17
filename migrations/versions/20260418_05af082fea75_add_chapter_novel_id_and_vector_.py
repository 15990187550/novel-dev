"""add chapter novel_id and vector_embedding

Revision ID: 05af082fea75
Revises: 5496bbb8d0df
Create Date: 2026-04-18 06:14:55.663915

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import Column, Text
from novel_dev.db.models import VectorCompat


# revision identifiers, used by Alembic.
revision: str = '05af082fea75'
down_revision: Union[str, Sequence[str], None] = '5496bbb8d0df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chapters', Column('novel_id', Text, nullable=True))
    op.add_column('chapters', Column('vector_embedding', VectorCompat(1536), nullable=True))


def downgrade() -> None:
    op.drop_column('chapters', 'vector_embedding')
    op.drop_column('chapters', 'novel_id')
