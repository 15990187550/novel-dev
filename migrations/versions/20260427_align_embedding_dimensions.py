"""align embedding vector dimensions

Revision ID: 20260427_embedding_dims
Revises: 20260425_knowledge_domains
Create Date: 2026-04-27 08:45:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260427_embedding_dims"
down_revision: Union[str, Sequence[str], None] = "20260425_knowledge_domains"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS idx_entities_vector;")
    op.execute("DROP INDEX IF EXISTS idx_chapters_vector;")
    op.execute("UPDATE entities SET vector_embedding = NULL;")
    op.execute("UPDATE chapters SET vector_embedding = NULL;")
    op.execute("ALTER TABLE entities ALTER COLUMN vector_embedding TYPE vector(1024) USING NULL;")
    op.execute("ALTER TABLE chapters ALTER COLUMN vector_embedding TYPE vector(1024) USING NULL;")
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
    if conn.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS idx_entities_vector;")
    op.execute("DROP INDEX IF EXISTS idx_chapters_vector;")
    op.execute("UPDATE entities SET vector_embedding = NULL;")
    op.execute("UPDATE chapters SET vector_embedding = NULL;")
    op.execute("ALTER TABLE entities ALTER COLUMN vector_embedding TYPE vector(1536) USING NULL;")
    op.execute("ALTER TABLE chapters ALTER COLUMN vector_embedding TYPE vector(1536) USING NULL;")
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
