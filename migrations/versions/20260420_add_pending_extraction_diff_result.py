"""add diff_result to pending extractions

Revision ID: 20260420_pe_diff_result
Revises: 097b728b9fa0
Create Date: 2026-04-20 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260420_pe_diff_result'
down_revision: Union[str, Sequence[str], None] = '097b728b9fa0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pending_extractions', sa.Column('diff_result', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('pending_extractions', 'diff_result')
