"""enable pgvector

Revision ID: 815fd4566d43
Revises: a198e260c3bf
Create Date: 2026-04-17 23:39:35.256397

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '815fd4566d43'
down_revision: Union[str, Sequence[str], None] = 'a198e260c3bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable pgvector extension."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Disable pgvector extension."""
    op.execute("DROP EXTENSION IF EXISTS vector")
