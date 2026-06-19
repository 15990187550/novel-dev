"""add chapter attempt index

Revision ID: 7c9b4f2d1a6e
Revises: e686cd654d1e
Create Date: 2026-06-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c9b4f2d1a6e"
down_revision: Union[str, Sequence[str], None] = "e686cd654d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chapters",
        sa.Column("attempt_index", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("chapters", "attempt_index")
