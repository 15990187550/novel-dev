# tests/test_agents/test_fast_review_metric_write.py
import pytest
from novel_dev.db.models import Chapter, ChapterQualityMetric
from novel_dev.services.quality_metrics_service import QualityMetricsService
from sqlalchemy import select


@pytest.fixture
async def chapter_with_session(async_session):
    chapter = Chapter(
        id="ch_metric_write_1",
        volume_id="v_metric_write_1",
        chapter_number=1,
        title="ch1",
        novel_id="n_metric_write_1",
    )
    async_session.add(chapter)
    await async_session.commit()
    return chapter


async def test_finalize_and_record_metric_writes_row(chapter_with_session, async_session):
    from novel_dev.agents.fast_review_agent import FastReviewAgent

    agent = FastReviewAgent.__new__(FastReviewAgent)
    agent.session = async_session

    await agent._finalize_and_record_metric(
        chapter=chapter_with_session,
        phase="fast_reviewing",
        attempt_index=0,
        final_score=82,
        final_feedback={"overall": 82, "breakdown": {"plot_tension": 80}},
        gate_status="pass",
        issue_codes=["AI_FLAVOR_HIGH"],
    )
    await async_session.commit()

    result = await async_session.execute(
        select(ChapterQualityMetric).where(
            ChapterQualityMetric.chapter_id == chapter_with_session.id
        )
    )
    metric = result.scalar_one()
    assert metric.phase == "fast_reviewing"
    assert metric.overall_score == 82
    assert metric.gate_status == "pass"
    assert metric.issue_codes == ["AI_FLAVOR_HIGH"]


async def test_finalize_handles_metric_failure_gracefully(chapter_with_session, async_session, monkeypatch):
    from novel_dev.agents.fast_review_agent import FastReviewAgent

    agent = FastReviewAgent.__new__(FastReviewAgent)
    agent.session = async_session

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated DB failure")
    monkeypatch.setattr(QualityMetricsService, "record", boom)

    # Should NOT raise
    await agent._finalize_and_record_metric(
        chapter=chapter_with_session,
        phase="fast_reviewing",
        attempt_index=0,
        final_score=82,
        final_feedback={},
        gate_status="pass",
    )
