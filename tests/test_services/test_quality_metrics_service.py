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


async def test_query_trends_falls_back_to_chapter_score(service, sample_chapter, async_session):
    from novel_dev.db.models import Chapter
    from sqlalchemy import select

    result = await async_session.execute(
        select(Chapter).where(Chapter.id == sample_chapter.id)
    )
    chapter = result.scalar_one()
    chapter.score_overall = 78
    await async_session.commit()

    trends = await service.get_trends(
        novel_id=sample_chapter.novel_id,
        dimension="overall",
        phase="final",
    )
    assert len(trends) == 1
    assert trends[0]["value"] == 78
    assert trends[0]["source"] == "chapter_fallback"


async def test_query_trends_prefers_metrics_table(service, sample_chapter, async_session):
    from novel_dev.db.models import Chapter
    from sqlalchemy import select

    chapter = (await async_session.execute(
        select(Chapter).where(Chapter.id == sample_chapter.id)
    )).scalar_one()
    chapter.score_overall = 60
    await async_session.commit()

    await service.record(QualityMetricInput(
        chapter_id=sample_chapter.id,
        novel_id=sample_chapter.novel_id,
        phase="final",
        gate_status="pass",
        overall_score=82,
    ))
    await async_session.commit()

    trends = await service.get_trends(
        novel_id=sample_chapter.novel_id,
        dimension="overall",
        phase="final",
    )
    assert len(trends) == 1
    assert trends[0]["value"] == 82
    assert trends[0]["source"] == "metrics"


async def test_aggregate_issues_empty_novel(service):
    agg = await service.aggregate_issues(novel_id="n_qm_empty")
    assert agg == {"counts": {}, "total_chapters": 0}


async def test_aggregate_issues_aggregates_counts(service, async_session):
    for idx, num, codes in [
        (0, 1, ["AI_FLAVOR_HIGH", "PACING_DRAG"]),
        (1, 2, ["AI_FLAVOR_HIGH"]),
        (2, 3, ["PACING_DRAG", "PACING_DRAG"]),
    ]:
        ch = Chapter(
            id=f"ch_qm_agg_{idx}",
            volume_id="v_qm_agg",
            chapter_number=num,
            title=f"ch{num}",
            novel_id="n_qm_agg",
        )
        async_session.add(ch)
        await async_session.commit()
        await service.record(QualityMetricInput(
            chapter_id=ch.id,
            novel_id=ch.novel_id,
            phase="final",
            gate_status="pass",
            issue_codes=codes,
        ))
        await async_session.commit()

    agg = await service.aggregate_issues(novel_id="n_qm_agg")
    assert agg["counts"] == {
        "AI_FLAVOR_HIGH": 2,
        "PACING_DRAG": 3,
    }
    assert agg["total_chapters"] == 3


async def test_aggregate_issues_respects_chapter_range(service, async_session):
    for idx, num in enumerate([1, 2, 3, 4], start=1):
        ch = Chapter(
            id=f"ch_qm_rng_{idx}",
            volume_id="v_qm_rng",
            chapter_number=num,
            title=f"ch{num}",
            novel_id="n_qm_rng",
        )
        async_session.add(ch)
        await async_session.commit()
        await service.record(QualityMetricInput(
            chapter_id=ch.id,
            novel_id=ch.novel_id,
            phase="final",
            gate_status="pass",
            issue_codes=["AI_FLAVOR_HIGH"],
        ))
        await async_session.commit()

    agg = await service.aggregate_issues(
        novel_id="n_qm_rng", from_chapter=2, to_chapter=3
    )
    assert agg["total_chapters"] == 2
    assert agg["counts"] == {"AI_FLAVOR_HIGH": 2}