"""add outline workbench sessions

Revision ID: 20260421_add_outline_workbench_sessions
Revises: 20260421_add_entity_classification_and_search_fields
Create Date: 2026-04-21 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260421_add_outline_workbench_sessions"
down_revision: Union[str, Sequence[str], None] = "20260421_add_entity_classification_and_search_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outline_sessions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("outline_type", sa.Text(), nullable=False),
        sa.Column("outline_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("conversation_summary", sa.Text(), nullable=True),
        sa.Column("last_result_snapshot", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id", "outline_type", "outline_ref", name="uix_outline_session_scope"),
    )

    op.create_table(
        "outline_messages",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("message_type", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["outline_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outline_messages_session_id", "outline_messages", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_outline_messages_session_id", table_name="outline_messages")
    op.drop_table("outline_messages")
    op.drop_table("outline_sessions")
