"""add entity vector_embedding

Revision ID: 5496bbb8d0df
Revises: 815fd4566d43
Create Date: 2026-04-18 00:00:09.909752

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import Column
from novel_dev.db.models import VectorCompat


# revision identifiers, used by Alembic.
revision: str = '5496bbb8d0df'
down_revision: Union[str, Sequence[str], None] = '815fd4566d43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('entities', Column('vector_embedding', VectorCompat(1536), nullable=True))


def downgrade() -> None:
    op.drop_column('entities', 'vector_embedding')
