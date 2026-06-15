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


@pytest.mark.asyncio
async def test_start_raises_when_running_exists(async_session):
    runner = ABTestRunner(async_session)
    await runner.start("critic", "v1.0", "v2.0")
    with pytest.raises(ValueError, match="already has a running"):
        await runner.start("critic", "v1.0", "v2.0")


@pytest.mark.asyncio
async def test_stop_marks_aborted(async_session):
    runner = ABTestRunner(async_session)
    ab = await runner.start("critic", "v1.0", "v2.0")
    result = await runner.stop(ab.id)
    assert result.status == "aborted"
    assert result.ended_at is not None


@pytest.mark.asyncio
async def test_list_all_returns_all(async_session):
    runner = ABTestRunner(async_session)
    ab = await runner.start("critic", "v1.0", "v2.0")
    await runner.stop(ab.id)  # one aborted
    await runner.start("writer", "v1.0", "v2.0")  # one running
    all_tests = await runner.list_all()
    assert len(all_tests) == 2


@pytest.mark.asyncio
async def test_pick_version_returns_none_when_no_running(async_session):
    runner = ABTestRunner(async_session)
    v = await runner.pick_version("critic", "ch_1")
    assert v is None


@pytest.mark.asyncio
async def test_results_raises_when_test_not_found(async_session):
    runner = ABTestRunner(async_session)
    with pytest.raises(ValueError, match="not found"):
        await runner.results("nonexistent_id")


@pytest.mark.asyncio
async def test_results_marks_completed_when_threshold_met(async_session):
    from novel_dev.db.models import Chapter
    from novel_dev.services.quality_metrics_service import QualityMetricsService, QualityMetricInput
    # Need 4+4 chapters
    chapters = []
    for i in range(8):
        ch = Chapter(
            id=f"ch_{i}", volume_id="v_t", chapter_number=i + 1,
            title=f"t {i}", novel_id="n_1",
        )
        async_session.add(ch)
        chapters.append(ch)
    await async_session.flush()

    runner = ABTestRunner(async_session)
    ab = await runner.start("critic", "v1.0", "v2.0", max_samples=2, min_samples=4)

    svc = QualityMetricsService(async_session)
    for i in range(4):
        await svc.record(QualityMetricInput(
            chapter_id=f"ch_{i}", novel_id="n_1", phase="critic",
            attempt_index=1, overall_score=60, gate_status="warn", prompt_version="v1.0",
        ))
    for i in range(4, 8):
        await svc.record(QualityMetricInput(
            chapter_id=f"ch_{i}", novel_id="n_1", phase="critic",
            attempt_index=1, overall_score=90, gate_status="pass", prompt_version="v2.0",
        ))
    await async_session.flush()

    result = await runner.results(ab.id)
    assert result.winner == "challenger"
    assert result.status == "completed"
    # Check the test record itself got marked completed
    ab_after = await runner.repo.get(ab.id)
    assert ab_after.status == "completed"
    assert ab_after.winner == "challenger"


@pytest.mark.asyncio
async def test_declare_winner_sets_active(async_session):
    runner = ABTestRunner(async_session)
    from novel_dev.services.prompt_registry import PromptRegistry
    reg = PromptRegistry(async_session)
    await reg.create_version("critic", "v1.0", "v1 content", is_active=True)
    await reg.create_version("critic", "v2.0", "v2 content")
    ab = await runner.start("critic", "v1.0", "v2.0")
    await runner.declare_winner(ab.id, "challenger")
    assert await reg.get_active("critic") == "v2 content"


@pytest.mark.asyncio
async def test_declare_winner_raises_on_invalid(async_session):
    runner = ABTestRunner(async_session)
    ab = await runner.start("critic", "v1.0", "v2.0")
    with pytest.raises(ValueError, match="Invalid winner"):
        await runner.declare_winner(ab.id, "invalid_choice")


@pytest.mark.asyncio
async def test_declare_winner_raises_when_test_missing(async_session):
    runner = ABTestRunner(async_session)
    with pytest.raises(ValueError, match="not found"):
        await runner.declare_winner("missing_id", "challenger")
