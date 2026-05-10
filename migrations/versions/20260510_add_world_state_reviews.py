"""add world state reviews

Revision ID: 20260510_world_reviews
Revises: 20260504_setting_consolidation
Create Date: 2026-05-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260510_world_reviews"
down_revision: Union[str, Sequence[str], None] = "20260504_setting_consolidation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "world_state_reviews",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("chapter_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("extraction_payload", sa.JSON(), nullable=False),
        sa.Column("diff_result", sa.JSON(), nullable=False),
        sa.Column("decision", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_world_state_reviews_novel_status", "world_state_reviews", ["novel_id", "status"])
    op.create_index("ix_world_state_reviews_chapter", "world_state_reviews", ["chapter_id"])


def downgrade() -> None:
    op.drop_index("ix_world_state_reviews_chapter", table_name="world_state_reviews")
    op.drop_index("ix_world_state_reviews_novel_status", table_name="world_state_reviews")
    op.drop_table("world_state_reviews")
