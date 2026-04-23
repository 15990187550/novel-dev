"""add brainstorm suggestion cards

Revision ID: 20260423_bw_suggestion_cards
Revises: 20260422_pe_error_msg
Create Date: 2026-04-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260423_bw_suggestion_cards"
down_revision: Union[str, Sequence[str], None] = "20260422_pe_error_msg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brainstorm_workspaces",
        sa.Column("setting_suggestion_cards", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.alter_column("brainstorm_workspaces", "setting_suggestion_cards", server_default=None)


def downgrade() -> None:
    op.drop_column("brainstorm_workspaces", "setting_suggestion_cards")
