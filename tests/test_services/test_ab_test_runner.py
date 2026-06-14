import pytest
from novel_dev.services.ab_test_runner import ABTestRunner


@pytest.mark.asyncio
async def test_start_creates_test_record(async_session):
    runner = ABTestRunner(async_session)
    ab = await runner.start(
        agent_name="critic",
        baseline_version="v1.0", challenger_version="v2.0",
        max_samples=10, min_samples=3,
    )
    assert ab.status == "running"
    assert ab.config["max_samples"] == 10


@pytest.mark.asyncio
async def test_pick_version_is_stable_per_chapter(async_session):
    runner = ABTestRunner(async_session)
    await runner.start("critic", "v1.0", "v2.0", max_samples=10, min_samples=3)
    v1 = await runner.pick_version("critic", "ch_1")
    v2 = await runner.pick_version("critic", "ch_1")
    assert v1 == v2


@pytest.mark.asyncio
async def test_pick_version_distributes_across_chapters(async_session):
    runner = ABTestRunner(async_session)
    await runner.start("critic", "v1.0", "v2.0", max_samples=10, min_samples=3)
    baseline_count = 0
    for i in range(100):
        v = await runner.pick_version("critic", f"ch_{i}")
        if v == "v1.0":
            baseline_count += 1
    assert 40 <= baseline_count <= 60


@pytest.mark.asyncio
async def test_results_calculates_p_value(async_session):
    from novel_dev.db.models import Chapter
    from novel_dev.services.quality_metrics_service import QualityMetricsService, QualityMetricInput

    # Create real Chapter rows since chapter_id is a FK
    chapters = []
    for i in range(5):
        ch = Chapter(
            id=f"baseline_{i}", volume_id="v_test",
            chapter_number=i + 1, title=f"baseline {i}",
            novel_id="n_1",
        )
        async_session.add(ch)
        chapters.append(ch)
    for i in range(5):
        ch = Chapter(
            id=f"challenger_{i}", volume_id="v_test",
            chapter_number=i + 100, title=f"challenger {i}",
            novel_id="n_1",
        )
        async_session.add(ch)
        chapters.append(ch)
    await async_session.flush()

    runner = ABTestRunner(async_session)
    await runner.start("critic", "v1.0", "v2.0", max_samples=10, min_samples=3)

    svc = QualityMetricsService(async_session)
    for i in range(5):
        await svc.record(QualityMetricInput(
            chapter_id=f"baseline_{i}", novel_id="n_1", phase="critic",
            attempt_index=1, overall_score=70 + i, gate_status="warn",
            prompt_version="v1.0",
        ))
    for i in range(5):
        await svc.record(QualityMetricInput(
            chapter_id=f"challenger_{i}", novel_id="n_1", phase="critic",
            attempt_index=1, overall_score=85 + i, gate_status="warn",
            prompt_version="v2.0",
        ))
    await async_session.flush()

    ab_id = (await runner.list_running())[0].id
    result = await runner.results(ab_id)
    assert result.baseline_mean < result.challenger_mean
    assert result.p_value < 0.05
    assert result.winner == "challenger"


@pytest.mark.asyncio
async def test_results_inconclusive_when_too_few_samples(async_session):
    runner = ABTestRunner(async_session)
    ab = await runner.start("critic", "v1.0", "v2.0", max_samples=10, min_samples=3)
    result = await runner.results(ab.id)
    assert result.winner is None
    assert result.status == "pending"
