"""phase4_quality_architectural_tables

Revision ID: 4a1c635516ef
Revises: 7efdc0342fec
Create Date: 2026-06-17 23:26:52.377395

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a1c635516ef'
down_revision: Union[str, Sequence[str], None] = '7efdc0342fec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chapter_synopsis',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('novel_id', sa.String(length=64), nullable=False),
        sa.Column('chapter_range_start', sa.Integer(), nullable=False),
        sa.Column('chapter_range_end', sa.Integer(), nullable=False),
        sa.Column('narrative_prose', sa.Text(), nullable=False),
        sa.Column('structured_json', sa.JSON(), nullable=False),
        sa.Column('trigger_event', sa.JSON(), nullable=False),
        sa.Column('prev_synopsis_id', sa.String(length=36), nullable=True),
        sa.Column('analyzer_version', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chapter_synopsis_novel_id'), 'chapter_synopsis', ['novel_id'], unique=False)

    op.create_table(
        'thrill_points',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('novel_id', sa.String(length=64), nullable=False),
        sa.Column('chapter_id', sa.String(length=64), nullable=False),
        sa.Column('beat_idx', sa.Integer(), nullable=True),
        sa.Column('thrill_type', sa.String(length=32), nullable=False),
        sa.Column('intensity', sa.String(length=16), nullable=False),
        sa.Column('evidence_quote', sa.Text(), nullable=True),
        sa.Column('planner_predicted', sa.Boolean(), nullable=False),
        sa.Column('fast_review_verified', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_thrill_points_chapter', 'thrill_points', ['chapter_id'], unique=False)
    op.create_index(op.f('ix_thrill_points_novel_id'), 'thrill_points', ['novel_id'], unique=False)

    op.create_table(
        'imagery_inventory',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('novel_id', sa.String(length=64), nullable=False),
        sa.Column('chapter_id', sa.String(length=64), nullable=False),
        sa.Column('item', sa.String(length=255), nullable=False),
        sa.Column('item_type', sa.String(length=32), nullable=False),
        sa.Column('frequency_in_chapter', sa.Integer(), nullable=False),
        sa.Column('extracted_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_imagery_inventory_novel_chapter', 'imagery_inventory', ['novel_id', 'chapter_id'], unique=False)
    op.create_index(op.f('ix_imagery_inventory_novel_id'), 'imagery_inventory', ['novel_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_imagery_inventory_novel_id'), table_name='imagery_inventory')
    op.drop_index('ix_imagery_inventory_novel_chapter', table_name='imagery_inventory')
    op.drop_table('imagery_inventory')
    op.drop_index(op.f('ix_thrill_points_novel_id'), table_name='thrill_points')
    op.drop_index('ix_thrill_points_chapter', table_name='thrill_points')
    op.drop_table('thrill_points')
    op.drop_index(op.f('ix_chapter_synopsis_novel_id'), table_name='chapter_synopsis')
    op.drop_table('chapter_synopsis')
