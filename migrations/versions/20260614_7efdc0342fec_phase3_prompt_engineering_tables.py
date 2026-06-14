"""phase3 prompt engineering tables

Revision ID: 7efdc0342fec
Revises: 20260613_quality_metrics
Create Date: 2026-06-14 21:58:06.568045

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7efdc0342fec'
down_revision: Union[str, Sequence[str], None] = '20260613_quality_metrics'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_name", sa.String(64), nullable=False, index=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("false"), index=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_by", sa.String(32), nullable=False, server_default="user"),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("parent_version", sa.String(32), nullable=True),
        sa.Column("ab_test_id", sa.String(36), nullable=True, index=True),
        sa.UniqueConstraint("agent_name", "version", name="uq_prompt_versions_agent_version"),
    )

    op.create_table(
        "quality_root_cause",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chapter_id", sa.String(64), nullable=False, index=True),
        sa.Column("analyzer_version", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("suggested_actions", sa.JSON, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("input_snapshot", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), index=True),
    )
    op.create_index("ix_quality_root_cause_chapter_created", "quality_root_cause", ["chapter_id", "created_at"])

    op.create_table(
        "ab_tests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_name", sa.String(64), nullable=False, index=True),
        sa.Column("baseline_version", sa.String(32), nullable=False),
        sa.Column("challenger_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running", index=True),
        sa.Column("winner", sa.String(16), nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ended_at", sa.DateTime, nullable=True),
        sa.Column("config", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ab_tests")
    op.drop_index("ix_quality_root_cause_chapter_created", table_name="quality_root_cause")
    op.drop_table("quality_root_cause")
    op.drop_table("prompt_versions")
