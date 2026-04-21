"""add source_filename to pending extractions

Revision ID: 20260421_add_source_filename_to_pending_extractions
Revises: 20260420_add_pending_extraction_resolution_result
Create Date: 2026-04-21 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260421_add_source_filename_to_pending_extractions"
down_revision: Union[str, Sequence[str], None] = "20260420_add_pending_extraction_resolution_result"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pending_extractions", sa.Column("source_filename", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pending_extractions", "source_filename")
