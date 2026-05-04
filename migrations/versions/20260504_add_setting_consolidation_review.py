"""add setting consolidation review

Revision ID: 20260504_setting_consolidation
Revises: 20260504_setting_sessions
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260504_setting_consolidation"
down_revision: Union[str, Sequence[str], None] = "20260504_setting_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def source_archive_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("source_session_id", sa.Text(), nullable=True),
        sa.Column("source_review_batch_id", sa.Text(), nullable=True),
        sa.Column("source_review_change_id", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("archive_reason", sa.Text(), nullable=True),
        sa.Column("archived_by_consolidation_batch_id", sa.Text(), nullable=True),
        sa.Column("archived_by_consolidation_change_id", sa.Text(), nullable=True),
    )


def upgrade() -> None:
    op.create_table(
        "setting_review_batches",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("source_session_id", sa.Text(), sa.ForeignKey("setting_generation_sessions.id"), nullable=True),
        sa.Column("job_id", sa.Text(), sa.ForeignKey("generation_jobs.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False),
    )
    op.create_index("ix_setting_review_batches_novel_status", "setting_review_batches", ["novel_id", "status"])
    op.create_index("ix_setting_review_batches_source_session", "setting_review_batches", ["source_session_id"])
    op.create_index("ix_setting_review_batches_job", "setting_review_batches", ["job_id"])
    op.create_table(
        "setting_review_changes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("batch_id", sa.Text(), sa.ForeignKey("setting_review_batches.id"), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("before_snapshot", sa.JSON(), nullable=True),
        sa.Column("after_snapshot", sa.JSON(), nullable=True),
        sa.Column("conflict_hints", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_session_id", sa.Text(), sa.ForeignKey("setting_generation_sessions.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False),
    )
    op.create_index("ix_setting_review_changes_batch_status", "setting_review_changes", ["batch_id", "status"])
    for table_name in ("novel_documents", "entities", "entity_relationships"):
        for column in source_archive_columns():
            op.add_column(table_name, column)


def downgrade() -> None:
    for table_name in ("entity_relationships", "entities", "novel_documents"):
        for column_name in (
            "archived_by_consolidation_change_id",
            "archived_by_consolidation_batch_id",
            "archive_reason",
            "archived_at",
            "source_review_change_id",
            "source_review_batch_id",
            "source_session_id",
            "source_type",
        ):
            op.drop_column(table_name, column_name)
    op.drop_index("ix_setting_review_changes_batch_status", table_name="setting_review_changes")
    op.drop_table("setting_review_changes")
    op.drop_index("ix_setting_review_batches_job", table_name="setting_review_batches")
    op.drop_index("ix_setting_review_batches_source_session", table_name="setting_review_batches")
    op.drop_index("ix_setting_review_batches_novel_status", table_name="setting_review_batches")
    op.drop_table("setting_review_batches")
