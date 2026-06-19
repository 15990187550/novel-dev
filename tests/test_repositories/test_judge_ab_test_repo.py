import pytest
from novel_dev.db.models import JudgeABTest
from novel_dev.repositories.judge_ab_test_repo import JudgeABTestRepository


@pytest.mark.asyncio
async def test_create_and_get(async_session):
    repo = JudgeABTestRepository(async_session)
    ab = await repo.create(
        baseline_version="judge-v1",
        challenger_version="judge-v2",
        config={"min_samples": 30},
    )
    fetched = await repo.get(ab.id)
    assert fetched.baseline_version == "judge-v1"
    assert fetched.status == "running"


@pytest.mark.asyncio
async def test_list_running(async_session):
    repo = JudgeABTestRepository(async_session)
    await repo.create(baseline_version="v1", challenger_version="v2")
    await repo.create(baseline_version="v3", challenger_version="v4")
    running = await repo.list_by_status("running")
    assert len(running) == 2


@pytest.mark.asyncio
async def test_complete(async_session):
    repo = JudgeABTestRepository(async_session)
    ab = await repo.create(baseline_version="v1", challenger_version="v2")
    await repo.complete(ab.id, winner="v2")
    fetched = await repo.get(ab.id)
    assert fetched.status == "completed"
    assert fetched.winner == "v2"
    assert fetched.ended_at is not None
