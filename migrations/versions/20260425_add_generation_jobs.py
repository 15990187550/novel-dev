"""add generation jobs

Revision ID: 20260425_generation_jobs
Revises: eaf5a79edc90, 20260423_bw_suggestion_cards
Create Date: 2026-04-25 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260425_generation_jobs"
down_revision: Union[str, Sequence[str], None] = ("eaf5a79edc90", "20260423_bw_suggestion_cards")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_generation_jobs_novel_type_status",
        "generation_jobs",
        ["novel_id", "job_type", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_generation_jobs_novel_type_status", table_name="generation_jobs")
    op.drop_table("generation_jobs")
