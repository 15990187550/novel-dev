"""phase 6 judge tables

Revision ID: 20260619_1200
Revises: e686cd654d1e
Create Date: 2026-06-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "20260619_1200"
down_revision: Union[str, Sequence[str], None] = "e686cd654d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: 9 columns on ab_decisions + 3 new tables."""
    # 1. Extend ab_decisions with 9 judge fields
    op.add_column("ab_decisions", sa.Column("judge_triggered", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("ab_decisions", sa.Column("judge_error", sa.String(32), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_tie_breaker_baseline", sa.Float(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_tie_breaker_challenger", sa.Float(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_scores_baseline", JSONB(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_scores_challenger", JSONB(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_rationale_baseline", sa.Text(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_rationale_challenger", sa.Text(), nullable=True))
    op.add_column("ab_decisions", sa.Column("judge_model", sa.String(64), nullable=True))
    op.create_index("ix_ab_decisions_judge_triggered", "ab_decisions", ["judge_triggered"])

    # 2. judge_prompt_versions
    op.create_table(
        "judge_prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ab_test_id", sa.String(36), nullable=True),
        sa.Column("experiment_state", sa.String(32), nullable=False, server_default="none"),
        sa.Column("last_score", sa.Float(), nullable=True),
        sa.Column("last_decision_at", sa.DateTime(), nullable=True),
        sa.Column("experiment_history", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("agent_name", "version", name="uq_judge_prompt_versions_agent_version"),
    )
    op.create_index("ix_judge_prompt_versions_active", "judge_prompt_versions", ["is_active"])
    op.create_index("ix_judge_prompt_versions_ab_test", "judge_prompt_versions", ["ab_test_id"])

    # 3. judge_ab_tests
    op.create_table(
        "judge_ab_tests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("baseline_version", sa.String(32), nullable=False),
        sa.Column("challenger_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("config", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("winner", sa.String(16), nullable=True),
    )
    op.create_index("ix_judge_ab_tests_agent_name", "judge_ab_tests", ["agent_name"])
    op.create_index("ix_judge_ab_tests_status", "judge_ab_tests", ["status"])

    # 4. judge_call_log
    op.create_table(
        "judge_call_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("decision_id", sa.String(36), nullable=True),
        sa.Column("experiment_id", sa.String(36), nullable=True),
        sa.Column("prompt_version_id", sa.String(36), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("called_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_judge_call_log_decision", "judge_call_log", ["decision_id"])
    op.create_index("ix_judge_call_log_experiment_called", "judge_call_log", ["experiment_id", "called_at"])


def downgrade() -> None:
    """Downgrade schema: drop the 3 new tables and 9 new columns from ab_decisions."""
    op.drop_index("ix_judge_call_log_experiment_called", table_name="judge_call_log")
    op.drop_index("ix_judge_call_log_decision", table_name="judge_call_log")
    op.drop_table("judge_call_log")
    op.drop_index("ix_judge_ab_tests_status", table_name="judge_ab_tests")
    op.drop_index("ix_judge_ab_tests_agent_name", table_name="judge_ab_tests")
    op.drop_table("judge_ab_tests")
    op.drop_index("ix_judge_prompt_versions_ab_test", table_name="judge_prompt_versions")
    op.drop_index("ix_judge_prompt_versions_active", table_name="judge_prompt_versions")
    op.drop_table("judge_prompt_versions")
    op.drop_index("ix_ab_decisions_judge_triggered", table_name="ab_decisions")
    op.drop_column("ab_decisions", "judge_model")
    op.drop_column("ab_decisions", "judge_rationale_challenger")
    op.drop_column("ab_decisions", "judge_rationale_baseline")
    op.drop_column("ab_decisions", "judge_scores_challenger")
    op.drop_column("ab_decisions", "judge_scores_baseline")
    op.drop_column("ab_decisions", "judge_tie_breaker_challenger")
    op.drop_column("ab_decisions", "judge_tie_breaker_baseline")
    op.drop_column("ab_decisions", "judge_error")
    op.drop_column("ab_decisions", "judge_triggered")
