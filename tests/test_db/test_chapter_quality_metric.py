import pytest
from datetime import datetime
from sqlalchemy import select

from novel_dev.db.models import Chapter, ChapterQualityMetric


@pytest.mark.asyncio
async def test_chapter_quality_metric_persists(async_session):
    chapter = Chapter(
        id="ch_metric_1",
        volume_id="v_metric_1",
        chapter_number=1,
        title="ch1",
        novel_id="n_metric_1",
    )
    async_session.add(chapter)
    await async_session.flush()

    metric = ChapterQualityMetric(
        novel_id="n_metric_1",
        chapter_id=chapter.id,
        phase="final",
        attempt_index=0,
        overall_score=82,
        dimension_scores={"plot_tension": 85, "consistency": 78},
        gate_status="pass",
        issue_codes=["AI_FLAVOR_HIGH"],
    )
    async_session.add(metric)
    await async_session.commit()

    result = await async_session.execute(
        select(ChapterQualityMetric).where(ChapterQualityMetric.chapter_id == chapter.id)
    )
    loaded = result.scalar_one()
    assert loaded.overall_score == 82
    assert loaded.dimension_scores["plot_tension"] == 85
    assert loaded.issue_codes == ["AI_FLAVOR_HIGH"]
    assert isinstance(loaded.created_at, datetime)
