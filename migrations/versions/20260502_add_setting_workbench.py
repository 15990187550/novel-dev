"""add setting workbench persistence

Revision ID: 20260502_setting_workbench
Revises: 20260430_chapter_quality_gate
Create Date: 2026-05-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260502_setting_workbench"
down_revision: Union[str, Sequence[str], None] = "20260430_chapter_quality_gate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "setting_generation_sessions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="clarifying"),
        sa.Column("target_categories", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("clarification_round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversation_summary", sa.Text(), nullable=True),
        sa.Column("focused_target", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_setting_generation_sessions_novel_status",
        "setting_generation_sessions",
        ["novel_id", "status"],
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
        "ix_setting_generation_messages_session",
        "setting_generation_messages",
        ["session_id", "created_at"],
    )

    op.create_table(
        "setting_review_batches",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("source_session_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(["source_session_id"], ["setting_generation_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_setting_review_batches_novel_status",
        "setting_review_batches",
        ["novel_id", "status"],
    )
    op.create_index(
        "ix_setting_review_batches_session",
        "setting_review_batches",
        ["source_session_id"],
    )

    op.create_table(
        "setting_review_changes",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("before_snapshot", sa.JSON(), nullable=True),
        sa.Column("after_snapshot", sa.JSON(), nullable=True),
        sa.Column("conflict_hints", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_session_id", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["setting_review_batches.id"]),
        sa.ForeignKeyConstraint(["source_session_id"], ["setting_generation_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_setting_review_changes_batch_status",
        "setting_review_changes",
        ["batch_id", "status"],
    )

    for table_name in ("novel_documents", "entities", "entity_relationships"):
        op.add_column(table_name, sa.Column("source_type", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("source_session_id", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("source_review_batch_id", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("source_review_change_id", sa.Text(), nullable=True))


def downgrade() -> None:
    for table_name in ("entity_relationships", "entities", "novel_documents"):
        op.drop_column(table_name, "source_review_change_id")
        op.drop_column(table_name, "source_review_batch_id")
        op.drop_column(table_name, "source_session_id")
        op.drop_column(table_name, "source_type")

    op.drop_index("ix_setting_review_changes_batch_status", table_name="setting_review_changes")
    op.drop_table("setting_review_changes")

    op.drop_index("ix_setting_review_batches_session", table_name="setting_review_batches")
    op.drop_index("ix_setting_review_batches_novel_status", table_name="setting_review_batches")
    op.drop_table("setting_review_batches")

    op.drop_index("ix_setting_generation_messages_session", table_name="setting_generation_messages")
    op.drop_table("setting_generation_messages")

    op.drop_index("ix_setting_generation_sessions_novel_status", table_name="setting_generation_sessions")
    op.drop_table("setting_generation_sessions")
