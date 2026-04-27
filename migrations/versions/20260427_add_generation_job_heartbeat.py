"""add generation job heartbeat

Revision ID: 20260427_generation_job_heartbeat
Revises: 20260427_document_embedding_dims
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260427_generation_job_heartbeat"
down_revision: Union[str, Sequence[str], None] = "20260427_document_embedding_dims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("heartbeat_at", sa.TIMESTAMP(), nullable=True))


def downgrade() -> None:
    op.drop_column("generation_jobs", "heartbeat_at")
