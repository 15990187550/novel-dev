"""merge branches

Revision ID: a073a208ff9b
Revises: f2a3b4c5d6e7, 8a7c3e5f1d2a, cbff13937f2d
Create Date: 2026-04-18 07:08:38.603872

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a073a208ff9b'
down_revision: Union[str, Sequence[str], None] = ('f2a3b4c5d6e7', '8a7c3e5f1d2a', 'cbff13937f2d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
