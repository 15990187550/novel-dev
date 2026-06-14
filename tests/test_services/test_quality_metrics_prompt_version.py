import pytest
from sqlalchemy import select

from novel_dev.db.models import Chapter, ChapterQualityMetric
from novel_dev.services.quality_metrics_service import (
    QualityMetricInput,
    QualityMetricsService,
)


@pytest.mark.asyncio
async def test_record_stores_prompt_version(async_session):
    """Verify that QualityMetricsService.record stores prompt_version."""
    chapter = Chapter(
        id="ch_pv_1",
        volume_id="v_pv_1",
        chapter_number=1,
        title="t",
        novel_id="n_pv_1",
    )
    async_session.add(chapter)
    await async_session.flush()

    svc = QualityMetricsService(async_session)
    await svc.record(QualityMetricInput(
        chapter_id="ch_pv_1",
        novel_id="n_pv_1",
        phase="draft",
        attempt_index=1,
        overall_score=80,
        gate_status="warn",
        prompt_version="v2.0",
    ))
    await async_session.commit()

    result = await async_session.execute(select(ChapterQualityMetric))
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].prompt_version == "v2.0"


@pytest.mark.asyncio
async def test_record_handles_missing_prompt_version(async_session):
    """Verify that record() works when prompt_version is None."""
    chapter = Chapter(
        id="ch_pv_2",
        volume_id="v_pv_2",
        chapter_number=1,
        title="t",
        novel_id="n_pv_2",
    )
    async_session.add(chapter)
    await async_session.flush()

    svc = QualityMetricsService(async_session)
    await svc.record(QualityMetricInput(
        chapter_id="ch_pv_2",
        novel_id="n_pv_2",
        phase="draft",
        attempt_index=1,
        overall_score=80,
        gate_status="warn",
        prompt_version=None,
    ))
    await async_session.commit()

    result = await async_session.execute(select(ChapterQualityMetric))
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].prompt_version is None
