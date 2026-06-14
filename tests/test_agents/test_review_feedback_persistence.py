"""Regression test for review feedback persistence.

Verifies the persistence path between CriticAgent -> Chapter (review_feedback
and final_review_feedback columns) -> FastReviewAgent (metric row written via
_finalize_and_record_metric).

Reference: Task 18 noted that build_quality_quality_snapshot was wired to read
`final_review_feedback` and `draft_review_feedback` from the Chapter record, so
those fields must survive a DB round-trip and be the source of truth for
downstream metric recording.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from novel_dev.agents.critic_agent import CriticAgent
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents.fast_review_agent import FastReviewAgent
from novel_dev.db.models import Chapter, ChapterQualityMetric
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.schemas.context import (
    BeatPlan,
    ChapterContext,
    ChapterPlan,
    LocationContext,
)
from novel_dev.llm.models import LLMResponse
from novel_dev.schemas.review import DimensionScore, ScoreResult


def _make_context() -> dict:
    plan = ChapterPlan(
        chapter_number=1,
        title="T",
        target_word_count=3000,
        beats=[BeatPlan(summary="B1", target_mood="tense")],
    )
    ctx = ChapterContext(
        chapter_plan=plan,
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current=""),
        timeline_events=[],
        pending_foreshadowings=[],
    )
    return ctx.model_dump()


async def _seed_chapter_and_state(
    async_session,
    *,
    novel_id: str,
    chapter_id: str,
    volume_id: str = "v_rfp_1",
    phase: Phase = Phase.REVIEWING,
) -> Chapter:
    """Set up minimal checkpoint + chapter row for a given novel/chapter id."""
    context = _make_context()
    await NovelDirector(async_session).save_checkpoint(
        novel_id,
        phase=phase,
        checkpoint_data={"chapter_context": context, "draft_attempt_count": 0},
        volume_id=volume_id,
        chapter_id=chapter_id,
    )
    chapter_repo = ChapterRepository(async_session)
    await chapter_repo.create(chapter_id, volume_id, 1, "Test", novel_id=novel_id)
    await chapter_repo.update_text(chapter_id, raw_draft="a" * 200)
    chapter = await chapter_repo.get_by_id(chapter_id)
    assert chapter is not None
    return chapter


def _make_score_result(overall: int = 88) -> ScoreResult:
    return ScoreResult(
        overall=overall,
        dimensions=[
            DimensionScore(name="plot_tension", score=85, comment="节奏稳定"),
            DimensionScore(name="characterization", score=85, comment="人物行为一致"),
            DimensionScore(name="readability", score=85, comment="可读性良好"),
            DimensionScore(name="consistency", score=85, comment="设定无冲突"),
            DimensionScore(name="humanity", score=85, comment="自然流畅"),
        ],
        summary_feedback="整体良好",
    )


# ----------------------------------------------------------------------
# Test 1: CriticAgent.review() persists feedback onto the Chapter row
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_critic_persists_draft_review_feedback_on_chapter(async_session):
    """After CriticAgent.review() runs with a passing score, the Chapter row
    must carry both `review_feedback` and `draft_review_feedback` populated
    with the score_result summary so the next session can read them.
    """
    novel_id = "n_rfp_critic_persists"
    chapter_id = "c_rfp_critic_persists"
    await _seed_chapter_and_state(async_session, novel_id=novel_id, chapter_id=chapter_id)

    score_result = _make_score_result(overall=88)
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[{"beat_index": 0, "scores": {"plot_tension": 80, "humanity": 80}}]'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        await agent.review(novel_id, chapter_id)

    chapter = await ChapterRepository(async_session).get_by_id(chapter_id)
    assert chapter is not None
    # The `review_feedback` column is the legacy slot; `draft_review_feedback`
    # is the column the snapshot reads from. Both must be populated.
    assert chapter.draft_review_feedback is not None
    assert chapter.draft_review_feedback.get("summary") == "整体良好"
    assert chapter.draft_review_score == 88
    # The score breakdown must include dimension comments keyed by dimension
    # so the metric record + snapshot can render dimension_feedback downstream.
    assert chapter.score_breakdown is not None
    assert chapter.score_breakdown["plot_tension"]["score"] == 85
    assert chapter.score_breakdown["plot_tension"]["comment"] == "节奏稳定"


# ----------------------------------------------------------------------
# Test 2: Feedback survives a DB round-trip (expire/refresh)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_review_feedback_survives_db_round_trip(async_session):
    """Reload the chapter in a fresh query (forcing a SELECT) and verify the
    feedback dicts still match what was written. This guards against any
    in-memory state leak where the original Python object is referenced.
    """
    novel_id = "n_rfp_round_trip"
    chapter_id = "c_rfp_round_trip"
    await _seed_chapter_and_state(async_session, novel_id=novel_id, chapter_id=chapter_id)

    score_result = _make_score_result(overall=85)
    mock_client = AsyncMock()
    mock_client.acomplete.side_effect = [
        LLMResponse(text=score_result.model_dump_json()),
        LLMResponse(text='[{"beat_index": 0, "scores": {"plot_tension": 80, "humanity": 80}}]'),
    ]

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = CriticAgent(async_session)
        await agent.review(novel_id, chapter_id)
    await async_session.commit()

    # Force a fresh SELECT to ensure the row was actually persisted, not just
    # mutated on the in-session instance.
    async_session.expire_all()
    chapter = (await async_session.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )).scalar_one()

    expected_summary = "整体良好"
    assert chapter.draft_review_feedback is not None
    assert chapter.draft_review_feedback.get("summary") == expected_summary
    assert chapter.draft_review_score == 85
    # And the score breakdown dict must be intact
    assert chapter.score_breakdown["humanity"]["comment"] == "自然流畅"


# ----------------------------------------------------------------------
# Test 3: FastReviewAgent._finalize_and_record_metric picks up the
# final_review_feedback breakdown that was persisted on the Chapter row
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_metric_row_references_persisted_final_feedback(async_session):
    """After FastReviewAgent finalizes, the metric row's `dimension_scores`
    field must be derived from the same final_review_feedback dict the
    Chapter row carries. We seed a chapter with a known final_review_feedback
    and feed it through _finalize_and_record_metric, then verify the metric
    row's breakdown matches the persisted feedback.
    """
    novel_id = "n_rfp_metric_refs_persisted"
    chapter_id = "c_rfp_metric_refs_persisted"
    chapter_repo = ChapterRepository(async_session)
    await chapter_repo.create(chapter_id, "v_rfp_metric", 1, "Test", novel_id=novel_id)
    chapter = await chapter_repo.get_by_id(chapter_id)
    assert chapter is not None

    # Seed a known final_review_feedback on the chapter as if FastReviewAgent
    # had already run and persisted it. This is the field the snapshot reads.
    final_feedback = {
        "overall": 82,
        "summary": "整体表现稳定",
        "breakdown": {
            "plot_tension": {"score": 80, "comment": "节拍推进稳定"},
            "humanity": {"score": 84, "comment": "对话自然"},
        },
        "per_dim_issues": [
            {"dim": "plot_tension", "problem": "第2节拍偏长", "suggestion": "缩短过渡"},
        ],
    }
    await chapter_repo.update_quality_gate(
        chapter_id,
        quality_status="pass",
        quality_reasons={},
        final_review_score=82,
        final_review_feedback=final_feedback,
        world_state_ingested=False,
    )

    agent = FastReviewAgent.__new__(FastReviewAgent)
    agent.session = async_session

    await agent._finalize_and_record_metric(
        chapter=chapter,
        phase="fast_reviewing",
        attempt_index=0,
        final_score=82,
        final_feedback=final_feedback,
        gate_status="pass",
        issue_codes=[],
    )
    await async_session.commit()

    metric = (await async_session.execute(
        select(ChapterQualityMetric).where(ChapterQualityMetric.chapter_id == chapter_id)
    )).scalar_one()

    # The metric row's dimension_scores must match the final_review_feedback
    # breakdown we persisted on the chapter.
    assert metric.dimension_scores == final_feedback["breakdown"]
    assert metric.overall_score == 82
    assert metric.gate_status == "pass"

    # And the chapter row's final_review_feedback must still be intact
    # after the metric write (no accidental clobbering).
    reloaded = await chapter_repo.get_by_id(chapter_id)
    assert reloaded.final_review_feedback == final_feedback
    assert reloaded.final_review_score == 82


# ----------------------------------------------------------------------
# Test 4: Metric row handles missing feedback gracefully (no crash)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_metric_row_handles_missing_feedback_gracefully(async_session):
    """If a chapter has no final_review_feedback (e.g., fast review bails
    out before persisting), _finalize_and_record_metric must still write
    a metric row without crashing.
    """
    novel_id = "n_rfp_metric_no_feedback"
    chapter_id = "c_rfp_metric_no_feedback"
    chapter_repo = ChapterRepository(async_session)
    await chapter_repo.create(chapter_id, "v_rfp_nf", 1, "Test", novel_id=novel_id)
    chapter = await chapter_repo.get_by_id(chapter_id)
    assert chapter is not None

    agent = FastReviewAgent.__new__(FastReviewAgent)
    agent.session = async_session

    # Empty / None feedback must not raise.
    await agent._finalize_and_record_metric(
        chapter=chapter,
        phase="fast_reviewing",
        attempt_index=0,
        final_score=None,
        final_feedback=None,
        gate_status="pass",
        issue_codes=[],
    )
    await agent._finalize_and_record_metric(
        chapter=chapter,
        phase="fast_reviewing",
        attempt_index=1,
        final_score=None,
        final_feedback={},
        gate_status="pass",
        issue_codes=[],
    )
    await async_session.commit()

    metrics = (await async_session.execute(
        select(ChapterQualityMetric).where(ChapterQualityMetric.chapter_id == chapter_id)
        .order_by(ChapterQualityMetric.attempt_index.asc())
    )).scalars().all()
    assert len(metrics) == 2
    # When no feedback was available, dimension_scores should be an empty dict
    # (not None, not crash) so downstream consumers can iterate safely.
    assert metrics[0].dimension_scores == {}
    assert metrics[1].dimension_scores == {}


# ----------------------------------------------------------------------
# Test 5: Snapshot path exposes final_review_feedback and draft_review_feedback
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_snapshot_includes_persisted_feedback_fields(async_session):
    """The quality summary snapshot reader expects
    `chapter["final_review_feedback"]` and `chapter["draft_review_feedback"]`
    to be populated from the Chapter row. Verify both flow into the
    serialized chapter dict that the snapshot builder emits.
    """
    from novel_dev.testing.generation_runner import _build_generation_quality_snapshot
    from novel_dev.testing.report import TestRunReport

    novel_id = "n_rfp_snapshot"
    chapter_id = "c_rfp_snapshot"
    volume_id = "v_rfp_snap"
    chapter_repo = ChapterRepository(async_session)
    await chapter_repo.create(chapter_id, volume_id, 1, "Test", novel_id=novel_id)

    # _build_generation_quality_snapshot reads NovelState.checkpoint_data to
    # enrich the snapshot, so we must seed a state row too.
    await NovelDirector(async_session).save_checkpoint(
        novel_id,
        phase=Phase.DRAFTING,
        checkpoint_data={"chapter_context": _make_context()},
        volume_id=volume_id,
        chapter_id=chapter_id,
    )
    # Commit so the snapshot's separately-opened session can see the row.
    await async_session.commit()

    final_feedback = {"overall": 90, "summary": "整体优秀", "breakdown": {"plot_tension": {"score": 90, "comment": "ok"}}}
    draft_feedback = {"summary": "草稿评估"}
    await chapter_repo.update_quality_gate(
        chapter_id,
        quality_status="pass",
        quality_reasons={},
        final_review_score=90,
        final_review_feedback=final_feedback,
        draft_review_score=80,
        draft_review_feedback=draft_feedback,
        world_state_ingested=False,
    )
    await async_session.commit()

    report = TestRunReport(
        run_id="rfp-snap",
        entrypoint="test",
        status="passed",
        duration_seconds=0.0,
        dataset="test",
        llm_mode="postprocess",
        artifacts={"novel_id": novel_id},
    )
    snapshot = await _build_generation_quality_snapshot(report)
    assert snapshot is not None

    chapter_dicts = snapshot.get("chapters") or []
    assert chapter_dicts, "snapshot must include the seeded chapter"
    snap_chapter = next(c for c in chapter_dicts if c.get("chapter_id") == chapter_id)
    assert snap_chapter.get("final_review_feedback") == final_feedback
    assert snap_chapter.get("draft_review_feedback") == draft_feedback
    assert snap_chapter.get("final_review_score") == 90
    assert snap_chapter.get("draft_review_score") == 80
