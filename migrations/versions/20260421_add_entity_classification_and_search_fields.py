"""add entity classification and search fields

Revision ID: 20260421_entity_classification
Revises: 20260421_pe_source_filename
Create Date: 2026-04-21 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import TypeDecorator

try:
    from pgvector.sqlalchemy import Vector as PgVector
except ImportError:  # pragma: no cover - optional dependency in SQLite-only test runs
    PgVector = None


class _VectorCompat(TypeDecorator):
    impl = sa.JSON
    cache_ok = True

    def __init__(self, dimensions: int = 1024):
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if PgVector is not None and dialect.name == "postgresql":
            return dialect.type_descriptor(PgVector(self.dimensions))
        return dialect.type_descriptor(sa.JSON)


# revision identifiers, used by Alembic.
revision: str = "20260421_entity_classification"
down_revision: Union[str, Sequence[str], None] = "20260421_pe_source_filename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_groups",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("group_name", sa.Text(), nullable=False),
        sa.Column("group_slug", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id", "category", "group_slug", name="uix_entity_group_scope"),
    )
    with op.batch_alter_table("entities") as batch_op:
        batch_op.add_column(sa.Column("system_category", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("system_group_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("manual_category", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("manual_group_id", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_entities_system_group_id_entity_groups",
            "entity_groups",
            ["system_group_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_entities_manual_group_id_entity_groups",
            "entity_groups",
            ["manual_group_id"],
            ["id"],
        )
        batch_op.add_column(sa.Column("classification_reason", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("classification_confidence", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("system_needs_review", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("search_document", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("search_vector_embedding", _VectorCompat(1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("entities") as batch_op:
        batch_op.drop_constraint("fk_entities_manual_group_id_entity_groups", type_="foreignkey")
        batch_op.drop_constraint("fk_entities_system_group_id_entity_groups", type_="foreignkey")
        batch_op.drop_column("search_vector_embedding")
        batch_op.drop_column("search_document")
        batch_op.drop_column("system_needs_review")
        batch_op.drop_column("classification_confidence")
        batch_op.drop_column("classification_reason")
        batch_op.drop_column("manual_group_id")
        batch_op.drop_column("manual_category")
        batch_op.drop_column("system_group_id")
        batch_op.drop_column("system_category")
    op.drop_table("entity_groups")
