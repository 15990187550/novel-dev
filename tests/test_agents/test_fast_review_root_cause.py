"""Task 13 — FastReviewAgent 集成 RootCauseAnalyzer。

The FastReviewAgent's main entry point is `review_standalone(novel_id, chapter_id, checkpoint)`.
After the quality gate is evaluated, when gate.status != "pass" the agent should
call RootCauseAnalyzer.analyze() and persist the summary + suggested_actions
into the checkpoint so downstream stages (Writer, Editor, etc.) can act on
the diagnosed root cause.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents.fast_review_agent import FastReviewAgent
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.services.quality_gate_service import (
    QUALITY_BLOCK,
    QUALITY_PASS,
    QUALITY_WARN,
    QualityGateResult,
)
from novel_dev.services.root_cause_analyzer import RootCauseResult


def _build_gate(status: str) -> QualityGateResult:
    """Build a gate that will produce the desired final code path.

    Each status maps to a small list of issue items so the analyzer receives
    a non-empty `issue_codes` list.
    """
    if status == QUALITY_WARN:
        return QualityGateResult(
            status=status,
            warning_items=[{"code": "ai_flavor", "message": "AI 腔未充分降低"}],
            summary="可放行告警",
        )
    if status == QUALITY_BLOCK:
        return QualityGateResult(
            status=status,
            blocking_items=[{"code": "consistency", "message": "主角状态冲突"}],
            summary="存在阻断问题",
        )
    return QualityGateResult(status=QUALITY_PASS, summary="通过")


def _patch_root_cause_analyzer(monkey_target: str):
    """Return a context manager that patches RootCauseAnalyzer at the
    `novel_dev.agents.fast_review_agent.RootCauseAnalyzer` import path so the
    agent's lazy import resolves to our mock.
    """
    return patch(monkey_target)


@pytest.mark.asyncio
async def test_fast_review_calls_root_cause_for_warn(async_session):
    """Verify analyzer is called when gate_status is warn."""
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_root_cause_warn",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 4}}},
        volume_id="v1",
        chapter_id="c_root_cause_warn",
    )
    repo = ChapterRepository(async_session)
    await repo.create("c_root_cause_warn", "v1", 1, "Warn")
    await repo.update_text("c_root_cause_warn", raw_draft="甲乙丙。", polished_text="甲乙丙。")
    checkpoint = {"chapter_context": {"chapter_plan": {"target_word_count": 4}}}

    fake_gate = _build_gate(QUALITY_WARN)

    with patch(
        "novel_dev.agents.fast_review_agent.call_and_parse_model",
        new_callable=AsyncMock,
        return_value=type("LLMCheck", (), {
            "consistency_fixed": True,
            "beat_cohesion_ok": True,
            "notes": [],
        })(),
    ), patch(
        "novel_dev.services.quality_gate_service.QualityGateService.evaluate_fast_review",
        return_value=fake_gate,
    ), patch(
        "novel_dev.agents.fast_review_agent.RootCauseAnalyzer",
    ) as MockAnalyzer, patch(
        "novel_dev.agents.fast_review_agent.RecommendationWirer",
        create=True,
    ) as MockWirer:
        instance = MockAnalyzer.return_value
        instance.analyze = AsyncMock(return_value=RootCauseResult(
            summary="warn summary",
            suggested_actions=[{"action": "改写", "target": "beat:0"}],
            confidence=0.6,
        ))
        MockWirer.return_value.evaluate_and_dispatch = AsyncMock(
            return_value=type("WR", (), {"action": "noop"})()
        )

        agent = FastReviewAgent(async_session)
        await agent.review_standalone("novel_fr_root_cause_warn", "c_root_cause_warn", checkpoint)

    instance.analyze.assert_awaited_once()
    call_kwargs = instance.analyze.await_args.kwargs
    assert call_kwargs["novel_id"] == "novel_fr_root_cause_warn"
    assert call_kwargs["chapter_id"] == "c_root_cause_warn"
    assert checkpoint.get("root_cause") == "warn summary"
    assert checkpoint.get("root_cause_actions") == [{"action": "改写", "target": "beat:0"}]


@pytest.mark.asyncio
async def test_fast_review_calls_root_cause_for_block(async_session):
    """Verify analyzer is called when gate_status is block."""
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_root_cause_block",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 4}}},
        volume_id="v1",
        chapter_id="c_root_cause_block",
    )
    repo = ChapterRepository(async_session)
    await repo.create("c_root_cause_block", "v1", 1, "Block")
    await repo.update_text("c_root_cause_block", raw_draft="甲乙丙。", polished_text="甲乙丙。")
    checkpoint = {"chapter_context": {"chapter_plan": {"target_word_count": 4}}}

    fake_gate = _build_gate(QUALITY_BLOCK)

    with patch(
        "novel_dev.agents.fast_review_agent.call_and_parse_model",
        new_callable=AsyncMock,
        return_value=type("LLMCheck", (), {
            "consistency_fixed": True,
            "beat_cohesion_ok": True,
            "notes": [],
        })(),
    ), patch(
        "novel_dev.services.quality_gate_service.QualityGateService.evaluate_fast_review",
        return_value=fake_gate,
    ), patch(
        "novel_dev.agents.fast_review_agent.RootCauseAnalyzer",
    ) as MockAnalyzer, patch(
        "novel_dev.agents.fast_review_agent.RecommendationWirer",
        create=True,
    ) as MockWirer:
        instance = MockAnalyzer.return_value
        instance.analyze = AsyncMock(return_value=RootCauseResult(
            summary="block summary",
            suggested_actions=[{"action": "重写", "target": "beat:1", "severity": "high"}],
            confidence=0.9,
        ))
        MockWirer.return_value.evaluate_and_dispatch = AsyncMock(
            return_value=type("WR", (), {"action": "noop"})()
        )

        agent = FastReviewAgent(async_session)
        await agent.review_standalone("novel_fr_root_cause_block", "c_root_cause_block", checkpoint)

    instance.analyze.assert_awaited_once()
    assert checkpoint.get("root_cause") == "block summary"
    assert checkpoint.get("root_cause_actions") == [{"action": "重写", "target": "beat:1", "severity": "high"}]


@pytest.mark.asyncio
async def test_fast_review_skips_root_cause_for_pass(async_session):
    """Verify analyzer is NOT called when gate_status is pass (per spec)."""
    director = NovelDirector(session=async_session)
    await director.save_checkpoint(
        "novel_fr_root_cause_pass",
        phase=Phase.FAST_REVIEWING,
        checkpoint_data={"chapter_context": {"chapter_plan": {"target_word_count": 4}}},
        volume_id="v1",
        chapter_id="c_root_cause_pass",
    )
    repo = ChapterRepository(async_session)
    await repo.create("c_root_cause_pass", "v1", 1, "Pass")
    await repo.update_text("c_root_cause_pass", raw_draft="甲乙丙。", polished_text="甲乙丙。")
    checkpoint = {"chapter_context": {"chapter_plan": {"target_word_count": 4}}}

    fake_gate = _build_gate(QUALITY_PASS)

    with patch(
        "novel_dev.agents.fast_review_agent.call_and_parse_model",
        new_callable=AsyncMock,
        return_value=type("LLMCheck", (), {
            "consistency_fixed": True,
            "beat_cohesion_ok": True,
            "notes": [],
        })(),
    ), patch(
        "novel_dev.services.quality_gate_service.QualityGateService.evaluate_fast_review",
        return_value=fake_gate,
    ), patch(
        "novel_dev.agents.fast_review_agent.RootCauseAnalyzer",
    ) as MockAnalyzer, patch(
        "novel_dev.agents.fast_review_agent.RecommendationWirer",
        create=True,
    ) as MockWirer:
        instance = MockAnalyzer.return_value
        instance.analyze = AsyncMock()
        MockWirer.return_value.evaluate_and_dispatch = AsyncMock(
            return_value=type("WR", (), {"action": "noop"})()
        )

        agent = FastReviewAgent(async_session)
        await agent.review_standalone("novel_fr_root_cause_pass", "c_root_cause_pass", checkpoint)

    instance.analyze.assert_not_awaited()
    assert "root_cause" not in checkpoint
    assert "root_cause_actions" not in checkpoint
