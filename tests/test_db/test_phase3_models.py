import pytest
from novel_dev.db.models import PromptVersion, QualityRootCause, ABTest


def test_prompt_version_table_columns():
    assert hasattr(PromptVersion, "agent_name")
    assert hasattr(PromptVersion, "version")
    assert hasattr(PromptVersion, "content")
    assert hasattr(PromptVersion, "is_active")
    assert hasattr(PromptVersion, "created_at")
    assert hasattr(PromptVersion, "created_by")
    assert hasattr(PromptVersion, "sample_count")
    assert hasattr(PromptVersion, "parent_version")
    assert hasattr(PromptVersion, "ab_test_id")


def test_quality_root_cause_table_columns():
    assert hasattr(QualityRootCause, "chapter_id")
    assert hasattr(QualityRootCause, "analyzer_version")
    assert hasattr(QualityRootCause, "summary")
    assert hasattr(QualityRootCause, "suggested_actions")
    assert hasattr(QualityRootCause, "confidence")
    assert hasattr(QualityRootCause, "input_snapshot")
    assert hasattr(QualityRootCause, "created_at")


def test_ab_test_table_columns():
    assert hasattr(ABTest, "agent_name")
    assert hasattr(ABTest, "baseline_version")
    assert hasattr(ABTest, "challenger_version")
    assert hasattr(ABTest, "status")
    assert hasattr(ABTest, "winner")
    assert hasattr(ABTest, "started_at")
    assert hasattr(ABTest, "ended_at")
    assert hasattr(ABTest, "config")