"""add chapter_quality_metrics table

Revision ID: 20260613_quality_metrics
Revises: 20260515_genre_templates
Create Date: 2026-06-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


revision: str = "20260613_quality_metrics"
down_revision: Union[str, Sequence[str], None] = "20260515_genre_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chapter_quality_metrics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("novel_id", sa.Text, nullable=False, index=True),
        sa.Column("chapter_id", sa.Text, sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("attempt_index", sa.Integer, server_default="0"),
        sa.Column("overall_score", sa.Integer, nullable=True),
        sa.Column("dimension_scores", JSON, nullable=True),
        sa.Column("dimension_feedback", JSON, nullable=True),
        sa.Column("gate_status", sa.String(32), nullable=False),
        sa.Column("blocking_items", JSON, nullable=True),
        sa.Column("warning_items", JSON, nullable=True),
        sa.Column("issue_codes", JSON, nullable=True),
        sa.Column("repairable", sa.Boolean, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("token_usage", JSON, nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_chapter_quality_metrics_novel_chapter_phase",
        "chapter_quality_metrics",
        ["novel_id", "chapter_id", "phase", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chapter_quality_metrics_novel_chapter_phase", "chapter_quality_metrics")
    op.drop_table("chapter_quality_metrics")