"""add brainstorm workspace

Revision ID: 20260422_add_brainstorm_workspace
Revises: 20260421_outline_workbench
Create Date: 2026-04-22 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260422_add_brainstorm_workspace"
down_revision: Union[str, Sequence[str], None] = "20260421_outline_workbench"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brainstorm_workspaces",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("workspace_summary", sa.Text(), nullable=True),
        sa.Column("outline_drafts", sa.JSON(), nullable=False),
        sa.Column("setting_docs_draft", sa.JSON(), nullable=False),
        sa.Column("last_saved_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("submitted_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id", "status", name="uix_brainstorm_workspace_novel_status"),
    )
    op.create_index(
        "ix_brainstorm_workspaces_novel_status",
        "brainstorm_workspaces",
        ["novel_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_brainstorm_workspaces_novel_status", table_name="brainstorm_workspaces")
    op.drop_table("brainstorm_workspaces")
