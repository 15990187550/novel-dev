"""add pending extraction error message

Revision ID: 20260422_pe_error_msg
Revises: 20260422_bw_workspace
Create Date: 2026-04-22 20:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260422_pe_error_msg"
down_revision: Union[str, Sequence[str], None] = "20260422_bw_workspace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pending_extractions", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pending_extractions", "error_message")
