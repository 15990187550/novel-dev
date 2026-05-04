"""add setting generation sessions

Revision ID: 20260504_setting_sessions
Revises: 20260430_chapter_quality_gate
Create Date: 2026-05-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260504_setting_sessions"
down_revision: Union[str, Sequence[str], None] = "20260430_chapter_quality_gate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "setting_generation_sessions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("target_categories", sa.JSON(), nullable=False),
        sa.Column("clarification_round", sa.Integer(), nullable=False),
        sa.Column("conversation_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_setting_generation_sessions_novel_updated",
        "setting_generation_sessions",
        ["novel_id", "updated_at"],
    )
    op.create_table(
        "setting_generation_messages",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["setting_generation_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_setting_generation_messages_session_created",
        "setting_generation_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_setting_generation_messages_session_created", table_name="setting_generation_messages")
    op.drop_table("setting_generation_messages")
    op.drop_index("ix_setting_generation_sessions_novel_updated", table_name="setting_generation_sessions")
    op.drop_table("setting_generation_sessions")
