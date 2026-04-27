"""align document embedding vector dimensions

Revision ID: 20260427_document_embedding_dims
Revises: 20260427_embedding_dims
Create Date: 2026-04-27 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260427_document_embedding_dims"
down_revision: Union[str, Sequence[str], None] = "20260427_embedding_dims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS idx_novel_documents_vector;")
    op.execute("UPDATE novel_documents SET vector_embedding = NULL;")
    op.execute("ALTER TABLE novel_documents ALTER COLUMN vector_embedding TYPE vector(1024) USING NULL;")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_novel_documents_vector
        ON novel_documents USING hnsw (vector_embedding vector_cosine_ops)
        WHERE vector_embedding IS NOT NULL;
    """)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS idx_novel_documents_vector;")
    op.execute("UPDATE novel_documents SET vector_embedding = NULL;")
    op.execute("ALTER TABLE novel_documents ALTER COLUMN vector_embedding TYPE vector(1536) USING NULL;")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_novel_documents_vector
        ON novel_documents USING hnsw (vector_embedding vector_cosine_ops)
        WHERE vector_embedding IS NOT NULL;
    """)
