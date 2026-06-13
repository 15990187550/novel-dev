import pytest
from novel_dev.services.quality_metrics_service import (
    QualityMetricsService,
    QualityMetricInput,
)
from novel_dev.db.models import Chapter, ChapterQualityMetric
from sqlalchemy import select


@pytest.fixture
async def service(async_session):
    return QualityMetricsService(async_session)


@pytest.fixture
async def sample_chapter(async_session):
    chapter = Chapter(
        id="ch_qm_test_1",
        volume_id="v_qm_test_1",
        chapter_number=1,
        title="ch1",
        novel_id="n_qm_test_1",
    )
    async_session.add(chapter)
    await async_session.commit()
    return chapter


async def test_record_metric_persists_to_db(service, sample_chapter, async_session):
    metric = QualityMetricInput(
        chapter_id=sample_chapter.id,
        novel_id=sample_chapter.novel_id,
        phase="final",
        attempt_index=0,
        overall_score=82,
        dimension_scores={"plot_tension": 85},
        gate_status="pass",
        issue_codes=["AI_FLAVOR_HIGH"],
        latency_ms=1500,
    )
    await service.record(metric)
    await async_session.commit()

    result = await async_session.execute(
        select(ChapterQualityMetric).where(
            ChapterQualityMetric.chapter_id == sample_chapter.id
        )
    )
    loaded = result.scalar_one()
    assert loaded.overall_score == 82
    assert loaded.issue_codes == ["AI_FLAVOR_HIGH"]