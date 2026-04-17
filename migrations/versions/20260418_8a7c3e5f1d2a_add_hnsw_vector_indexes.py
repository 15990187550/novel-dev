"""add hnsw vector indexes

Revision ID: 8a7c3e5f1d2a
Revises: 05af082fea75
Create Date: 2026-04-18 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8a7c3e5f1d2a'
down_revision: Union[str, Sequence[str], None] = '05af082fea75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        # HNSW indexes accelerate vector similarity search on PostgreSQL.
        # The WHERE clause skips rows with NULL embeddings, which is valid
        # since pgvector indexes only work on non-NULL values.
        op.execute("""
            CREATE INDEX IF NOT EXISTS idx_novel_documents_vector
            ON novel_documents USING hnsw (vector_embedding vector_cosine_ops)
            WHERE vector_embedding IS NOT NULL;
        """)
        op.execute("""
            CREATE INDEX IF NOT EXISTS idx_entities_vector
            ON entities USING hnsw (vector_embedding vector_cosine_ops)
            WHERE vector_embedding IS NOT NULL;
        """)
        op.execute("""
            CREATE INDEX IF NOT EXISTS idx_chapters_vector
            ON chapters USING hnsw (vector_embedding vector_cosine_ops)
            WHERE vector_embedding IS NOT NULL;
        """)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_chapters_vector;")
        op.execute("DROP INDEX IF EXISTS idx_entities_vector;")
        op.execute("DROP INDEX IF EXISTS idx_novel_documents_vector;")
