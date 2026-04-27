"""add knowledge domains

Revision ID: 20260425_knowledge_domains
Revises: 20260425_agent_logs
Create Date: 2026-04-25 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260425_knowledge_domains"
down_revision: Union[str, Sequence[str], None] = "20260425_agent_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_domains",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain_type", sa.Text(), nullable=False),
        sa.Column("scope_status", sa.Text(), nullable=False),
        sa.Column("activation_mode", sa.Text(), nullable=False),
        sa.Column("activation_keywords", sa.JSON(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("source_doc_ids", sa.JSON(), nullable=False),
        sa.Column("suggested_scopes", sa.JSON(), nullable=False),
        sa.Column("confirmed_scopes", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_domains_novel_status",
        "knowledge_domains",
        ["novel_id", "scope_status", "is_active"],
        unique=False,
    )
    op.create_table(
        "knowledge_domain_usages",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("novel_id", sa.Text(), nullable=False),
        sa.Column("domain_id", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_ref", sa.Text(), nullable=False),
        sa.Column("matched_keywords", sa.JSON(), nullable=False),
        sa.Column("usage_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(["domain_id"], ["knowledge_domains.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_domain_usages_novel_scope",
        "knowledge_domain_usages",
        ["novel_id", "scope_type", "scope_ref"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_domain_usages_novel_scope", table_name="knowledge_domain_usages")
    op.drop_table("knowledge_domain_usages")
    op.drop_index("ix_knowledge_domains_novel_status", table_name="knowledge_domains")
    op.drop_table("knowledge_domains")
