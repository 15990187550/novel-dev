"""add novel genre templates

Revision ID: 20260515_genre_templates
Revises: 20260510_world_reviews
Create Date: 2026-05-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260515_genre_templates"
down_revision: Union[str, Sequence[str], None] = "20260510_world_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "novel_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("parent_slug", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uix_novel_categories_slug"),
    )
    op.create_index("ix_novel_categories_parent_slug", "novel_categories", ["parent_slug"])

    op.create_table(
        "novel_genre_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("category_slug", sa.Text(), nullable=True),
        sa.Column("parent_slug", sa.Text(), nullable=True),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("task_name", sa.Text(), nullable=False),
        sa.Column("prompt_blocks", sa.JSON(), nullable=False),
        sa.Column("quality_config", sa.JSON(), nullable=False),
        sa.Column("merge_policy", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_novel_genre_templates_scope_category_agent_task",
        "novel_genre_templates",
        ["scope", "category_slug", "agent_name", "task_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_novel_genre_templates_scope_category_agent_task", table_name="novel_genre_templates")
    op.drop_table("novel_genre_templates")
    op.drop_index("ix_novel_categories_parent_slug", table_name="novel_categories")
    op.drop_table("novel_categories")
