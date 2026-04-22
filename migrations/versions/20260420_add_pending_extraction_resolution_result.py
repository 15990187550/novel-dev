"""add resolution_result to pending extractions

Revision ID: 20260420_pe_resolution_result
Revises: 20260420_pe_diff_result
Create Date: 2026-04-20 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260420_pe_resolution_result'
down_revision: Union[str, Sequence[str], None] = '20260420_pe_diff_result'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pending_extractions', sa.Column('resolution_result', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('pending_extractions', 'resolution_result')
