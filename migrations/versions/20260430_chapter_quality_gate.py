"""add chapter quality gate fields

Revision ID: 20260430_chapter_quality_gate
Revises: 20260427_job_heartbeat
Create Date: 2026-04-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260430_chapter_quality_gate"
down_revision: Union[str, Sequence[str], None] = "20260427_job_heartbeat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chapters", sa.Column("draft_review_score", sa.Integer(), nullable=True))
    op.add_column("chapters", sa.Column("draft_review_feedback", sa.JSON(), nullable=True))
    op.add_column("chapters", sa.Column("final_review_score", sa.Integer(), nullable=True))
    op.add_column("chapters", sa.Column("final_review_feedback", sa.JSON(), nullable=True))
    op.add_column("chapters", sa.Column("quality_status", sa.Text(), nullable=False, server_default="unchecked"))
    op.add_column("chapters", sa.Column("quality_reasons", sa.JSON(), nullable=True))
    op.add_column("chapters", sa.Column("quality_checked_at", sa.TIMESTAMP(), nullable=True))
    op.add_column("chapters", sa.Column("world_state_ingested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("chapters", "quality_status", server_default=None)
    op.alter_column("chapters", "world_state_ingested", server_default=None)


def downgrade() -> None:
    op.drop_column("chapters", "world_state_ingested")
    op.drop_column("chapters", "quality_checked_at")
    op.drop_column("chapters", "quality_reasons")
    op.drop_column("chapters", "quality_status")
    op.drop_column("chapters", "final_review_feedback")
    op.drop_column("chapters", "final_review_score")
    op.drop_column("chapters", "draft_review_feedback")
    op.drop_column("chapters", "draft_review_score")
