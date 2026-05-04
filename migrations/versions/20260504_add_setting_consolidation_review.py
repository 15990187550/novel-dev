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
        sa.Column("archived_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("archive_reason", sa.Text(), nullable=True),
        sa.Column("archived_by_consolidation_batch_id", sa.Text(), nullable=True),
        sa.Column("archived_by_consolidation_change_id", sa.Text(), nullable=True),
    )


def upgrade() -> None:
    op.add_column("setting_review_batches", sa.Column("job_id", sa.Text(), nullable=True))
    op.add_column("setting_review_batches", sa.Column("input_snapshot", sa.JSON(), nullable=False, server_default="{}"))
    op.create_index("ix_setting_review_batches_job", "setting_review_batches", ["job_id"])
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
        ):
            op.drop_column(table_name, column_name)
    op.drop_index("ix_setting_review_batches_job", table_name="setting_review_batches")
    op.drop_column("setting_review_batches", "input_snapshot")
    op.drop_column("setting_review_batches", "job_id")
